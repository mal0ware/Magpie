"""The one record every part of Magpie shares. See docs/PLAN.md."""

from dataclasses import dataclass

# media_status / transcript_status values
PENDING = "pending"
DONE = "done"
FAILED = "failed"
NONE = "none"  # nothing to do: an image post, or a video with no speech
FREED = "freed"  # media_status only: the video was deleted to save space


@dataclass
class Item:
    shortcode: str  # primary key, the bit after /reel/ or /p/
    url: str  # canonical https://www.instagram.com/reel/<shortcode>/
    kind: str = "reel"  # reel | video | image | carousel
    author: str = ""  # handle without the @
    caption: str = ""
    taken_at: int | None = None  # unix seconds the post was published
    duration: float | None = None  # seconds
    video_url: str | None = None  # CDN url from the listing; expires in hours
    thumb_url: str | None = None  # CDN url from the listing; expires in hours
    collection: str | None = None  # named saved collection, if known
    # Set by the store, not by sources:
    saved_seq: int = 0  # higher = saved more recently
    first_seen: float = 0.0
    media_status: str = PENDING
    transcript_status: str = PENDING
    error: str | None = None
    hidden: int = 0  # 1 = removed from the roll; kept so a sync does not bring it back
