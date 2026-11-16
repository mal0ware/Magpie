"""The only place the web track reaches into the other tracks.

Two seams, both written so this branch runs on its own and picks up the real
thing with no edits once tracks A and B are merged:

* merged text: `magpie.pipeline.merge.format_many` if it imports, otherwise a
  local copy of the banner from docs/PLAN.md.
* Sync / Pull: run the `magpie sync` / `magpie pull` subcommands themselves in
  a child process, so the buttons do exactly what the CLI does and the
  command's own output is the progress. A button is "available" when its
  track has registered that subcommand.
"""

import argparse
import importlib
import os
import subprocess
import sys
import threading
import time

from .. import store
from ..models import DONE, NONE, Item

# -- merged text -------------------------------------------------------------

_RULE = "=" * 80


def merge_source() -> str:
    """'pipeline' when track B's formatter is importable, else 'fallback'."""
    try:
        importlib.import_module("magpie.pipeline.merge").format_many
    except (ImportError, AttributeError):
        return "fallback"
    return "pipeline"


def format_many(items: list[Item]) -> str:
    if merge_source() == "pipeline":
        return importlib.import_module("magpie.pipeline.merge").format_many(items)
    return "\n\n".join(_format_item(i) for i in items)


def read_transcript(shortcode: str) -> str | None:
    """transcript.txt for an item that is in the store, or None."""
    p = store.transcript_path(shortcode)
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8", errors="replace").strip()


def _format_item(item: Item) -> str:
    body = read_transcript(item.shortcode) if item.transcript_status == DONE else None
    if not body:
        body = "(no speech)" if item.transcript_status in (DONE, NONE) else "(not transcribed yet)"
    return "\n".join([
        _RULE,
        f"CREATOR: @{item.author}" if item.author else "CREATOR: (unknown)",
        f"URL:     {item.url}",
        f"CAPTION: {item.caption}",
        _RULE,
        "",
        body,
    ])


# -- Sync / Pull -------------------------------------------------------------

# button name -> (track that owns the subcommand, argv after `magpie`)
ACTIONS = {
    "sync": ("sources", lambda opts: ["sync"]),
    # No "last" means the whole library: the roll is the main way in, so its
    # Pull button catches up on everything that still needs downloading.
    "pull": ("pipeline", lambda opts: ["pull", "--last", str(int(opts["last"]))]
             if opts.get("last") else ["pull", "--all"]),
}


def available() -> dict[str, bool]:
    """Which buttons can run: has the owning track registered the subcommand yet?"""
    sub = argparse.ArgumentParser().add_subparsers()
    for track in {t for t, _ in ACTIONS.values()}:
        try:
            importlib.import_module(f"magpie.{track}.cli").register(sub)
        except Exception:  # a half-merged track must not take the page down
            pass
    return {name: name in sub.choices for name in ACTIONS}


def command(name: str, opts: dict) -> list[str]:
    return [sys.executable, "-m", "magpie.cli", *ACTIONS[name][1](opts)]


class Jobs:
    """At most one Sync or Pull at a time; keeps the tail of its output."""

    def __init__(self):
        self._lock = threading.Lock()
        self._job: dict | None = None

    def snapshot(self) -> dict | None:
        with self._lock:
            return dict(self._job, lines=self._job["lines"][-12:]) if self._job else None

    def start(self, name: str, opts: dict) -> tuple[bool, str]:
        """Returns (started, reason-if-not)."""
        if name not in ACTIONS:
            return False, "unknown action"
        if not available()[name]:
            return False, f"{name} is not available yet"
        with self._lock:
            if self._job and self._job["state"] == "running":
                return False, f"{self._job['name']} is still running"
            job = {"name": name, "state": "running", "lines": [], "started": time.time(),
                   "returncode": None}
            self._job = job
        threading.Thread(target=self._run, args=(job, command(name, opts)), daemon=True).start()
        return True, ""

    def _run(self, job: dict, argv: list[str]) -> None:
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        try:
            proc = subprocess.Popen(
                argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                text=True, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for line in proc.stdout:
                # yt-dlp style progress rewrites one line with \r; keep the latest.
                line = line.rstrip().rsplit("\r", 1)[-1].strip()
                if line:
                    with self._lock:
                        job["lines"].append(line)
                        del job["lines"][:-200]
            code = proc.wait()
        except OSError as e:
            code = -1
            with self._lock:
                job["lines"].append(str(e))
        with self._lock:
            job["returncode"] = code
            job["state"] = "done" if code == 0 else "failed"
