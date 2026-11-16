"""Tidying the library: free a video's disk space, take a post out of the
roll, or unsave it on Instagram.

Unsaving is the one place Magpie changes anything on the account. It only
happens for posts named explicitly, one request each, spaced out, and it stops
at the first answer that is not a plain success.
"""

import random
import shutil
import time
from collections.abc import Callable, Iterable

from .. import store as paths
from ..models import DONE, FREED, PENDING, Item
from ..store import Store

UNSAVE_DELAY = (2.0, 4.0)  # seconds between unsave requests
_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def _items(store: Store, shortcodes: Iterable[str]) -> list[Item]:
    """The named items that exist and are still in the roll, without repeats."""
    found = (store.get(c) for c in dict.fromkeys(shortcodes))
    return [i for i in found if i and not i.hidden]


def free(store: Store, shortcodes: Iterable[str],
         log: Callable[[str], None] = lambda s: None) -> tuple[int, int]:
    """Delete the video file of each item, keeping its thumbnail, caption and
    transcript. A video that has not been transcribed yet is left alone, since
    the transcript could never be made afterwards. Returns (videos freed, bytes)."""
    count = size = 0
    for item in _items(store, shortcodes):
        video = paths.video_path(item.shortcode)
        if item.media_status != DONE or not video.is_file():
            continue
        if item.transcript_status == PENDING:
            log(f"{item.shortcode}: kept, it has not been transcribed yet")
            continue
        size += video.stat().st_size
        video.unlink()
        store.set_media(item.shortcode, FREED)
        count += 1
    return count, size


def older_than(store: Store, keep: int) -> list[str]:
    """Shortcodes of everything below the `keep` most recently saved."""
    return [i.shortcode for i in store.recent(limit=-1, offset=max(0, keep))]


def remove(store: Store, shortcodes: Iterable[str]) -> int:
    """Take items out of the roll and delete their files. They stay saved on
    Instagram; Magpie remembers them so a sync does not bring them back."""
    n = 0
    for item in _items(store, shortcodes):
        shutil.rmtree(paths.home() / "library" / item.shortcode, ignore_errors=True)
        store.hide(item.shortcode)
        n += 1
    return n


def media_id(shortcode: str) -> str:
    """Instagram's numeric id for a post. A shortcode is that number written
    in base 64; private posts carry extra characters after the first eleven."""
    n = 0
    for ch in shortcode[:11]:
        n = n * 64 + _ALPHABET.index(ch)
    return str(n)


class UnsaveStopped(Exception):
    """Instagram, or the bridge, answered with something other than success."""


def unsave(store: Store, shortcodes: Iterable[str], *,
           request: Callable[[str, dict], dict] | None = None,
           sleep: Callable[[float], None] = time.sleep,
           log: Callable[[str], None] = lambda s: None) -> int:
    """Unsave each item on Instagram through the browser extension, then take
    it out of the roll. Stops at the first failure (UnsaveStopped), leaving the
    rest untouched. Returns how many were unsaved."""
    from ..sources import bridge, feed

    if request is None:
        bridge.ensure_daemon()
        request = bridge.request
    items = _items(store, shortcodes)
    done = 0
    for n, item in enumerate(items, 1):
        try:
            reply = request("unsave", {"media_id": media_id(item.shortcode)})
            if not reply.get("ok") and "unknown action" in str(reply.get("error")):
                raise UnsaveStopped(
                    "The browser extension is an older version. Open the extensions "
                    "page, press the reload arrow on Magpie Bridge, and try again.")
            feed.read_reply(reply)  # raises on rate limit, login, checkpoint, non-200
        except UnsaveStopped:
            raise
        except Exception as exc:
            raise UnsaveStopped(f"Stopped at {item.shortcode} after {done} unsaved: {exc}") from exc
        remove(store, [item.shortcode])
        done += 1
        log(f"[{n}/{len(items)}] unsaved {item.shortcode}")
        if n < len(items):
            sleep(random.uniform(*UNSAVE_DELAY))
    return done
