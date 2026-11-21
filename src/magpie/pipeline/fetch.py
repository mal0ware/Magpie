"""Download videos and thumbnails for items whose media is pending.

Video: the listing's CDN `video_url` first (it expires within hours), then
yt-dlp on the post URL. Thumbnail: the listing's `thumb_url`, then the one
yt-dlp reports, then a frame cut with ffmpeg.
"""

import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Callable

from .. import store as paths
from ..models import DONE, FAILED, FREED, NONE, PENDING, Item
from ..store import Store

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
MIN_VIDEO_BYTES = 10_000  # anything smaller is an error page, not a video

Progress = Callable[[str], None]


# -- the pieces tests replace --------------------------------------------------

def download_url(url: str, dest: Path, timeout: float = 60) -> None:
    """Plain HTTP GET to dest, via a .part file so a crash leaves nothing half-written."""
    part = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r, open(part, "wb") as f:
            while chunk := r.read(1 << 16):
                f.write(chunk)
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)


class _QuietLogger:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def ytdlp_download(post_url: str, dest: Path) -> dict:
    """Download the post's (first) video to dest as mp4. Returns yt-dlp's info dict."""
    import yt_dlp

    stem = dest.with_name(dest.stem + ".ytdlp")
    opts = {
        "outtmpl": str(stem).replace("%", "%%") + ".%(ext)s",
        "format": "bv*+ba/b",
        "merge_output_format": "mp4",
        "playlist_items": "1",  # a carousel is a playlist; take its first video
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _QuietLogger(),  # errors come back as exceptions; don't print them twice
        "retries": 1,  # go slow: a refusal means stop, not retry harder
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(post_url, download=True) or {}
        if info.get("entries"):
            info = info["entries"][0] or {}
        got = [p for p in dest.parent.glob(stem.name + ".*") if p.suffix != ".part"]
        if not got:
            raise RuntimeError("yt-dlp reported success but wrote no file")
        src = max(got, key=lambda p: p.stat().st_size)
        if src.suffix.lower() == ".mp4":
            src.replace(dest)
        else:
            _run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src),
                  "-c", "copy", str(dest)])
        return info
    finally:
        for p in dest.parent.glob(stem.name + ".*"):
            p.unlink(missing_ok=True)


def cut_thumb(video: Path, dest: Path) -> None:
    """One frame from about a second in (or the first frame of a very short clip)."""
    for seek in ("1", "0"):
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", seek, "-i", str(video),
             "-frames:v", "1", "-vf", "scale=540:-2", "-q:v", "3", str(dest)],
            capture_output=True)
        if dest.exists() and dest.stat().st_size:
            return
    raise RuntimeError("ffmpeg could not cut a thumbnail")


def probe_duration(video: Path) -> float | None:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(video)],
        capture_output=True, text=True)
    try:
        return round(float(r.stdout.strip()), 2)
    except ValueError:
        return None


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip()[-400:] or f"{cmd[0]} failed")


# -- one item ------------------------------------------------------------------

def _short(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}".replace("\n", " ")[:500]


def fetch_item(store: Store, item: Item) -> str:
    """Fetch one item's media. Returns the new media_status. Raises on failure."""
    sc = item.shortcode
    video, thumb = paths.video_path(sc), paths.thumb_path(sc)
    # A listed carousel with no video_url is all photos: the listing gives a
    # video_url whenever a slide is a video. Keep its cover for the roll.
    photos_only = item.kind == "carousel" and item.thumb_url and not item.video_url
    if item.kind == "image" or photos_only:
        if item.thumb_url:
            try:
                download_url(item.thumb_url, thumb)
            except Exception:
                thumb.unlink(missing_ok=True)
        store.set_media(sc, NONE)
        store.set_transcript(sc, NONE)
        return NONE

    info: dict = {}
    got = False
    if item.video_url:
        try:
            download_url(item.video_url, video)
            got = video.stat().st_size >= MIN_VIDEO_BYTES
        except Exception:
            got = False  # expired CDN link is the normal case; yt-dlp is next
    if not got:
        video.unlink(missing_ok=True)
        info = ytdlp_download(item.url, video)
        if not video.exists() or video.stat().st_size < MIN_VIDEO_BYTES:
            video.unlink(missing_ok=True)
            raise RuntimeError("download produced no usable video")

    for url in (item.thumb_url, info.get("thumbnail")):
        if url and not (thumb.exists() and thumb.stat().st_size):
            try:
                download_url(url, thumb)
            except Exception:
                thumb.unlink(missing_ok=True)
    if not (thumb.exists() and thumb.stat().st_size):
        try:
            cut_thumb(video, thumb)
        except Exception:
            pass  # a missing thumbnail is not worth failing the item over

    # A hand-added URL has no author or caption; yt-dlp knows them. A re-listing
    # of a known item is the store's way to fill fields in.
    fill = Item(
        shortcode=sc, url=item.url,
        author="" if item.author else str(info.get("channel") or ""),
        caption="" if item.caption else str(info.get("description") or ""),
    )
    if fill.author or fill.caption:
        store.add_listing([fill])

    store.set_media(sc, DONE, duration=probe_duration(video) or info.get("duration"))
    return DONE


# -- thumbnails only -------------------------------------------------------------

THUMB_GIVE_UP = 5  # this many refusals in a row means the links have expired


def fetch_thumbs(store: Store, *, progress: Progress | None = None) -> dict:
    """Download the thumbnail of every post in the roll that has none yet, and
    nothing else. Thumbnails are small (tens of kB), so the roll can show every
    save without any video on disk. `magpie sync` runs this, because the
    listing's thumbnail links only work for a few hours after a sync.

    Returns {"done", "failed", "skipped", "total"}. A run of failures stops the
    batch: that is what expired links look like, and the rest would fail too.
    """
    say = progress or (lambda _msg: None)
    items = [i for i in store.recent(-1) if i.thumb_url
             and not (paths.thumb_path(i.shortcode).is_file()
                      and paths.thumb_path(i.shortcode).stat().st_size)]
    counts = {"done": 0, "failed": 0, "skipped": 0, "total": len(items)}
    misses = 0
    for n, item in enumerate(items, 1):
        thumb = paths.thumb_path(item.shortcode)
        try:
            download_url(item.thumb_url, thumb, timeout=20)
        except Exception:
            thumb.unlink(missing_ok=True)
            counts["failed"] += 1
            misses += 1
            if misses >= THUMB_GIVE_UP:
                counts["skipped"] = len(items) - n
                break
            continue
        misses = 0
        counts["done"] += 1
        if counts["done"] % 25 == 0:
            say(f"thumbnails: {counts['done']} of {len(items)}")
    return counts


# -- the batch -----------------------------------------------------------------

def _select(store: Store, column: str, last: int | None, retry: bool,
            shortcodes: list[str] | None = None) -> list[Item]:
    if shortcodes:
        # Posts asked for by name (a click in the roll): take them whatever
        # happened before, including a video that was freed or failed.
        found = (store.get(c) for c in dict.fromkeys(shortcodes))
        return [i for i in found if i and not i.hidden
                and getattr(i, column) in (PENDING, FAILED, FREED)]
    want = (PENDING, FAILED) if retry else (PENDING,)
    pool = store.recent(last) if last else store.recent(-1)
    return [i for i in pool if getattr(i, column) in want]


def fetch_pending(store: Store, last: int | None = None, *, retry: bool = False,
                  delay: float = 1.5, progress: Progress | None = None,
                  shortcodes: list[str] | None = None) -> dict:
    """Fetch media for pending items, newest saved first.

    `last` limits the batch to the N most recently saved items. `retry` also
    takes items that failed before. `delay` seconds pass between downloads.
    `shortcodes` names the posts to fetch instead, and overrides both.
    One failed item never stops the batch: the error is recorded on the item.
    Returns counts: {"done", "none", "failed", "total"}.
    """
    say = progress or (lambda _msg: None)
    items = _select(store, "media_status", last, retry, shortcodes)
    counts = {"done": 0, "none": 0, "failed": 0, "total": len(items)}
    for n, item in enumerate(items, 1):
        t0 = time.perf_counter()
        try:
            status = fetch_item(store, item)
        except Exception as e:  # noqa: BLE001 - one bad item must not stop the batch
            status = FAILED
            store.set_media(item.shortcode, FAILED, _short(e))
            say(f"[{n}/{len(items)}] fetch {item.shortcode}: FAILED {_short(e)}")
        else:
            say(f"[{n}/{len(items)}] fetch {item.shortcode}: {status} "
                f"({time.perf_counter() - t0:.1f}s)")
        counts[status] += 1
        if delay and status != NONE and n < len(items):
            time.sleep(delay)
    return counts
