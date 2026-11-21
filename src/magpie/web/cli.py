"""Subcommands owned by the web track. See docs/PLAN.md."""

import sys
import threading
import webbrowser


def _web(args) -> int:
    from . import autostart
    from .app import HOST, create_app

    url = f"http://{HOST}:{args.port}"

    if args.action in ("install", "uninstall") and not autostart.supported():
        print("Starting at login is only set up for Windows and macOS. Here, run "
              "`magpie web` and leave it open, or add it to your login items.",
              file=sys.stderr)
        return 1
    if args.action == "install":
        link = autostart.install(args.port)
        if not autostart.running(HOST, args.port):
            autostart.start_background(args.port)
        print(f"Magpie now starts at login and is running. Bookmark {url}")
        print(f"(login item: {link}; log: {autostart.log_path()}; "
              "`magpie web uninstall` removes it)")
        return 0
    if args.action == "uninstall":
        had = autostart.uninstall()
        print("Removed the login item." if had else "There was no login item.")
        if autostart.stop_background(HOST, args.port):
            print("Stopped the camera roll that was running in the background.")
        return 0

    if autostart.running(HOST, args.port):
        print(f"magpie web is already running: {url}")
        if not (args.no_browser or args.background):
            webbrowser.open(url)
        return 0

    import uvicorn

    if args.background:  # no console under pythonw: send output to a log file
        sys.stdout = sys.stderr = open(autostart.log_path(), "a", encoding="utf-8", buffering=1)
    print(f"magpie web: {url}  (Ctrl+C to stop)")
    if not (args.no_browser or args.background):
        threading.Timer(0.8, webbrowser.open, [url]).start()
    autostart.write_pid()  # so `magpie web uninstall` / `magpie uninstall` can stop it
    try:
        uvicorn.run(create_app(), host=HOST, port=args.port, log_level="warning")
    finally:
        autostart.clear_pid()
    return 0


def register(sub) -> None:
    from .app import PORT

    p = sub.add_parser("web", help="open the camera roll at http://127.0.0.1:8766")
    p.add_argument("action", nargs="?", choices=["install", "uninstall"],
                   help="install: run in the background from login on, so the address "
                        "can be bookmarked (Windows, macOS). uninstall: undo that")
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    p.add_argument("--background", action="store_true",
                   help="no browser tab, output to ~/.magpie/web.log (what install uses)")
    p.set_defaults(func=_web)
