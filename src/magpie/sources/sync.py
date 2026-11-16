"""List the saved feed into the store, slowly and incrementally.

`sync()` is the logic, driven by any `fetch_page(max_id) -> Page` callable.
`run_sync()` is what the CLI and the web UI call: it wires `sync()` to the
browser bridge.

How a walk down the feed is written to the store (see Store.add_listing):
posts met before the first one we already have are newer than everything in
the store and go in with ONE normal call. Posts met after it that we do not
have are older than everything in the store and are backfilled page by page.
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..models import Item
from ..store import Store
from . import bridge
from .feed import NOT_CONNECTED, UNEXPECTED, Page, SourceStop, read_reply

FIRST_SYNC_LIMIT = 30  # a plain `magpie sync` on an empty library takes this many
PAGE_DELAY = (2.5, 5.0)  # seconds between pages, picked at random in this range


@dataclass
class SyncResult:
    new: int = 0  # items added to the store
    seen: int = 0  # feed entries looked at
    pages: int = 0  # requests made to Instagram
    stopped: str | None = None  # a feed.py stop kind, or None if it ran to its end
    message: str = ""  # what to tell the user when stopped or when order may be off

    @property
    def ok(self) -> bool:
        return self.stopped is None


def sync(store: Store, fetch_page: Callable[[str | None], Page], *,
         limit: int | None = None, everything: bool = False,
         delay: tuple[float, float] = PAGE_DELAY,
         sleep: Callable[[float], None] = time.sleep,
         log: Callable[[str], None] = lambda s: None) -> SyncResult:
    """Walk the saved feed newest first and record it.

    Default: stop at the first post already in the store.
    limit=N: look at the N most recently saved posts, known or not (this also
    refreshes their expiring CDN urls).
    everything=True: walk to the end of the feed.
    A SourceStop from fetch_page ends the walk at once; it is never retried.
    """
    result = SyncResult()
    started_empty = store.count() == 0
    if limit is None and not everything and started_empty:
        limit = FIRST_SYNC_LIMIT
        log(f"Empty library: taking the {limit} most recent saves. "
            "Use `magpie sync --all` for the whole history.")
    stop_at_known = limit is None and not everything

    head: list[Item] = []  # newer than anything in the store, not yet written
    head_open = True  # False once we have met (or created) the top of the store
    seen_codes: set[str] = set()
    cursor: str | None = None
    done = False

    while not done:
        if result.pages:
            sleep(random.uniform(*delay))
        try:
            page = fetch_page(cursor)
        except SourceStop as stop:
            result.stopped, result.message = stop.kind, str(stop)
            break
        result.pages += 1

        tail: list[Item] = []  # this page's posts from below the top of the store
        for item in page.items:
            if item.shortcode in seen_codes:
                continue
            if limit is not None and result.seen >= limit:
                done = True
                break
            seen_codes.add(item.shortcode)
            result.seen += 1
            known = store.known(item.shortcode)
            if head_open and not known:
                head.append(item)
            elif head_open:
                # Reached what we already have: everything newer goes in at once.
                head_open = False
                result.new += store.add_listing(head + [item])
                head = []
                done = done or stop_at_known
            elif known or not stop_at_known:
                tail.append(item)  # refresh a known post, or backfill an older one
        if head_open and started_empty and head:
            # Nothing to stay above yet, so the first page can be written now
            # and the rest of the walk is a backfill.
            head_open = False
            result.new += store.add_listing(head)
            head = []
        if tail:
            result.new += store.add_listing(tail, backfill=True)
        log(f"page {result.pages}: {len(page.items)} posts, {result.new} new so far")

        cursor = page.next_max_id
        if not page.items or not page.more_available or not cursor:
            done = True
        if limit is not None and result.seen >= limit:
            done = True

    if head:
        # We never reached the posts we already have.
        if result.stopped:
            result.message += (f" {len(head)} newer posts were seen but not saved, "
                               "so the library stays in order; they will be picked up next time.")
        else:
            result.new += store.add_listing(head)
            if limit is not None and result.seen >= limit:
                result.message = (
                    f"More than {limit} posts were saved since the last sync. The newest "
                    f"{limit} are in; the ones between them and the older library were "
                    "skipped and would be misplaced by a later --all.")
    return result


def bridge_fetcher(raw_dir: Path | str | None = None,
                   log: Callable[[str], None] = lambda s: None) -> Callable[[str | None], Page]:
    """A fetch_page that asks the browser extension. With raw_dir, each raw
    reply is also written there as page-NNN.json (for debugging the mapping)."""
    count = 0

    def fetch(max_id: str | None) -> Page:
        nonlocal count
        try:
            if count == 0 and not bridge.ensure_daemon().get("extension_connected", True):
                log("Waiting for the browser extension to connect (up to 40 s)...")
            reply = bridge.request("saved", {"max_id": max_id} if max_id else {})
        except bridge.BridgeDown as exc:
            raise SourceStop(UNEXPECTED, str(exc)) from exc
        count += 1
        if raw_dir:
            out = Path(raw_dir)
            out.mkdir(parents=True, exist_ok=True)
            (out / f"page-{count:03d}.json").write_text(
                json.dumps(reply, ensure_ascii=False, indent=1), encoding="utf-8")
        return read_reply(reply)

    return fetch


def run_sync(limit: int | None = None, everything: bool = False, *,
             store: Store | None = None, raw_dir: Path | str | None = None,
             log: Callable[[str], None] = lambda s: None) -> SyncResult:
    """Sync from the logged-in browser. Blocking (it sleeps between pages), so
    run it in a worker thread from async code. Never raises for Instagram or
    bridge trouble: look at `result.stopped` and `result.message`."""
    return sync(store or Store(), bridge_fetcher(raw_dir, log),
                limit=limit, everything=everything, log=log)


__all__ = ["SyncResult", "sync", "run_sync", "bridge_fetcher", "NOT_CONNECTED"]
