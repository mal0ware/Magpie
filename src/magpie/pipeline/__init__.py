"""Track B: download, transcribe, merge. See docs/PLAN.md.

The functions the CLI runs, for the web track to call as well:

    fetch_pending(store, last=None, progress=print)
    transcribe_pending(store, last=None, model=None, device=None, progress=print)
    pull(store, last=30, progress=print)          # fetch then transcribe
    merge.format_item(item), merge.format_many(items)

`progress` is called with one line of text per item. Each returns counts
{"done", "none", "failed", "total"}; `pull` returns {"fetch": ..., "transcribe": ...}.
"""

from .fetch import Progress, fetch_pending
from .transcribe import transcribe_pending

__all__ = ["fetch_pending", "transcribe_pending", "pull"]


def pull(store, last: int | None = 30, *, model: str | None = None,
         device: str | None = None, retry: bool = False, delay: float = 1.5,
         progress: Progress | None = None) -> dict:
    """Fetch media for the last N saved items, then transcribe them."""
    return {
        "fetch": fetch_pending(store, last, retry=retry, delay=delay, progress=progress),
        "transcribe": transcribe_pending(store, last, model=model, device=device,
                                         retry=retry, progress=progress),
    }
