import sys
import time

import pytest
from starlette.testclient import TestClient

from magpie import store
from magpie.models import DONE, FAILED, NONE, Item
from magpie.web import seams
from magpie.web.app import create_app

RULE = "=" * 80
VIDEO = bytes(range(256)) * 8  # 2048 bytes standing in for an mp4


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MAGPIE_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def client(home):
    return TestClient(create_app())


@pytest.fixture
def library(home):
    """Five items, e newest. a/b/c have media and transcripts, d has no speech,
    e is freshly listed with nothing downloaded."""
    s = store.Store()
    s.add_listing([
        Item(shortcode=c, url=f"https://www.instagram.com/reel/{c}/", author=f"maker_{c}",
             caption=f"caption {c}\nsecond line", duration=12.0,
             video_url="https://cdn.example/expiring.mp4")
        for c in "edcba"
    ])
    for c in "abcd":
        store.video_path(c).write_bytes(VIDEO)
        store.thumb_path(c).write_bytes(b"\xff\xd8jpeg")
        s.set_media(c, DONE)
    for c in "abc":
        store.transcript_path(c).write_text(f"[0:00] hello from {c}\n[0:04] bye\n", encoding="utf-8")
        s.set_transcript(c, DONE)
    s.set_transcript("d", NONE)
    s.db.close()


def test_empty_library(client):
    assert client.get("/api/items").json() == {"items": [], "total": 0, "limit": 60, "offset": 0}
    assert client.post("/api/merged", json={"last": 30}).json()["text"] == ""
    assert "Nothing saved yet" in client.get("/").text


def test_items_are_in_camera_roll_order_and_page(client, library):
    page = client.get("/api/items?limit=2").json()
    assert [i["shortcode"] for i in page["items"]] == ["e", "d"]
    assert page["total"] == 5
    rest = client.get("/api/items?limit=10&offset=2").json()
    assert [i["shortcode"] for i in rest["items"]] == ["c", "b", "a"]
    e, d = page["items"]
    assert (e["has_video"], e["has_thumb"], e["transcript_status"]) == (False, False, "pending")
    assert (d["has_video"], d["has_thumb"], d["transcript_status"]) == (True, True, "none")
    assert "video_url" not in e
    assert client.get("/api/items?limit=x").status_code == 400


def test_item_detail_has_transcript(client, library):
    a = client.get("/api/items/a").json()
    assert a["author"] == "maker_a" and a["transcript"] == "[0:00] hello from a\n[0:04] bye"
    assert client.get("/api/items/e").json()["transcript"] is None
    assert client.get("/api/items/nope").status_code == 404


def test_video_supports_range_requests(client, library):
    full = client.get("/media/a/video.mp4")
    assert full.status_code == 200 and full.content == VIDEO
    assert full.headers["content-type"] == "video/mp4"
    assert full.headers["accept-ranges"] == "bytes"
    part = client.get("/media/a/video.mp4", headers={"Range": "bytes=100-199"})
    assert part.status_code == 206
    assert part.content == VIDEO[100:200]
    assert part.headers["content-range"] == "bytes 100-199/2048"
    tail = client.get("/media/a/video.mp4", headers={"Range": "bytes=2000-"})
    assert tail.status_code == 206 and tail.content == VIDEO[2000:]


def test_media_missing_and_unknown(client, library, home):
    assert client.get("/media/a/thumb.jpg").content == b"\xff\xd8jpeg"
    assert client.get("/media/e/thumb.jpg").status_code == 404   # listed, not downloaded
    assert client.get("/media/e/video.mp4").status_code == 404
    assert client.get("/media/a/transcript.txt").status_code == 404  # only the two media names
    assert client.get("/media/zzz/video.mp4").status_code == 404
    assert client.get("/media/..%2F..%2Fmagpie.db/video.mp4").status_code == 404
    assert not (home / "library" / "zzz").exists()  # unknown codes never touch the disk


def test_merged_last_n_uses_the_banner(client, library):
    m = client.post("/api/merged", json={"last": 3}).json()
    assert m["shortcodes"] == ["e", "d", "c"] and m["count"] == 3
    assert m["without_transcript"] == 2 and m["source"] == "pipeline"
    blocks = m["text"].split("\n\n" + RULE + "\n")
    assert len(blocks) == 3
    assert m["text"].endswith(
        f"{RULE}\nCREATOR: @maker_c\nURL:     https://www.instagram.com/reel/c/\n"
        f"CAPTION: caption c\nsecond line\n{RULE}\n\n[0:00] hello from c\n[0:04] bye\n")
    assert "(no transcript yet)" in blocks[0]   # e
    assert blocks[1].endswith("(no speech)")       # d


def test_merged_selection_is_roll_order_and_reports_missing(client, library):
    m = client.post("/api/merged", json=["a", "ghost", "c", "a"]).json()
    assert m["shortcodes"] == ["c", "a"] and m["missing"] == ["ghost"]
    assert m["text"].index("@maker_c") < m["text"].index("@maker_a")
    assert client.post("/api/merged", json={"shortcodes": ["b"]}).json()["count"] == 1


def test_merged_rejects_bad_bodies(client, library):
    assert client.post("/api/merged", json={"last": "all"}).status_code == 400
    assert client.post("/api/merged", json={}).status_code == 400
    # A cross-site form post is not JSON and must not be accepted.
    assert client.post("/api/merged", data={"last": "3"}).status_code == 400


def test_merged_switches_to_the_pipeline_formatter_when_present(client, library, monkeypatch):
    import types

    fake = types.ModuleType("magpie.pipeline.merge")
    fake.format_many = lambda items: "REAL:" + ",".join(i.shortcode for i in items)
    monkeypatch.setitem(sys.modules, "magpie.pipeline.merge", fake)
    m = client.post("/api/merged", json={"last": 2}).json()
    assert m["text"] == "REAL:e,d" and m["source"] == "pipeline"


def test_failed_transcript_is_counted_and_keeps_its_error(client, library):
    s = store.Store()
    s.set_transcript("a", FAILED, "whisper blew up")
    s.db.close()
    m = client.post("/api/merged", json=["a"]).json()
    assert m["without_transcript"] == 1
    assert client.get("/api/items/a").json()["error"] == "whisper blew up"


def test_actions_refused_when_a_track_is_unavailable(client, monkeypatch):
    assert seams.available() == {"sync": True, "pull": True}
    monkeypatch.setattr(seams, "available", lambda: {"sync": False, "pull": False})
    assert client.get("/api/actions").json() == {"available": {"sync": False, "pull": False},
                                                 "job": None}
    r = client.post("/api/actions/sync", json={})
    assert r.status_code == 409 and "not available" in r.json()["error"]
    assert client.post("/api/actions/format-disk", json={}).status_code == 409
    assert client.post("/api/actions/sync", data={"x": "1"}).status_code == 415


def test_action_runs_the_cli_command_and_reports_progress(client, monkeypatch):
    monkeypatch.setattr(seams, "available", lambda: {"sync": True, "pull": True})
    seen = {}

    def fake_command(name, opts):
        seen.update(name=name, opts=opts)
        return [sys.executable, "-c", "print('page 1'); print('2 new items')"]

    monkeypatch.setattr(seams, "command", fake_command)
    assert client.post("/api/actions/pull", json={"last": 7}).status_code == 202
    job = _wait(client)
    assert seen == {"name": "pull", "opts": {"last": 7}}
    assert job["state"] == "done" and job["lines"] == ["page 1", "2 new items"]

    monkeypatch.setattr(seams, "command",
                        lambda n, o: [sys.executable, "-c", "raise SystemExit('checkpoint')"])
    assert client.post("/api/actions/sync", json={}).status_code == 202
    job = _wait(client)
    assert job["state"] == "failed" and job["lines"][-1] == "checkpoint"


def test_real_commands_are_the_cli_subcommands():
    assert seams.command("sync", {})[1:] == ["-m", "magpie.cli", "sync"]
    assert seams.command("pull", {"last": 5})[1:] == ["-m", "magpie.cli", "pull", "--last", "5"]


def test_only_loopback_host_names_are_served(home):
    c = TestClient(create_app(), base_url="http://evil.example")
    assert c.get("/api/items").status_code == 400


def test_web_subcommand_is_registered():
    import argparse

    from magpie.web import cli

    sub = argparse.ArgumentParser().add_subparsers()
    cli.register(sub)
    args = sub.choices["web"].parse_args([])
    assert args.port == 8766 and args.no_browser is False


def _wait(client):
    for _ in range(100):
        job = client.get("/api/actions").json()["job"]
        if job["state"] != "running":
            return job
        time.sleep(0.1)
    raise AssertionError("job never finished")
