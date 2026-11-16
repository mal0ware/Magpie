"""`magpie free`, `magpie remove`, `magpie unsave`."""

from ..store import Store
from . import UnsaveStopped, free, older_than, remove, unsave


def _say(msg: str) -> None:
    print(msg, flush=True)


def cmd_free(args) -> int:
    s = Store()
    if args.keep is None and not args.shortcodes:
        _say("name some posts, or use --keep N to free everything older than the newest N")
        return 1
    codes = list(args.shortcodes) + (older_than(s, args.keep) if args.keep is not None else [])
    count, size = free(s, codes, log=_say)
    _say(f"freed {count} videos, {size / 2**20:.0f} MB. Thumbnails, captions and transcripts kept.")
    return 0


def cmd_remove(args) -> int:
    n = remove(Store(), args.shortcodes)
    _say(f"removed {n} posts from the roll. They are still saved on Instagram.")
    return 0


def cmd_unsave(args) -> int:
    try:
        n = unsave(Store(), args.shortcodes, log=_say)
    except UnsaveStopped as stop:
        _say(str(stop))
        return 1
    _say(f"unsaved {n} posts on Instagram and removed them from the roll.")
    return 0


def register(sub) -> None:
    p = sub.add_parser("free", help="delete video files to save space; transcripts stay")
    p.add_argument("shortcodes", nargs="*", metavar="SHORTCODE")
    p.add_argument("--keep", type=int, metavar="N",
                   help="free every video older than the N most recently saved")
    p.set_defaults(func=cmd_free)

    p = sub.add_parser("remove", help="take posts out of the roll and delete their files")
    p.add_argument("shortcodes", nargs="+", metavar="SHORTCODE")
    p.set_defaults(func=cmd_remove)

    p = sub.add_parser("unsave", help="unsave posts on Instagram, then remove them from the roll")
    p.add_argument("shortcodes", nargs="+", metavar="SHORTCODE")
    p.set_defaults(func=cmd_unsave)
