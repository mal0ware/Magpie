"""Subcommands owned by the web track. See docs/PLAN.md."""

import threading
import webbrowser


def _web(args) -> int:
    import uvicorn

    from .app import HOST, create_app

    url = f"http://{HOST}:{args.port}"
    print(f"magpie web: {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(0.8, webbrowser.open, [url]).start()
    uvicorn.run(create_app(), host=HOST, port=args.port, log_level="warning")
    return 0


def register(sub) -> None:
    from .app import PORT

    p = sub.add_parser("web", help="open the camera roll at http://127.0.0.1:8766")
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    p.set_defaults(func=_web)
