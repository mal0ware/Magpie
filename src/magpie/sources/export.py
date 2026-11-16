"""Listing sources that need no browser: Instagram's data export and pasted URLs.

The export ("Download your information", JSON format) has
`your_instagram_activity/saved/saved_posts.json`:

    {"saved_saved_media": [
        {"title": "<author handle>",
         "string_map_data": {"Saved on": {"href": "<post url>", "timestamp": 1700000000}}}]}

The layout has changed before, so anything else is searched for post URLs
rather than rejected.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from ..models import Item
from ..store import Store
from .feed import item_from_url


def _strings(node) -> Iterable[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


def _timestamp(node) -> int | None:
    if isinstance(node, dict):
        ts = node.get("timestamp")
        if isinstance(ts, (int, float)) and ts > 0:
            return int(ts)
        node = list(node.values())
    if isinstance(node, list):
        for v in node:
            ts = _timestamp(v)
            if ts:
                return ts
    return None


def _entries(data) -> list:
    """The list of saved-post records, wherever the export put it."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("saved_saved_media", "saved_saved_collections"):
            if isinstance(data.get(key), list):
                return data[key]
        for v in data.values():
            if isinstance(v, list):
                return v
    return []


def parse_export(data) -> list[Item]:
    """Items from a parsed saved_posts.json, newest saved first."""
    found: list[tuple[int | None, Item]] = []
    seen: set[str] = set()
    for entry in _entries(data):
        item = next((i for i in map(item_from_url, _strings(entry)) if i), None)
        if not item or item.shortcode in seen:
            continue
        seen.add(item.shortcode)
        if isinstance(entry, dict) and isinstance(entry.get("title"), str):
            item.author = entry["title"].lstrip("@")
        found.append((_timestamp(entry), item))
    if found and all(ts for ts, _ in found):
        found.sort(key=lambda pair: pair[0], reverse=True)  # stable: ties keep file order
    return [item for _, item in found]


def import_export(store: Store, path: Path | str) -> tuple[int, int]:
    """Import a saved_posts.json. Returns (new, total found).

    Into an empty library the posts go in as listed. Into a library that
    already has posts, the ones we do not have are treated as older history
    and placed below everything else: the export cannot say where they fall
    among posts the browser sync already listed.
    """
    items = parse_export(json.loads(Path(path).read_text(encoding="utf-8-sig")))
    backfill = store.count() > 0
    return store.add_listing(items, backfill=backfill), len(items)


def add_urls(store: Store, urls: Iterable[str]) -> tuple[int, list[Item], list[str]]:
    """Add pasted post URLs as the most recent saves, the first URL on top.

    Returns (new, items recognised, strings that were not post URLs).
    """
    items: list[Item] = []
    bad: list[str] = []
    seen: set[str] = set()
    for url in urls:
        url = url.strip()
        if not url:
            continue
        item = item_from_url(url)
        if not item:
            bad.append(url)
        elif item.shortcode not in seen:
            seen.add(item.shortcode)
            items.append(item)
    return store.add_listing(items), items, bad
