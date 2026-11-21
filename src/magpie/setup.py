"""`magpie setup` and `magpie uninstall`: the way in and the way out.

Setup takes a fresh clone to an open camera roll by calling the same pieces
the other commands use, so it is safe to run again. Uninstall removes
everything Magpie put on the machine and says what is left to do by hand.
"""

import shutil
import sys
import time
import webbrowser
from argparse import Namespace
from pathlib import Path

from . import store
from .pipeline import cli as pipeline_cli
from .sources import bridge
from .sources import cli as sources_cli
from .web import autostart
from .web import cli as web_cli
from .web.app import HOST, PORT

EXT_WAIT = 600  # seconds setup waits for someone to load the extension
EXT_CHECK_IN = 35  # a loaded extension looks for the bridge every 30 s
REPO = Path(__file__).resolve().parents[2]

_FFMPEG = {
    "win32": "winget install Gyan.FFmpeg",
    "darwin": "brew install ffmpeg",
}


def _say(msg: str = "") -> None:
    print(msg, flush=True)


def _step(n: int, msg: str) -> None:
    _say(f"\n[{n}/5] {msg}")


def _wait_for_extension(seconds: float) -> bool:
    """Poll the daemon until the extension has connected, or time runs out."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        st = bridge.status()
        if st and st.get("extension_connected"):
            return True
        time.sleep(2)
    return False


def _connect_extension(wait: float) -> bool:
    """Give an extension that is already loaded time to check in before
    showing anyone how to load it. Ctrl+C gives up."""
    try:
        quiet = min(EXT_CHECK_IN, wait)
        if quiet:
            _say("Waiting for the extension to check in (up to half a minute)...")
        if _wait_for_extension(quiet):
            return True
        _say(sources_cli.load_steps(again=False))
        return _wait_for_extension(wait - quiet)
    except KeyboardInterrupt:
        _say()
        return False


def _old_extension(version: str | None) -> bool:
    try:
        return tuple(int(p) for p in (version or "").split(".")[:2]) < (0, 3)
    except ValueError:
        return False


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _mb(size: int) -> str:
    return f"{size / 2**20:,.0f} MB"


def cmd_setup(args) -> int:
    url = f"http://{HOST}:{args.port}"

    _step(1, "Checking for ffmpeg")
    if not shutil.which("ffmpeg"):
        hint = _FFMPEG.get(sys.platform, "sudo apt install ffmpeg")
        _say(f"ffmpeg is not installed. Install it, then run setup again:\n  {hint}")
        return 1

    _step(2, "Connecting to the browser extension")
    started_daemon = bridge.status() is None
    try:
        st = bridge.ensure_daemon()
    except bridge.BridgeDown as exc:
        _say(str(exc))
        return 1
    if not st.get("extension_connected"):
        if not _connect_extension(args.wait):
            if started_daemon:
                bridge.stop_daemon()  # do not leave it running for nothing
            _say("The extension did not connect. Nothing was changed. Load it and run "
                 "`uv run magpie setup` again.")
            return 1
        st = bridge.status() or st
    _say(f"Extension connected (version {st.get('extension_version')}).")
    if _old_extension(st.get("extension_version")):
        _say("That is an older version. Press the reload arrow on Magpie Bridge in the "
             "extensions page so it closes the Instagram tab it opens.")

    _step(3, "Listing your saved posts")
    if sources_cli.cmd_sync(Namespace(limit=None, all=False, raw_dir=None)):
        _say("Setup stopped here. Sort out the message above and run "
             "`uv run magpie setup` again; it carries on where it left off.")
        return 1

    if args.pull:
        _step(4, f"Downloading and transcribing your newest {args.pull}")
        _say("The first time, this also downloads the speech model (about 500 MB).")
        pipeline_cli.cmd_pull(Namespace(last=args.pull, model=None, device=None,
                                        retry=False, shortcodes=[]))
    else:
        _step(4, "No videos downloaded: click a post in the roll to fetch that one")

    foreground = args.no_login or not autostart.supported()
    if foreground:
        _step(5, "Opening the camera roll")
        if not args.no_login:
            _say("Starting at login is only set up for Windows and macOS.")
    else:
        _step(5, "Starting the camera roll, now and at every login")
        link = autostart.install(args.port)
        if not autostart.running(HOST, args.port):
            autostart.start_background(args.port)
            for _ in range(40):
                if autostart.running(HOST, args.port):
                    break
                time.sleep(0.25)
        _say(f"Login item: {link}")

    home = store.home()
    _say(f"\nDone. Your camera roll is at {url}\n"
         f"  Click a post to download and transcribe it. Pull does that for all of them.\n"
         f"  Data lives in {home} ({_mb(_dir_size(home))} so far).\n"
         "  `uv run magpie uninstall` removes everything Magpie put on this machine.")

    if foreground:
        _say("  The page runs in this terminal. Press Ctrl+C to stop it; "
             "`uv run magpie` opens it again.\n")
        return web_cli._web(Namespace(action=None, port=args.port,
                                      no_browser=False, background=False))
    webbrowser.open(url)
    return 0


# -- uninstall ---------------------------------------------------------------

def model_dirs() -> list[Path]:
    """Speech models in the shared Hugging Face cache (other tools use it too)."""
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
    except ImportError:
        return []
    return sorted(Path(HF_HUB_CACHE).glob("models--Systran--faster-whisper-*"))


def _confirm(question: str) -> bool:
    if not sys.stdin.isatty():
        _say(f"{question}\n  No terminal to ask on, so nothing was deleted. "
             "Pass --yes to delete without asking.")
        return False
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        _say()
        return False


def _safe_to_delete(home: Path) -> bool:
    """$MAGPIE_HOME could point anywhere: only ever delete a Magpie folder."""
    home = home.resolve()
    if home in (Path.home().resolve(), Path(home.anchor)):
        return False
    return (home / "magpie.db").exists() or not any(home.iterdir())


def cmd_uninstall(args) -> int:
    if autostart.supported() and autostart.uninstall():
        _say("Removed the login item.")
    if autostart.stop_background(HOST, args.port):
        _say("Stopped the camera roll.")
    if bridge.stop_daemon():
        _say("Stopped the bridge daemon.")

    home = store.home()
    size = _dir_size(home)
    if args.keep_data:
        _say(f"Kept your library: {home} ({_mb(size)}).")
    elif not _safe_to_delete(home):
        _say(f"{home} does not look like a Magpie data folder, so it was left alone.")
    elif args.yes or _confirm(f"Delete {home} ({_mb(size)})? That is every downloaded "
                              "video, thumbnail and transcript. Instagram is not touched."):
        shutil.rmtree(home, ignore_errors=True)
        _say(f"Deleted {home}.")
    else:
        _say(f"Kept {home}.")

    for model in model_dirs():
        if args.model:
            shutil.rmtree(model, ignore_errors=True)
            _say(f"Deleted the speech model {model.name}.")
        else:
            _say(f"Speech model kept: {model} ({_mb(_dir_size(model))}). Other tools share "
                 "this cache; `uv run magpie uninstall --model` deletes it.")

    _say("\nTwo things only you can remove:\n"
         "  1. Magpie Bridge, on your browser's extensions page.\n"
         f"  2. This folder: {REPO}")
    return 0


def register(sub) -> None:
    p = sub.add_parser("setup", help="set everything up and open the camera roll")
    p.add_argument("--pull", type=int, default=0, metavar="N",
                   help="also download and transcribe your newest N now "
                        "(default: none; thumbnails only)")
    p.add_argument("--no-login", action="store_true",
                   help="do not start at login; run the page in this terminal instead")
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--wait", type=float, default=EXT_WAIT, metavar="SECONDS",
                   help=f"how long to wait for the extension (default {EXT_WAIT})")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("uninstall", help="remove everything Magpie put on this machine")
    p.add_argument("--yes", action="store_true", help="delete the library without asking")
    p.add_argument("--keep-data", action="store_true",
                   help="keep the library (videos, transcripts)")
    p.add_argument("--model", action="store_true",
                   help="also delete the speech model from the shared Hugging Face cache")
    p.add_argument("--port", type=int, default=PORT)
    p.set_defaults(func=cmd_uninstall)
