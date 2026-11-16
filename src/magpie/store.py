"""SQLite index plus the on-disk library layout. The shared contract between
the source, pipeline and web tracks. See docs/PLAN.md before changing it."""

import os
import sqlite3
import time
from dataclasses import asdict, fields
from pathlib import Path

from .models import Item

_COLS = [f.name for f in fields(Item)]
# Fields a re-listing may refresh on an item we already have.
_REFRESH = ("video_url", "thumb_url", "caption", "author", "duration", "collection")


def home() -> Path:
    """Data root: $MAGPIE_HOME or ~/.magpie."""
    p = Path(os.environ.get("MAGPIE_HOME") or Path.home() / ".magpie")
    p.mkdir(parents=True, exist_ok=True)
    return p


def item_dir(shortcode: str) -> Path:
    """library/<shortcode>/ holding video.mp4, thumb.jpg, transcript.txt, transcript.json."""
    p = home() / "library" / shortcode
    p.mkdir(parents=True, exist_ok=True)
    return p


def video_path(shortcode: str) -> Path:
    return item_dir(shortcode) / "video.mp4"


def thumb_path(shortcode: str) -> Path:
    return item_dir(shortcode) / "thumb.jpg"


def transcript_path(shortcode: str) -> Path:
    """Plain text, one `[m:ss] text` line per segment."""
    return item_dir(shortcode) / "transcript.txt"


class Store:
    def __init__(self, path: Path | str | None = None):
        self.db = sqlite3.connect(str(path or home() / "magpie.db"), timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        cols = ", ".join(
            f"{c} PRIMARY KEY" if c == "shortcode" else c for c in _COLS
        )
        self.db.execute(f"CREATE TABLE IF NOT EXISTS items ({cols})")
        have = {r[1] for r in self.db.execute("PRAGMA table_info(items)")}
        if "hidden" not in have:  # libraries made before items could be removed
            self.db.execute("ALTER TABLE items ADD COLUMN hidden DEFAULT 0")
        self.db.commit()

    # -- writes ------------------------------------------------------------

    def add_listing(self, items: list[Item], backfill: bool = False) -> int:
        """Record a batch of saved posts, given newest-saved first.

        Normal sync (backfill=False): pass everything newer than what we have
        in ONE call; new items are placed above all existing ones.
        Backfill (backfill=True): pass older pages, one call per page in the
        order Instagram returns them; new items are placed below all existing
        ones. Items already known only get their expiring fields refreshed.
        Returns the number of new items.
        """
        new = [i for i in items if not self.known(i.shortcode)]
        for i in items:
            if i not in new:
                sets = ", ".join(f"{c} = COALESCE(?, {c})" for c in _REFRESH)
                vals = [getattr(i, c) or None for c in _REFRESH]
                self.db.execute(
                    f"UPDATE items SET {sets} WHERE shortcode = ?", (*vals, i.shortcode)
                )
        lo, hi = self.db.execute(
            "SELECT COALESCE(MIN(saved_seq), 0), COALESCE(MAX(saved_seq), 0) FROM items"
        ).fetchone()
        now = time.time()
        for n, i in enumerate(new):
            i.saved_seq = lo - 1 - n if backfill else hi + len(new) - n
            i.first_seen = now
            row = asdict(i)
            self.db.execute(
                f"INSERT INTO items ({', '.join(_COLS)}) VALUES ({', '.join('?' * len(_COLS))})",
                [row[c] for c in _COLS],
            )
        self.db.commit()
        return len(new)

    def set_media(self, shortcode: str, status: str, error: str | None = None,
                  duration: float | None = None) -> None:
        self.db.execute(
            "UPDATE items SET media_status = ?, error = ?, duration = COALESCE(?, duration) "
            "WHERE shortcode = ?", (status, error, duration, shortcode))
        self.db.commit()

    def set_transcript(self, shortcode: str, status: str, error: str | None = None) -> None:
        self.db.execute(
            "UPDATE items SET transcript_status = ?, error = ? WHERE shortcode = ?",
            (status, error, shortcode))
        self.db.commit()

    def hide(self, shortcode: str) -> None:
        """Take an item out of the roll. The row stays, so `known()` is still
        true and a later sync will not list it again."""
        self.db.execute("UPDATE items SET hidden = 1 WHERE shortcode = ?", (shortcode,))
        self.db.commit()

    # -- reads -------------------------------------------------------------

    def known(self, shortcode: str) -> bool:
        return self.db.execute(
            "SELECT 1 FROM items WHERE shortcode = ?", (shortcode,)).fetchone() is not None

    def get(self, shortcode: str) -> Item | None:
        r = self.db.execute("SELECT * FROM items WHERE shortcode = ?", (shortcode,)).fetchone()
        return Item(**dict(r)) if r else None

    def recent(self, limit: int = 30, offset: int = 0,
               collection: str | None = None) -> list[Item]:
        """Newest-saved first. This is the camera-roll order and what 'last 30' means."""
        where, args = ("AND collection = ?", [collection]) if collection else ("", [])
        rows = self.db.execute(
            f"SELECT * FROM items WHERE hidden = 0 {where} ORDER BY saved_seq DESC LIMIT ? OFFSET ?",
            (*args, limit, offset))
        return [Item(**dict(r)) for r in rows]

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM items WHERE hidden = 0").fetchone()[0]

    def with_status(self, column: str, status: str, limit: int = -1) -> list[Item]:
        """Items whose media_status or transcript_status equals status, newest-saved first."""
        if column not in ("media_status", "transcript_status"):
            raise ValueError(column)
        rows = self.db.execute(
            f"SELECT * FROM items WHERE {column} = ? AND hidden = 0 ORDER BY saved_seq DESC LIMIT ?",
            (status, limit))
        return [Item(**dict(r)) for r in rows]
