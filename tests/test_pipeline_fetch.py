"""fetch: no network, no ffmpeg. The downloader pieces are replaced."""

import pytest

from magpie import store as paths
from magpie.models import DONE, FAILED, NONE, PENDING, Item
from magpie.pipeline import fetch
from magpie.store import Store

VIDEO = b"v" * 20_000


def item(sc, **kw):
    return Item(shortcode=sc, url=f"https://www.instagram.com/reel/{sc}/", **kw)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("MAGPIE_HOME", str(tmp_path))
    return Store()


@pytest.fixture
def net(monkeypatch):
    """Fake downloader. Records calls; behaviour is set per test."""
    class Net:
        http, ytdlp, cuts = [], [], []
        dead_urls: set = set()
        ytdlp_error: dict = {}
        info: dict = {}

    def download_url(url, dest, timeout=60):
        Net.http.append(url)
        if url in Net.dead_urls:
            raise OSError("403 Forbidden")
        dest.write_bytes(VIDEO if "video" in url else b"jpg")

    def ytdlp_download(post_url, dest):
        Net.ytdlp.append(post_url)
        for sc, err in Net.ytdlp_error.items():
            if sc in post_url:
                raise RuntimeError(err)
        dest.write_bytes(VIDEO)
        return dict(Net.info)

    def cut_thumb(video, dest):
        Net.cuts.append(dest)
        dest.write_bytes(b"frame")

    monkeypatch.setattr(fetch, "download_url", download_url)
    monkeypatch.setattr(fetch, "ytdlp_download", ytdlp_download)
    monkeypatch.setattr(fetch, "cut_thumb", cut_thumb)
    monkeypatch.setattr(fetch, "probe_duration", lambda video: 12.5)
    return Net


def test_listing_urls_are_used_first(store, net):
    store.add_listing([item("A", video_url="https://cdn/video-a", thumb_url="https://cdn/thumb-a")])
    counts = fetch.fetch_pending(store, delay=0)
    assert counts == {"done": 1, "none": 0, "failed": 0, "total": 1}
    assert net.ytdlp == [] and net.cuts == []
    assert paths.video_path("A").read_bytes() == VIDEO
    assert paths.thumb_path("A").read_bytes() == b"jpg"
    got = store.get("A")
    assert (got.media_status, got.duration, got.error) == (DONE, 12.5, None)


def test_expired_cdn_url_falls_back_to_ytdlp_and_cuts_a_thumb(store, net):
    net.dead_urls = {"https://cdn/video-a"}
    store.add_listing([item("A", video_url="https://cdn/video-a")])
    fetch.fetch_pending(store, delay=0)
    assert net.ytdlp == ["https://www.instagram.com/reel/A/"]
    assert paths.thumb_path("A").read_bytes() == b"frame"
    assert store.get("A").media_status == DONE


def test_ytdlp_fills_in_author_caption_and_thumbnail_for_bare_urls(store, net):
    net.info = {"channel": "somebody", "description": "line one\nline two",
                "thumbnail": "https://cdn/thumb-x"}
    store.add_listing([item("A"), item("B", author="kept", caption="kept too")])
    fetch.fetch_pending(store, delay=0)
    a, b = store.get("A"), store.get("B")
    assert (a.author, a.caption) == ("somebody", "line one\nline two")
    assert (b.author, b.caption) == ("kept", "kept too")
    assert net.cuts == []  # yt-dlp's thumbnail was enough
    assert a.media_status == DONE and a.saved_seq == 2  # order untouched


def test_image_posts_have_nothing_to_do(store, net):
    store.add_listing([item("IMG", kind="image")])
    counts = fetch.fetch_pending(store, delay=0)
    got = store.get("IMG")
    assert (got.media_status, got.transcript_status) == (NONE, NONE)
    assert counts["none"] == 1 and net.http == [] and net.ytdlp == []


def test_one_failure_does_not_stop_the_batch(store, net):
    net.ytdlp_error = {"/B/": "login required"}
    store.add_listing([item("A"), item("B"), item("C")])
    lines = []
    counts = fetch.fetch_pending(store, delay=0, progress=lines.append)
    assert counts == {"done": 2, "none": 0, "failed": 1, "total": 3}
    b = store.get("B")
    assert b.media_status == FAILED and "login required" in b.error
    assert not paths.video_path("B").exists()
    assert store.get("A").media_status == store.get("C").media_status == DONE
    assert len(lines) == 3 and "FAILED" in lines[1]


def test_last_limits_to_most_recently_saved_and_retry_takes_failed(store, net):
    net.ytdlp_error = {"/A/": "boom"}
    store.add_listing([item("A"), item("B"), item("C")])  # A is newest
    fetch.fetch_pending(store, last=2, delay=0)
    assert [store.get(s).media_status for s in "ABC"] == [FAILED, DONE, PENDING]

    net.ytdlp_error = {}
    assert fetch.fetch_pending(store, last=2, delay=0)["total"] == 0  # failed is not pending
    assert fetch.fetch_pending(store, last=2, delay=0, retry=True)["done"] == 1
    a = store.get("A")
    assert a.media_status == DONE and a.error is None


def test_tiny_download_is_not_a_video(store, net, monkeypatch):
    monkeypatch.setattr(fetch, "ytdlp_download",
                        lambda url, dest: dest.write_bytes(b"<html>") and {})
    store.add_listing([item("A")])
    fetch.fetch_pending(store, delay=0)
    assert store.get("A").media_status == FAILED
    assert not paths.video_path("A").exists()
