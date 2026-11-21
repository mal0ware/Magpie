"""Subcommands owned by the sources track. See docs/PLAN.md."""

import sys
from pathlib import Path

from ..store import Store
from . import bridge, daemon, export, feed
from .sync import run_sync


def extension_dir() -> str:
    path = Path(__file__).resolve().parents[3] / "extension"
    return str(path) if (path / "manifest.json").exists() else "the extension/ folder of the Magpie repo"


def load_steps(again: bool = True) -> str:
    """How to load the extension. `again=False` is for `magpie setup`, which
    waits for it instead of asking to be run a second time."""
    last = ("  4. Leave the browser open, wait half a minute, and run this again.\n"
            "`magpie bridge --status` shows whether it has connected."
            if again else
            "  4. Leave the browser open. Setup carries on by itself once the extension\n"
            "     connects (it checks in every 30 seconds). Ctrl+C gives up.")
    return (
        "Magpie's browser extension is not connected.\n"
        "  1. Open Chrome, Edge, Brave, Opera GX or Vivaldi and log in to instagram.com.\n"
        "  2. Go to chrome://extensions (in Opera: opera://extensions) and switch on\n"
        "     Developer mode.\n"
        f"  3. Click \"Load unpacked\" and pick: {extension_dir()}\n"
        + last
    )


_ADVICE = {
    feed.NOT_CONNECTED: load_steps,
    feed.RATE_LIMITED: lambda: "Stopped. Leave it alone for a few hours before syncing again.",
    feed.LOGIN_REQUIRED: lambda: "Stopped. Log in to instagram.com in the browser that has the extension, then sync again.",
    feed.CHECKPOINT: lambda: ("Stopped. Open instagram.com in that browser and clear the prompt "
                              "yourself; do not sync again until the site works normally."),
}


def cmd_sync(args) -> int:
    result = run_sync(limit=args.limit, everything=args.all, raw_dir=args.raw_dir, log=print)
    if result.stopped == feed.NOT_CONNECTED:
        print(load_steps(), file=sys.stderr)
    elif result.stopped:
        print(f"{result.message}\n{_ADVICE.get(result.stopped, lambda: 'Stopped.')()}",
              file=sys.stderr)
    elif result.message:
        print(f"Note: {result.message}", file=sys.stderr)
    print(f"{result.new} new, {result.seen} looked at, {result.pages} page(s). "
          f"Library: {Store().count()} items.")
    _thumbnails()
    return 0 if result.ok else 1


def _thumbnails() -> None:
    """Every sync ends by fetching the thumbnails that are missing, while the
    links the listing gave us still work. Videos are not touched."""
    from ..pipeline.fetch import fetch_thumbs

    c = fetch_thumbs(Store(), progress=print)
    if not c["total"]:
        return
    print(f"Thumbnails: {c['done']} downloaded.")
    missed = c["failed"] + c["skipped"]
    if missed:
        print(f"{missed} thumbnails could not be fetched; their links have probably "
              "expired. `magpie sync --all` gets fresh links for every post.",
              file=sys.stderr)


def cmd_import(args) -> int:
    try:
        new, total = export.import_export(Store(), args.path)
    except (OSError, ValueError) as exc:
        print(f"Could not read {args.path}: {exc}", file=sys.stderr)
        return 1
    if not total:
        print(f"No Instagram post links found in {args.path}.", file=sys.stderr)
        return 1
    print(f"{new} new of {total} posts in the export. Library: {Store().count()} items.")
    return 0


def cmd_add(args) -> int:
    urls = args.urls
    if urls == ["-"]:
        urls = sys.stdin.read().split()
    new, items, bad = export.add_urls(Store(), urls)
    for url in bad:
        print(f"Not an Instagram post URL, skipped: {url}", file=sys.stderr)
    print(f"{new} new of {len(items)} URLs. Library: {Store().count()} items.")
    return 0 if items else 1


def cmd_bridge(args) -> int:
    if args.stop:
        print("Bridge daemon stopped." if bridge.stop_daemon() else "No bridge daemon was running.")
        return 0
    if args.run:
        return daemon.main()
    try:
        st = bridge.ensure_daemon()
    except bridge.BridgeDown as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Bridge daemon: running on ws://{daemon.HOST}:{daemon.PORT} "
          f"(up {st['uptime']:.0f}s, log {bridge.log_path()})")
    if st["extension_connected"]:
        print(f"Extension: connected (version {st['extension_version']})")
        return 0
    print(load_steps(), file=sys.stderr)
    return 1


def register(sub) -> None:
    p = sub.add_parser("sync", help="list Saved posts from the logged-in browser into the library")
    how = p.add_mutually_exclusive_group()
    how.add_argument("--limit", type=int, metavar="N",
                     help="look at the N most recently saved posts and stop")
    how.add_argument("--all", action="store_true",
                     help="walk the whole saved history, slowly")
    p.add_argument("--raw-dir", metavar="DIR",
                   help="also write each raw page reply to DIR (debugging)")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("import", help="import saved_posts.json from an Instagram data export")
    p.add_argument("path", metavar="saved_posts.json")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("add", help="add post URLs by hand, as the most recent saves")
    p.add_argument("urls", nargs="+", metavar="url", help="post URLs, or - to read them from stdin")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("bridge", help="start or check the local bridge the extension connects to")
    what = p.add_mutually_exclusive_group()
    what.add_argument("--status", action="store_true", help="show daemon and extension state (default)")
    what.add_argument("--stop", action="store_true", help="stop the background daemon")
    what.add_argument("--run", action="store_true", help="run the daemon in this terminal")
    p.set_defaults(func=cmd_bridge)
