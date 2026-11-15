"""Banner format for pasting transcripts into an LLM. See docs/PLAN.md.

Track C imports `format_item` and `format_many`; keep the names.
"""

from .. import store
from ..models import FAILED, NONE, Item

RULE = "=" * 80


def format_timestamp(seconds: float) -> str:
    """`[m:ss]`, minutes unbounded."""
    s = max(0, int(seconds))
    return f"[{s // 60}:{s % 60:02d}]"


def _body(item: Item) -> str:
    if item.transcript_status == NONE:
        return "(no speech)"
    path = store.transcript_path(item.shortcode)
    text = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    if text:
        return text
    if FAILED in (item.media_status, item.transcript_status):
        return "(download failed)" if item.media_status == FAILED else "(transcription failed)"
    return "(no transcript yet)"


def format_item(item: Item) -> str:
    """One banner plus transcript body, no trailing newline."""
    return "\n".join([
        RULE,
        f"CREATOR: @{item.author}" if item.author else "CREATOR: (unknown)",
        f"URL:     {item.url}",
        f"CAPTION: {(item.caption or '').strip()}".rstrip(),
        RULE,
        "",
        _body(item),
    ])


def format_many(items: list[Item]) -> str:
    """Items in the order given, separated by a blank line."""
    if not items:
        return ""
    return "\n\n".join(format_item(i) for i in items) + "\n"
