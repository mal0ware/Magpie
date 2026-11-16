"""Turn Instagram's saved-feed JSON into `Item`s, and decide when to stop.

Nothing here talks to the network. `read_reply` takes what the bridge handed
back for one page and either returns a `Page` or raises `SourceStop`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import Item

# Reasons a listing stops early. None of them is ever retried.
RATE_LIMITED = "rate_limited"
LOGIN_REQUIRED = "login_required"
CHECKPOINT = "checkpoint"
NOT_CONNECTED = "not_connected"
UNEXPECTED = "unexpected"

_POST_URL = re.compile(
    r"instagram\.com/(?:[A-Za-z0-9_.]+/)?(p|reel|reels|tv)/([A-Za-z0-9_-]+)", re.I)


class SourceStop(Exception):
    """Listing has to stop here. `kind` is one of the constants above."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


@dataclass
class Page:
    items: list[Item] = field(default_factory=list)
    next_max_id: str | None = None
    more_available: bool = False


def post_url(shortcode: str, kind: str = "reel") -> str:
    return f"https://www.instagram.com/{'reel' if kind == 'reel' else 'p'}/{shortcode}/"


def item_from_url(url: str) -> Item | None:
    """An Item from a pasted post URL, or None if it is not one.

    A /p/ link does not say whether it is a video; it is recorded as `video`
    and the pipeline finds out when it downloads.
    """
    m = _POST_URL.search(url)
    if not m:
        return None
    kind = "reel" if m.group(1).lower() in ("reel", "reels") else "video"
    return Item(shortcode=m.group(2), url=post_url(m.group(2), kind), kind=kind)


def _best_video(media: dict) -> str | None:
    versions = [v for v in media.get("video_versions") or [] if v.get("url")]
    if not versions:
        return None
    return max(versions, key=lambda v: (v.get("width") or 0) * (v.get("height") or 0))["url"]


def _thumb(media: dict) -> str | None:
    candidates = (media.get("image_versions2") or {}).get("candidates") or []
    return next((c["url"] for c in candidates if c.get("url")), None)


def item_from_media(media: dict) -> Item | None:
    """Map one `media` object from the saved feed to an Item."""
    code = media.get("code")
    if not code:
        return None
    media_type = media.get("media_type")
    source = media  # where the video lives; a carousel keeps it in a child
    if media_type == 8:
        kind = "carousel"
        children = media.get("carousel_media") or []
        source = next((c for c in children if c.get("video_versions")), {})
        thumb = _thumb(media) or next((t for t in map(_thumb, children) if t), None)
    elif media_type == 2:
        kind = "reel" if media.get("product_type") == "clips" else "video"
        thumb = _thumb(media)
    else:
        kind = "image"
        thumb = _thumb(media)
    duration = source.get("video_duration")
    return Item(
        shortcode=code,
        url=post_url(code, kind),
        kind=kind,
        author=(media.get("user") or {}).get("username") or "",
        caption=(media.get("caption") or {}).get("text") or "",
        taken_at=int(media["taken_at"]) if media.get("taken_at") else None,
        duration=float(duration) if duration else None,
        video_url=_best_video(source),
        thumb_url=thumb,
    )


def parse_page(body: dict) -> Page:
    """A saved-feed response body to a Page, newest saved first."""
    items = []
    for entry in body.get("items") or []:
        item = item_from_media(entry.get("media") or entry)
        if item:
            items.append(item)
    cursor = body.get("next_max_id")
    return Page(items, str(cursor) if cursor else None, bool(body.get("more_available")))


def read_reply(reply: dict) -> Page:
    """Interpret the bridge's reply for one page. Raises SourceStop if the
    listing must not go on."""
    if not reply.get("ok"):
        error = str(reply.get("error") or "unknown error")
        kind = NOT_CONNECTED if "not connected" in error else UNEXPECTED
        raise SourceStop(kind, error)

    data = reply.get("data") or {}
    status = data.get("status")
    body = data.get("body") if isinstance(data.get("body"), dict) else {}
    message = str(body.get("message") or "")
    where = f"{data.get('url') or ''} {data.get('page_url') or ''}"

    if status == 429 or "wait a few minutes" in message.lower():
        raise SourceStop(RATE_LIMITED, "Instagram is rate limiting (HTTP 429).")
    if ("/challenge" in where or "/checkpoint" in where or body.get("checkpoint_url")
            or message in ("checkpoint_required", "challenge_required", "feedback_required")):
        raise SourceStop(CHECKPOINT, "Instagram is asking for a checkpoint or challenge"
                         + (f" ({message})." if message else "."))
    if ("/accounts/login" in where or message == "login_required" or status in (401, 403)
            or data.get("logged_in") is False):
        raise SourceStop(LOGIN_REQUIRED, "Instagram wants a login"
                         + (f" (HTTP {status})." if status else "."))
    if data.get("fetch_error"):
        raise SourceStop(UNEXPECTED, f"The request failed in the browser: {data['fetch_error']}")
    if status != 200 or not body or body.get("status") not in (None, "ok"):
        detail = message or data.get("snippet") or "no JSON body"
        raise SourceStop(UNEXPECTED, f"Unexpected answer from Instagram (HTTP {status}): {detail}")
    return parse_page(body)
