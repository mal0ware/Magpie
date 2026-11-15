from magpie.models import DONE, PENDING, Item
from magpie.store import Store


def _items(*codes):
    return [Item(shortcode=c, url=f"https://www.instagram.com/reel/{c}/") for c in codes]


def test_listing_order_sync_and_backfill(tmp_path):
    s = Store(tmp_path / "t.db")
    assert s.add_listing(_items("c", "b")) == 2          # first sync, newest first
    assert s.add_listing(_items("a"), backfill=True) == 1  # older page
    assert s.add_listing(_items("e", "d", "c")) == 2      # later sync overlaps on c
    assert [i.shortcode for i in s.recent()] == ["e", "d", "c", "b", "a"]
    assert [i.shortcode for i in s.recent(limit=2)] == ["e", "d"]
    assert s.count() == 5


def test_relisting_refreshes_expiring_urls_only(tmp_path):
    s = Store(tmp_path / "t.db")
    s.add_listing(_items("a"))
    s.set_media("a", DONE, duration=12.5)
    again = _items("a")
    again[0].video_url = "https://cdn/new.mp4"
    assert s.add_listing(again) == 0
    got = s.get("a")
    assert got.video_url == "https://cdn/new.mp4"
    assert got.media_status == DONE and got.duration == 12.5
    assert got.transcript_status == PENDING
    assert [i.shortcode for i in s.with_status("transcript_status", PENDING)] == ["a"]
