"""Subcommands owned by the pipeline track. See docs/PLAN.md."""

import sys
import time

from ..store import Store


def _say(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _summary(what: str, c: dict) -> None:
    _say(f"{what}: {c['done']} done, {c['none']} nothing to do, "
         f"{c['failed']} failed (of {c['total']})")


def to_clipboard(text: str) -> None:
    """Put text on the Windows clipboard as Unicode, through the Win32 API.

    (clip.exe would be shorter, but it leaves a BOM character at the front.)
    """
    if sys.platform != "win32":
        raise OSError("the clipboard is only supported on Windows; use --stdout")
    import ctypes
    from ctypes import wintypes as w

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    k32.GlobalAlloc.argtypes, k32.GlobalAlloc.restype = (w.UINT, ctypes.c_size_t), w.HGLOBAL
    k32.GlobalLock.argtypes, k32.GlobalLock.restype = (w.HGLOBAL,), w.LPVOID
    k32.GlobalUnlock.argtypes = (w.HGLOBAL,)
    k32.GlobalFree.argtypes = (w.HGLOBAL,)
    u32.OpenClipboard.argtypes = (w.HWND,)
    u32.SetClipboardData.argtypes, u32.SetClipboardData.restype = (w.UINT, w.HANDLE), w.HANDLE

    data = text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-16-le") + b"\0\0"
    for _ in range(10):  # another program may hold the clipboard for a moment
        if u32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise OSError("could not open the clipboard")
    try:
        u32.EmptyClipboard()
        handle = k32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
        if not handle:
            raise OSError("GlobalAlloc failed")
        ctypes.memmove(k32.GlobalLock(handle), data, len(data))
        k32.GlobalUnlock(handle)
        if not u32.SetClipboardData(13, handle):  # CF_UNICODETEXT; the system owns it now
            k32.GlobalFree(handle)
            raise OSError(f"SetClipboardData failed ({ctypes.get_last_error()})")
    finally:
        u32.CloseClipboard()


def cmd_fetch(args) -> int:
    from . import fetch_pending

    c = fetch_pending(Store(), args.last, retry=args.retry, progress=_say)
    _summary("fetch", c)
    return 0


def cmd_transcribe(args) -> int:
    from . import transcribe_pending

    c = transcribe_pending(Store(), args.last, model=args.model, device=args.device,
                           retry=args.retry, progress=_say)
    _summary("transcribe", c)
    return 0


def cmd_pull(args) -> int:
    from . import pull

    r = pull(Store(), args.last, model=args.model, device=args.device,
             retry=args.retry, progress=_say, shortcodes=args.shortcodes or None)
    _summary("fetch", r["fetch"])
    _summary("transcribe", r["transcribe"])
    return 0


def cmd_copy(args) -> int:
    from .merge import format_many

    items = Store().recent(args.last)
    if not items:
        _say("nothing in the store yet")
        return 1
    text = format_many(items)
    if args.stdout:
        sys.stdout.reconfigure(encoding="utf-8")  # captions carry emoji
        sys.stdout.write(text)
    try:
        to_clipboard(text)
    except OSError as e:
        _say(f"could not reach the clipboard: {e}")
        return 0 if args.stdout else 1
    _say(f"copied {len(items)} items ({len(text):,} characters) to the clipboard")
    return 0


def register(sub) -> None:
    def add(name, func, help_, last_default=None, whisper=False, retry=True):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--last", type=int, default=last_default, metavar="N",
                       help="only the N most recently saved items"
                       + (f" (default {last_default})" if last_default else " (default: all)"))
        if retry:
            p.add_argument("--retry", action="store_true",
                           help="also take items that failed before")
        if whisper:
            p.add_argument("--model", help="whisper model (default small.en, "
                           "or $MAGPIE_WHISPER_MODEL)")
            p.add_argument("--device", choices=["auto", "cuda", "cpu"],
                           help="default auto: CUDA, else CPU (or $MAGPIE_WHISPER_DEVICE)")
        p.set_defaults(func=func)
        return p

    add("fetch", cmd_fetch, "download videos and thumbnails for pending items")
    add("transcribe", cmd_transcribe, "transcribe downloaded videos", whisper=True)
    p = add("pull", cmd_pull, "fetch then transcribe", last_default=30, whisper=True)
    p.add_argument("--all", dest="last", action="store_const", const=None,
                   help="everything in the library that still needs it")
    p.add_argument("shortcodes", nargs="*", metavar="SHORTCODE",
                   help="only these posts, even ones freed or failed before")
    add("copy", cmd_copy, "merged transcripts to the clipboard", last_default=30,
        retry=False).add_argument("--stdout", action="store_true",
                                  help="also print the merged text")
