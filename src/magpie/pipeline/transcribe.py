"""Transcribe downloaded videos with faster-whisper.

Model and device: `--model` / `--device` flags, else `MAGPIE_WHISPER_MODEL` /
`MAGPIE_WHISPER_DEVICE`, else `small.en` on `auto` (CUDA, falling back to CPU
when the CUDA libraries are missing or unusable).
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from .. import store as paths
from ..models import DONE, FAILED, NONE, Item
from ..store import Store
from .fetch import Progress, _select, _short
from .merge import format_timestamp

DEFAULT_MODEL = "small.en"
_CUDA_TROUBLE = re.compile(r"cuda|cublas|cudnn|\.dll|\.so\b", re.I)


def transcript_json_path(shortcode: str) -> Path:
    return paths.transcript_path(shortcode).with_suffix(".json")


# -- the pieces tests replace --------------------------------------------------

def has_audio(video: Path) -> bool:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=index", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True)
    return bool(r.stdout.strip())


def extract_audio(video: Path):
    """The audio as 16 kHz mono float32 samples, what whisper wants.

    ffmpeg decodes straight to a pipe and the model gets the array, so
    faster-whisper's own decoder (PyAV) is never involved.
    """
    import numpy as np

    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(video),
         "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
        capture_output=True)
    if r.returncode:
        err = r.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(err[-400:] or "ffmpeg audio extraction failed")
    return np.frombuffer(r.stdout, dtype=np.float32)


def _add_nvidia_dll_dirs() -> None:
    """Let ctranslate2 find cuBLAS/cuDNN installed as pip wheels (nvidia-*-cu12)."""
    if sys.platform != "win32":
        return
    spec = importlib.util.find_spec("nvidia")
    for root in (spec.submodule_search_locations if spec else []):
        for bin_dir in Path(root).glob("*/bin"):
            if str(bin_dir) not in os.environ["PATH"]:
                os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
                os.add_dll_directory(str(bin_dir))


def load_model(name: str, device: str):
    from faster_whisper import WhisperModel

    if device == "cuda":
        _add_nvidia_dll_dirs()
    return WhisperModel(name, device=device,
                        compute_type="float16" if device == "cuda" else "int8")


def _looks_invented(seg) -> bool:
    """Whisper makes up a stock phrase ("Thank you very much.") over music and
    street noise. Those segments come out with low confidence AND a raised
    no-speech probability; real speech, even mumbled, rarely has both."""
    return (getattr(seg, "avg_logprob", 0.0) < -1.0
            and getattr(seg, "no_speech_prob", 0.0) > 0.3)


# -- model wrapper with CPU fallback ---------------------------------------------

class Transcriber:
    """Loads the model once, on first use. `device` is auto | cuda | cpu."""

    def __init__(self, model: str | None = None, device: str | None = None,
                 progress: Progress | None = None):
        self.model_name = model or os.environ.get("MAGPIE_WHISPER_MODEL") or DEFAULT_MODEL
        self.device = (device or os.environ.get("MAGPIE_WHISPER_DEVICE") or "auto").lower()
        self.active_device: str | None = None
        self._model = None
        self._say = progress or (lambda _msg: None)

    def _load(self, device: str) -> None:
        t0 = time.perf_counter()
        self._model = load_model(self.model_name, device)
        self.active_device = device
        self._say(f"whisper {self.model_name} on {device} "
                  f"(loaded in {time.perf_counter() - t0:.1f}s)")

    def _to_cpu(self, why: BaseException) -> None:
        self._say(f"CUDA unusable ({_short(why)[:160]}); falling back to CPU")
        self._load("cpu")

    def _once(self, audio) -> list[dict]:
        segments, _info = self._model.transcribe(
            audio, vad_filter=True, condition_on_previous_text=False)
        out = []
        for s in segments:  # a generator: the real work, and CUDA errors, happen here
            text = s.text.strip()
            if text and not _looks_invented(s):
                out.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": text})
        return out

    def run(self, audio) -> list[dict]:
        """Segments as {start, end, text}; empty when there is no speech."""
        if self._model is None:
            try:
                self._load("cpu" if self.device == "cpu" else "cuda")
            except Exception as e:  # noqa: BLE001
                if self.device == "cpu" or not _CUDA_TROUBLE.search(str(e)):
                    raise
                self._to_cpu(e)
        try:
            return self._once(audio)
        except Exception as e:  # noqa: BLE001
            # Missing cuBLAS/cuDNN often only shows up on the first inference.
            if self.active_device == "cpu" or not _CUDA_TROUBLE.search(str(e)):
                raise
            self._to_cpu(e)
            return self._once(audio)


# -- one item ------------------------------------------------------------------

def transcribe_item(store: Store, item: Item, transcriber: Transcriber) -> str:
    """Transcribe one item. Returns the new transcript_status. Raises on failure."""
    sc = item.shortcode
    video = paths.video_path(sc)
    if not video.exists():
        raise FileNotFoundError(f"{video} is missing; run fetch again")

    segments: list[dict] = []
    if has_audio(video):
        audio = extract_audio(video)
        if len(audio):
            segments = transcriber.run(audio)

    transcript_json_path(sc).write_text(json.dumps({
        "shortcode": sc,
        "model": transcriber.model_name,
        "device": transcriber.active_device,
        "segments": segments,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    txt = paths.transcript_path(sc)
    if not segments:
        txt.unlink(missing_ok=True)
        store.set_transcript(sc, NONE)
        return NONE
    txt.write_text(
        "".join(f"{format_timestamp(s['start'])} {s['text']}\n" for s in segments),
        encoding="utf-8")
    store.set_transcript(sc, DONE)
    return DONE


# -- the batch -----------------------------------------------------------------

def transcribe_pending(store: Store, last: int | None = None, *, model: str | None = None,
                       device: str | None = None, retry: bool = False,
                       progress: Progress | None = None,
                       transcriber: Transcriber | None = None,
                       shortcodes: list[str] | None = None) -> dict:
    """Transcribe items whose media is done and whose transcript is pending.

    Same `last` / `retry` meaning as `fetch_pending`. One failed item never
    stops the batch. Returns counts: {"done", "none", "failed", "total"}.
    """
    say = progress or (lambda _msg: None)
    items = [i for i in _select(store, "transcript_status", last, retry, shortcodes)
             if i.media_status == DONE]
    counts = {"done": 0, "none": 0, "failed": 0, "total": len(items)}
    if not items:
        return counts
    tr = transcriber or Transcriber(model, device, progress)
    for n, item in enumerate(items, 1):
        t0 = time.perf_counter()
        try:
            status = transcribe_item(store, item, tr)
        except Exception as e:  # noqa: BLE001 - one bad item must not stop the batch
            status = FAILED
            store.set_transcript(item.shortcode, FAILED, _short(e))
            say(f"[{n}/{len(items)}] transcribe {item.shortcode}: FAILED {_short(e)}")
        else:
            took = time.perf_counter() - t0
            length = f" of {item.duration:.0f}s video" if item.duration else ""
            say(f"[{n}/{len(items)}] transcribe {item.shortcode}: {status} "
                f"({took:.1f}s{length})")
        counts[status] += 1
    return counts
