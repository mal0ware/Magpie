import sqlite3

import pytest

from magpie import cli, manage
from magpie.models import DONE, FREED, NONE, PENDING, Item
from magpie.store import Store, item_dir, thumb_path, transcript_path, video_path
from magpie.web import seams


@pytest.fixture
def lib(tmp_path, monkeypatch):
    """Five items, e newest. a-d have a video on disk; a-c are transcribed."""
    monkeypatch.setenv("MAGPIE_HOME", str(tmp_path))
    s = Store()
    s.add_listing([Item(shortcode=c, url=f"https://www.instagram.com/reel/{c}/") for c in "edcba"])
    for c in "abcd":
        video_path(c).write_bytes(b"v" * 1000)
        thumb_path(c).write_bytes(b"t")
        s.set_media(c, DONE)
    for c in "abc":
        transcript_path(c).write_text("[0:00] hi", encoding="utf-8")
        s.set_transcript(c, DONE)
    return s


def test_free_deletes_only_the_video(lib):
    assert manage.free(lib, ["a", "a", "ghost"]) == (1, 1000)
    assert not video_path("a").exists()
    assert thumb_path("a").exists() and transcript_path("a").exists()
    assert lib.get("a").media_status == FREED and lib.get("a").transcript_status == DONE
    assert lib.count() == 5  # still in the roll


def test_free_keeps_a_video_that_is_not_transcribed_yet(lib):
    said = []
    assert manage.free(lib, ["d", "e"], log=said.append) == (0, 0)
    assert video_path("d").exists() and lib.get("d").media_status == DONE
    assert "not been transcribed" in said[0]


def test_free_older_than_keeps_the_newest(lib):
    assert manage.older_than(lib, 3) == ["b", "a"]
    assert cli.main(["free", "--keep", "3"]) == 0
    assert not video_path("a").exists() and not video_path("b").exists()
    assert video_path("c").exists()
    assert cli.main(["free"]) == 1


def test_freed_video_is_not_downloaded_again(lib):
    manage.free(lib, ["a"])
    assert "a" not in [i.shortcode for i in lib.with_status("media_status", PENDING)]


def test_remove_hides_it_and_a_sync_does_not_bring_it_back(lib):
    assert manage.remove(lib, ["c"]) == 1
    assert not (item_dir("d").parent / "c").exists()
    assert [i.shortcode for i in lib.recent()] == ["e", "d", "b", "a"]
    assert lib.count() == 4 and lib.known("c")
    assert lib.add_listing([Item(shortcode="c", url="u")]) == 0
    assert lib.count() == 4
    assert manage.remove(lib, ["c"]) == 0  # already gone


def test_old_libraries_gain_the_hidden_column(tmp_path):
    path = tmp_path / "old.db"
    cols = [f for f in Item.__dataclass_fields__ if f != "hidden"]
    db = sqlite3.connect(path)
    db.execute(f"CREATE TABLE items ({', '.join(cols)})")
    db.execute(f"INSERT INTO items (shortcode, url, saved_seq, media_status, transcript_status) "
               "VALUES ('x', 'u', 1, 'done', 'none')")
    db.commit()
    db.close()
    s = Store(path)
    assert [i.shortcode for i in s.recent()] == ["x"] and s.get("x").hidden == 0


def test_media_id_is_the_shortcode_in_base_64():
    assert manage.media_id("B") == "1"
    assert manage.media_id("BA") == "64"
    assert manage.media_id("AAAAAAAAAA_") == "63"
    assert manage.media_id("AAAAAAAAAABextra-private-suffix") == "1"  # first eleven only


def test_unsave_asks_once_per_post_then_removes_it(lib):
    asked, naps = [], []

    def request(action, params):
        asked.append((action, params))
        return {"ok": True, "data": {"status": 200, "body": {"status": "ok"}}}

    assert manage.unsave(lib, ["b", "a"], request=request, sleep=naps.append) == 2
    assert asked == [("unsave", {"media_id": manage.media_id("b")}),
                     ("unsave", {"media_id": manage.media_id("a")})]
    assert len(naps) == 1 and 2.0 <= naps[0] <= 4.0
    assert [i.shortcode for i in lib.recent()] == ["e", "d", "c"]


@pytest.mark.parametrize("reply, said", [
    ({"ok": True, "data": {"status": 429, "body": {}}}, "rate limiting"),
    ({"ok": True, "data": {"status": 200, "body": {"status": "fail", "message": "nope"}}}, "nope"),
    ({"ok": True, "data": {"status": 200, "url": "https://www.instagram.com/accounts/login/",
                           "body": None}}, "login"),
    ({"ok": False, "error": "unknown action: unsave"}, "reload"),
    ({"ok": False, "error": "extension is not connected"}, "not connected"),
])
def test_unsave_stops_at_the_first_trouble_and_changes_nothing_more(lib, reply, said):
    replies = [{"ok": True, "data": {"status": 200, "body": {"status": "ok"}}}, reply]
    calls = []

    def request(action, params):
        calls.append(params)
        return replies[len(calls) - 1]

    with pytest.raises(manage.UnsaveStopped, match=said):
        manage.unsave(lib, ["c", "b", "a"], request=request, sleep=lambda s: None)
    assert len(calls) == 2  # never reached a
    assert [i.shortcode for i in lib.recent()] == ["e", "d", "b", "a"]  # only c went


def test_page_actions_build_safe_commands():
    assert seams.command("remove", {"shortcodes": ["-abc", "Def_1"]})[3:] == ["remove", "--", "-abc", "Def_1"]
    assert seams.command("unsave", {"shortcodes": ["a"]})[3:] == ["unsave", "--", "a"]
    assert seams.command("free", {"keep": 100})[3:] == ["free", "--keep", "100"]
    assert seams.command("free", {"shortcodes": ["a"]})[3:] == ["free", "--", "a"]
    for bad in ({}, {"shortcodes": []}, {"shortcodes": ["a b"]}, {"shortcodes": ["--all"], "x": 1},
                {"shortcodes": "a"}):
        if bad.get("shortcodes") == ["--all"]:
            assert seams.command("remove", bad)[3:] == ["remove", "--", "--all"]  # inert after --
            continue
        with pytest.raises(ValueError):
            seams.command("remove", bad)
    assert seams.available()["unsave"] is True
    ok, why = seams.Jobs().start("unsave", {})
    assert not ok and "shortcodes" in why


def test_remove_accepts_a_shortcode_that_starts_with_a_dash(lib):
    lib.add_listing([Item(shortcode="-x9", url="u")])
    assert cli.main(["remove", "--", "-x9"]) == 0
    assert lib.get("-x9").hidden == 1
