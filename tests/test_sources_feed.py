import json
from pathlib import Path

import pytest

from magpie.sources import feed

FIX = Path(__file__).parent / "fixtures"


def _body(n):
    return json.loads((FIX / f"sources_saved_page_{n}.json").read_text(encoding="utf-8"))


def _reply(n=1, **over):
    data = {"status": 200, "url": "https://www.instagram.com/api/v1/feed/saved/posts/",
            "page_url": "https://www.instagram.com/", "logged_in": True, "body": _body(n)}
    data.update(over)
    return {"ok": True, "data": data}


def test_page_maps_every_field():
    page = feed.read_reply(_reply(1))
    assert page.next_max_id == "QVFDcursorPage2" and page.more_available
    reel, image, carousel = page.items

    assert reel.shortcode == "DReelAAA111"
    assert reel.url == "https://www.instagram.com/reel/DReelAAA111/"
    assert reel.kind == "reel"
    assert reel.author == "cook.with.sam"
    assert reel.caption.startswith("3 ingredient flatbread\n\n200g")
    assert reel.taken_at == 1762000000
    assert reel.duration == pytest.approx(42.366)
    assert reel.video_url == "https://cdn.example/v/reelA_720.mp4"  # the largest version
    assert reel.thumb_url == "https://cdn.example/t/reelA_720.jpg"

    assert image.kind == "image" and image.url == "https://www.instagram.com/p/DImageBBB22/"
    assert image.caption == "" and image.video_url is None and image.duration is None
    assert image.thumb_url == "https://cdn.example/t/imgB.jpg"

    assert carousel.kind == "carousel"
    assert carousel.video_url == "https://cdn.example/v/carC_2.mp4"  # first video child
    assert carousel.duration == 15.0
    assert carousel.thumb_url == "https://cdn.example/t/carC_1.jpg"


def test_last_page_and_entries_without_a_shortcode():
    page = feed.read_reply(_reply(2))
    assert [i.shortcode for i in page.items] == ["DVideoDDD44"]
    assert page.items[0].kind == "video"
    assert page.items[0].url == "https://www.instagram.com/p/DVideoDDD44/"
    assert page.next_max_id is None and not page.more_available


@pytest.mark.parametrize("reply, kind", [
    ({"ok": True, "data": {"status": 429, "body": None, "snippet": "<html>"}}, feed.RATE_LIMITED),
    ({"ok": True, "data": {"status": 400, "body": {
        "message": "Please wait a few minutes before you try again.", "status": "fail"}}},
     feed.RATE_LIMITED),
    ({"ok": True, "data": {"status": 200, "redirected": True, "body": None,
                           "url": "https://www.instagram.com/accounts/login/?next=%2Fapi"}},
     feed.LOGIN_REQUIRED),
    ({"ok": True, "data": {"status": 401, "body": {"message": "login_required", "status": "fail"}}},
     feed.LOGIN_REQUIRED),
    ({"ok": True, "data": {"status": 200, "logged_in": False, "body": {"status": "ok", "items": []}}},
     feed.LOGIN_REQUIRED),
    ({"ok": True, "data": {"status": 400, "body": {
        "message": "checkpoint_required", "checkpoint_url": "/challenge/abc/", "status": "fail"}}},
     feed.CHECKPOINT),
    ({"ok": True, "data": {"status": 200, "body": None,
                           "url": "https://www.instagram.com/challenge/?next=/api"}},
     feed.CHECKPOINT),
    ({"ok": True, "data": {"status": 200, "body": None, "snippet": "<!DOCTYPE html>"}},
     feed.UNEXPECTED),
    ({"ok": True, "data": {"status": 500, "body": {"status": "fail"}}}, feed.UNEXPECTED),
    ({"ok": True, "data": {"fetch_error": "TypeError: Failed to fetch"}}, feed.UNEXPECTED),
    ({"ok": False, "error": "extension not connected"}, feed.NOT_CONNECTED),
    ({"ok": False, "error": "extension timed out"}, feed.UNEXPECTED),
])
def test_anything_but_a_clean_page_stops(reply, kind):
    with pytest.raises(feed.SourceStop) as exc:
        feed.read_reply(reply)
    assert exc.value.kind == kind


@pytest.mark.parametrize("url, code, kind, canonical", [
    ("https://www.instagram.com/reel/DReelAAA111/?igsh=abc", "DReelAAA111", "reel",
     "https://www.instagram.com/reel/DReelAAA111/"),
    ("instagram.com/reels/Ab_c-9/", "Ab_c-9", "reel", "https://www.instagram.com/reel/Ab_c-9/"),
    ("https://www.instagram.com/p/Cxyz123/", "Cxyz123", "video", "https://www.instagram.com/p/Cxyz123/"),
    ("https://www.instagram.com/some.user/p/Cxyz123/", "Cxyz123", "video",
     "https://www.instagram.com/p/Cxyz123/"),
    ("https://www.instagram.com/tv/B0000/", "B0000", "video", "https://www.instagram.com/p/B0000/"),
])
def test_item_from_url(url, code, kind, canonical):
    item = feed.item_from_url(url)
    assert (item.shortcode, item.kind, item.url) == (code, kind, canonical)


@pytest.mark.parametrize("url", ["https://www.instagram.com/cook.with.sam/", "https://example.com/reel/x/", ""])
def test_item_from_url_rejects_non_posts(url):
    assert feed.item_from_url(url) is None
