"""The banner format and the CLI wiring."""

import pytest

from magpie import cli as magpie_cli
from magpie import pipeline
from magpie import store as paths
from magpie.models import DONE, NONE, Item
from magpie.pipeline import cli as pipeline_cli
from magpie.pipeline.merge import format_item, format_many, format_timestamp
from magpie.store import Store

RULE = "=" * 80


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("MAGPIE_HOME", str(tmp_path))
    return Store()


def seed(store):
    """B is saved most recently and has a transcript; A has no speech."""
    store.add_listing([
        Item(shortcode="B", url="https://www.instagram.com/reel/B/", author="chef",
             caption="Recipe:\n- 2 eggs\n- salt"),
        Item(shortcode="A", url="https://www.instagram.com/reel/A/", author="dancer",
             caption="vibes"),
    ])
    paths.transcript_path("B").write_text("[0:00] Crack the eggs.\n[0:04] Add salt.\n",
                                          encoding="utf-8")
    store.set_transcript("B", DONE)
    store.set_transcript("A", NONE)


def test_timestamp():
    assert [format_timestamp(s) for s in (0, 4.9, 59.99, 60, 754)] == [
        "[0:00]", "[0:04]", "[0:59]", "[1:00]", "[12:34]"]


def test_format_item_is_exactly_the_plan_banner(store):
    seed(store)
    assert format_item(store.get("B")) == (
        f"{RULE}\n"
        "CREATOR: @chef\n"
        "URL:     https://www.instagram.com/reel/B/\n"
        "CAPTION: Recipe:\n- 2 eggs\n- salt\n"
        f"{RULE}\n"
        "\n"
        "[0:00] Crack the eggs.\n"
        "[0:04] Add salt."
    )


def test_no_speech_keeps_the_caption(store):
    seed(store)
    text = format_item(store.get("A"))
    assert "CAPTION: vibes\n" in text and text.endswith(f"{RULE}\n\n(no speech)")


def test_pending_item_says_so_instead_of_claiming_no_speech(store):
    store.add_listing([Item(shortcode="P", url="https://www.instagram.com/reel/P/")])
    text = format_item(store.get("P"))
    assert "CREATOR: (unknown)" in text and text.endswith("(no transcript yet)")


def test_format_many_separates_items_with_a_blank_line(store):
    seed(store)
    text = format_many(store.recent(30))
    assert text == format_item(store.get("B")) + "\n\n" + format_item(store.get("A")) + "\n"
    assert format_many([]) == ""


def test_copy_puts_merged_text_on_the_clipboard_and_stdout(store, monkeypatch, capsys):
    seed(store)
    clip = []
    monkeypatch.setattr(pipeline_cli, "to_clipboard", clip.append)
    assert magpie_cli.main(["copy", "--last", "1"]) == 0
    assert clip == [format_many([store.get("B")])]
    assert capsys.readouterr().out == ""

    assert magpie_cli.main(["copy", "--stdout"]) == 0
    assert capsys.readouterr().out == clip[1] == format_many(store.recent(30))


def test_copy_with_an_empty_store(store, monkeypatch):
    monkeypatch.setattr(pipeline_cli, "to_clipboard", lambda text: pytest.fail("copied"))
    assert magpie_cli.main(["copy"]) == 1


def test_commands_pass_their_flags_through(store, monkeypatch):
    calls = []
    counts = {"done": 0, "none": 0, "failed": 0, "total": 0}
    monkeypatch.setattr(pipeline, "fetch_pending",
                        lambda s, last, **kw: calls.append(("fetch", last, kw)) or counts)
    monkeypatch.setattr(pipeline, "transcribe_pending",
                        lambda s, last, **kw: calls.append(("transcribe", last, kw)) or counts)

    assert magpie_cli.main(["fetch", "--last", "5", "--retry"]) == 0
    assert magpie_cli.main(["transcribe", "--model", "tiny.en", "--device", "cpu"]) == 0
    assert magpie_cli.main(["pull"]) == 0

    (f, t, pf, pt) = calls
    assert f[:2] == ("fetch", 5) and f[2]["retry"] is True
    assert t[:2] == ("transcribe", None)
    assert (t[2]["model"], t[2]["device"]) == ("tiny.en", "cpu")
    assert (pf[0], pf[1], pt[0], pt[1]) == ("fetch", 30, "transcribe", 30)  # fetch first
