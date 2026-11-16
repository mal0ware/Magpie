from magpie.models import NONE, Item
from magpie.pipeline import fetch
from magpie.store import Store, thumb_path


def test_photo_carousel_keeps_its_cover_and_is_not_downloaded(tmp_path, monkeypatch):
    monkeypatch.setenv("MAGPIE_HOME", str(tmp_path))
    monkeypatch.setattr(fetch, "download_url", lambda url, dest, timeout=60: dest.write_bytes(b"jpg"))
    monkeypatch.setattr(fetch, "ytdlp_download", lambda *a: (_ for _ in ()).throw(AssertionError("no")))
    s = Store()
    s.add_listing([Item(shortcode="p", url="u", kind="carousel", thumb_url="https://cdn/t.jpg")])
    assert fetch.fetch_item(s, s.get("p")) == NONE
    got = s.get("p")
    assert got.media_status == NONE and got.transcript_status == NONE
    assert thumb_path("p").read_bytes() == b"jpg"
