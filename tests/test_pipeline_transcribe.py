"""transcribe: no GPU, no ffmpeg, no model download. The whisper model is faked."""

import json
from types import SimpleNamespace

import pytest

from magpie import store as paths
from magpie.models import DONE, FAILED, NONE, PENDING, Item
from magpie.pipeline import transcribe
from magpie.store import Store


def seg(start, end, text):
    return SimpleNamespace(start=start, end=end, text=text)


class FakeModel:
    def __init__(self, segments=(), error=None):
        self.segments, self.error = segments, error

    def transcribe(self, audio, **kw):
        def gen():
            if self.error:
                raise RuntimeError(self.error)
            yield from self.segments
        return gen(), SimpleNamespace(language="en")


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("MAGPIE_HOME", str(tmp_path))
    monkeypatch.delenv("MAGPIE_WHISPER_MODEL", raising=False)
    monkeypatch.delenv("MAGPIE_WHISPER_DEVICE", raising=False)
    monkeypatch.setattr(transcribe, "has_audio", lambda video: True)
    monkeypatch.setattr(transcribe, "extract_audio", lambda video: [0.0] * 16000)
    return Store()


def seed(store, *shortcodes, media=DONE):
    store.add_listing([Item(shortcode=s, url=f"https://www.instagram.com/reel/{s}/")
                       for s in shortcodes])
    for s in shortcodes:
        if media == DONE:
            paths.video_path(s).write_bytes(b"video")
        store.set_media(s, media)


def use_models(monkeypatch, by_device):
    """load_model(name, device) returns by_device[device], or raises it if it is an exception."""
    loads = []

    def load_model(name, device):
        loads.append((name, device))
        m = by_device[device]
        if isinstance(m, Exception):
            raise m
        return m

    monkeypatch.setattr(transcribe, "load_model", load_model)
    return loads


def test_writes_txt_and_json(store, monkeypatch):
    seed(store, "A")
    loads = use_models(monkeypatch, {"cuda": FakeModel([
        seg(0.0, 3.9, " Hello there. "), seg(4.2, 7.0, "Second line"),
        seg(7.0, 7.5, "   "), seg(83.4, 90.0, "Later")])})
    counts = transcribe.transcribe_pending(store)
    assert counts == {"done": 1, "none": 0, "failed": 0, "total": 1}
    assert loads == [("small.en", "cuda")]
    assert paths.transcript_path("A").read_text(encoding="utf-8") == (
        "[0:00] Hello there.\n[0:04] Second line\n[1:23] Later\n")
    data = json.loads(transcribe.transcript_json_path("A").read_text(encoding="utf-8"))
    assert data["segments"][0] == {"start": 0.0, "end": 3.9, "text": "Hello there."}
    assert len(data["segments"]) == 3 and data["model"] == "small.en"
    assert store.get("A").transcript_status == DONE


def test_no_speech_and_no_audio_track_give_none(store, monkeypatch):
    seed(store, "QUIET", "MUTE")
    monkeypatch.setattr(transcribe, "has_audio", lambda video: "MUTE" not in str(video))
    use_models(monkeypatch, {"cuda": FakeModel([])})
    counts = transcribe.transcribe_pending(store)
    assert counts["none"] == 2
    for s in ("QUIET", "MUTE"):
        assert store.get(s).transcript_status == NONE
        assert not paths.transcript_path(s).exists()


def test_only_items_with_media_done_are_taken(store, monkeypatch):
    seed(store, "A")
    seed(store, "B", media=PENDING)
    seed(store, "C", media=FAILED)
    use_models(monkeypatch, {"cuda": FakeModel([seg(0, 1, "hi")])})
    assert transcribe.transcribe_pending(store)["total"] == 1
    assert store.get("B").transcript_status == PENDING


def test_nothing_to_do_never_loads_the_model(store, monkeypatch):
    loads = use_models(monkeypatch, {})
    assert transcribe.transcribe_pending(store)["total"] == 0
    assert loads == []


def test_one_failure_does_not_stop_the_batch(store, monkeypatch):
    seed(store, "A", "B", "C")

    def extract(video):
        if "B" in str(video):
            raise RuntimeError("Invalid data found when processing input")
        return [0.0] * 16000

    monkeypatch.setattr(transcribe, "extract_audio", extract)
    loads = use_models(monkeypatch, {"cuda": FakeModel([seg(0, 1, "hi")])})
    counts = transcribe.transcribe_pending(store)
    assert counts == {"done": 2, "none": 0, "failed": 1, "total": 3}
    b = store.get("B")
    assert b.transcript_status == FAILED and "Invalid data" in b.error
    assert loads == [("small.en", "cuda")]  # not a CUDA problem: no fallback, one load


def test_cpu_fallback_when_cuda_fails_to_load(store, monkeypatch):
    seed(store, "A")
    loads = use_models(monkeypatch, {
        "cuda": RuntimeError("CUDA failed with error no CUDA-capable device is detected"),
        "cpu": FakeModel([seg(0, 1, "on cpu")])})
    lines = []
    transcribe.transcribe_pending(store, progress=lines.append)
    assert [d for _, d in loads] == ["cuda", "cpu"]
    assert paths.transcript_path("A").read_text(encoding="utf-8") == "[0:00] on cpu\n"
    assert any("falling back to CPU" in line for line in lines)


def test_cpu_fallback_when_cuda_libraries_are_missing_at_inference(store, monkeypatch):
    seed(store, "A", "B")
    loads = use_models(monkeypatch, {
        "cuda": FakeModel(error="Library cublas64_12.dll is not found or cannot be loaded"),
        "cpu": FakeModel([seg(0, 1, "on cpu")])})
    counts = transcribe.transcribe_pending(store)
    assert counts["done"] == 2
    assert [d for _, d in loads] == ["cuda", "cpu"]  # switched once, stayed on CPU
    data = json.loads(transcribe.transcript_json_path("B").read_text(encoding="utf-8"))
    assert data["device"] == "cpu"


def test_model_and_device_from_flag_then_env(store, monkeypatch):
    monkeypatch.setenv("MAGPIE_WHISPER_MODEL", "tiny.en")
    monkeypatch.setenv("MAGPIE_WHISPER_DEVICE", "cpu")
    seed(store, "A", "B")
    loads = use_models(monkeypatch, {"cpu": FakeModel([seg(0, 1, "x")]),
                                     "cuda": FakeModel([seg(0, 1, "x")])})
    transcribe.transcribe_pending(store, last=1)
    transcribe.transcribe_pending(store, model="medium", device="cuda")
    assert loads == [("tiny.en", "cpu"), ("medium", "cuda")]


def test_low_confidence_segment_over_noise_is_dropped(store, monkeypatch):
    seed(store, "NOISE", "MUMBLE")
    invented = SimpleNamespace(start=0, end=2, text="Thank you very much.",
                               avg_logprob=-1.06, no_speech_prob=0.42)
    mumbled = SimpleNamespace(start=0, end=2, text="real but quiet",
                              avg_logprob=-1.2, no_speech_prob=0.05)
    model = FakeModel([invented])
    use_models(monkeypatch, {"cuda": model})
    tr = transcribe.Transcriber()
    assert transcribe.transcribe_pending(store, last=1, transcriber=tr)["none"] == 1
    model.segments = [mumbled]
    assert transcribe.transcribe_pending(store, transcriber=tr)["done"] == 1
