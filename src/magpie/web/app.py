"""Local camera-roll server. Loopback only; see docs/PLAN.md, Track C."""

import re
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .. import store
from ..models import DONE, Item
from . import seams

STATIC = Path(__file__).parent / "static"
HOST, PORT = "127.0.0.1", 8766
_SHORTCODE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_NO_CACHE = {"Cache-Control": "no-cache"}


@contextmanager
def _store():
    s = store.Store()
    try:
        yield s
    finally:
        s.db.close()


def _lookup(s: store.Store, shortcode: str) -> Item | None:
    """Only shortcodes that are in the store ever reach the filesystem."""
    return s.get(shortcode) if _SHORTCODE.match(shortcode) else None


def _public(item: Item) -> dict:
    d = asdict(item)
    del d["video_url"], d["thumb_url"]  # expiring CDN links; the page uses /media
    d["has_video"] = store.video_path(item.shortcode).is_file()
    d["has_thumb"] = store.thumb_path(item.shortcode).is_file()
    return d


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


class _FreshStatic(StaticFiles):
    """The page's own script and stylesheet, always revalidated. Without this
    a browser keeps running the app.js it cached before an update, and the
    page behaves like the old version. (An unchanged file is still a 304.)"""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


async def _json_body(request: Request):
    """POSTs must be JSON, so another site's form cannot trigger them."""
    if not request.headers.get("content-type", "").startswith("application/json"):
        return None
    try:
        return await request.json()
    except ValueError:
        return None


async def index(request: Request):
    # The script and stylesheet addresses carry the file's modification time,
    # so a browser can never pair this page with a copy it cached earlier.
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for name in ("app.js", "app.css"):
        stamp = int((STATIC / name).stat().st_mtime)
        html = html.replace(f"/static/{name}", f"/static/{name}?v={stamp}")
    return HTMLResponse(html, headers=_NO_CACHE)


async def items(request: Request):
    try:
        limit = int(request.query_params.get("limit", 60))
        offset = int(request.query_params.get("offset", 0))
    except ValueError:
        return _error(400, "limit and offset must be integers")
    limit, offset = max(1, min(limit, 500)), max(0, offset)
    with _store() as s:
        rows = s.recent(limit=limit, offset=offset)
        # How many videos the Pull button would download, so the page can say
        # so before it starts.
        to_pull = len([i for i in s.with_status("media_status", "pending") if not i.hidden])
        return JSONResponse({"items": [_public(i) for i in rows], "total": s.count(),
                             "to_pull": to_pull, "limit": limit, "offset": offset})


async def item(request: Request):
    with _store() as s:
        it = _lookup(s, request.path_params["shortcode"])
    if not it:
        return _error(404, "no such item")
    return JSONResponse({**_public(it), "transcript": seams.read_transcript(it.shortcode)})


async def media(request: Request):
    name = request.path_params["name"]
    with _store() as s:
        it = _lookup(s, request.path_params["shortcode"])
    locate = {"video.mp4": store.video_path, "thumb.jpg": store.thumb_path}.get(name)
    path = locate(it.shortcode) if it and locate else None
    if not path or not path.is_file():
        return _error(404, "not downloaded")
    # FileResponse answers Range requests itself, which is what makes seeking work.
    return FileResponse(path, headers=_NO_CACHE,
                        media_type="video/mp4" if name == "video.mp4" else "image/jpeg")


async def merged(request: Request):
    body = await _json_body(request)
    if isinstance(body, dict) and "shortcodes" in body:
        body = body["shortcodes"]
    with _store() as s:
        if isinstance(body, dict) and isinstance(body.get("last"), int) and body["last"] > 0:
            chosen, missing = s.recent(limit=body["last"]), []
        elif isinstance(body, list) and all(isinstance(c, str) for c in body):
            found = {c: _lookup(s, c) for c in dict.fromkeys(body)}
            missing = [c for c, it in found.items() if not it]
            # Camera-roll order, whatever order the tiles were clicked in.
            chosen = sorted((it for it in found.values() if it),
                            key=lambda it: it.saved_seq, reverse=True)
        else:
            return _error(400, 'send a JSON list of shortcodes or {"last": N}')
    return JSONResponse({
        "text": seams.format_many(chosen),
        "count": len(chosen),
        "shortcodes": [it.shortcode for it in chosen],
        "missing": missing,
        "without_transcript": sum(it.transcript_status != DONE for it in chosen),
        "source": seams.merge_source(),
    })


async def actions(request: Request):
    return JSONResponse({"available": seams.available(),
                         "job": request.app.state.jobs.snapshot()})


async def run_action(request: Request):
    body = await _json_body(request)
    if not isinstance(body, dict):
        return _error(415, "send a JSON object")
    ok, why = request.app.state.jobs.start(request.path_params["name"], body)
    if not ok:
        return JSONResponse({"error": why, "available": seams.available(),
                             "job": request.app.state.jobs.snapshot()}, status_code=409)
    return JSONResponse({"job": request.app.state.jobs.snapshot()}, status_code=202)


def create_app() -> Starlette:
    app = Starlette(
        routes=[
            Route("/", index),
            Route("/api/items", items),
            Route("/api/items/{shortcode}", item),
            Route("/api/merged", merged, methods=["POST"]),
            Route("/api/actions", actions),
            Route("/api/actions/{name}", run_action, methods=["POST"]),
            Route("/media/{shortcode}/{name:str}", media),
            Mount("/static", _FreshStatic(directory=STATIC), name="static"),
        ],
        # Refuse requests addressed to any other name (DNS rebinding).
        middleware=[Middleware(TrustedHostMiddleware,
                               allowed_hosts=["127.0.0.1", "localhost", "testserver"])],
    )
    app.state.jobs = seams.Jobs()
    return app
