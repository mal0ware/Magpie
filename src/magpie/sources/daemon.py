"""Magpie bridge daemon: a relay between `magpie sync` and the browser extension.

A WebSocket server on 127.0.0.1. The extension and the CLI both connect as
clients and say who they are in their first message:

    {"role": "ext", "version": "0.1.0"}                   the browser extension
    {"role": "cli", "action": "saved", "params": {...}}   a one-shot request

A CLI request is forwarded to the extension and the reply is sent back. Two
actions are answered by the daemon itself: `status` and `stop`.

Any web page can open a WebSocket to localhost, so connections are checked by
Origin: the extension must come from `chrome-extension://`, the CLI sends no
Origin at all, and anything else (a website) is refused.

Run it by hand with `python -m magpie.sources.daemon`; normally
`magpie.sources.bridge` starts it on demand.
"""

from __future__ import annotations

import asyncio
import http
import json
import sys
import time
import uuid

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

HOST = "127.0.0.1"
PORT = 19877  # not ig-bridge (19833), ytmerge-web (8765) or magpie web (8766)
PROTOCOL = 1
PING_INTERVAL = 20  # seconds; keeps the MV3 service worker awake
# The extension's reconnect alarm fires every 30 s, so a daemon that has just
# started gives it this long to show up. One that has been up longer than that
# without an extension answers almost at once.
EXT_WAIT_FRESH = 40
EXT_WAIT_MIN = 3
REQUEST_TIMEOUT = 60  # seconds to wait for the extension's reply
MAX_MESSAGE = 64 * 1024 * 1024  # a saved-feed page is large JSON

NOT_CONNECTED = "extension not connected"


def log(*args: object) -> None:
    print(time.strftime("%H:%M:%S"), "[magpie bridge]", *args, file=sys.stderr, flush=True)


def origin_allowed(origin: str | None, path: str = "") -> bool:
    """No Origin (a local program) or a browser extension; never a website."""
    if origin is None:
        return True
    return origin.startswith(("chrome-extension://", "moz-extension://"))


class Daemon:
    def __init__(self) -> None:
        self.ext = None
        self.ext_version: str | None = None
        self.ext_ready = asyncio.Event()
        self.pending: dict[str, asyncio.Future] = {}
        self.busy = asyncio.Lock()  # one request to Instagram at a time
        self.started = time.monotonic()
        self.stopping = asyncio.Event()

    # -- connection handling ------------------------------------------------

    def process_request(self, connection, request):
        if not origin_allowed(request.headers.get("Origin")):
            return connection.respond(http.HTTPStatus.FORBIDDEN, "origin not allowed\n")
        return None

    async def router(self, ws) -> None:
        try:
            first = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        except (asyncio.TimeoutError, ConnectionClosed, ValueError):
            return
        if not isinstance(first, dict):
            return
        origin = ws.request.headers.get("Origin")
        role = first.get("role")
        if role == "ext" and origin:  # only a browser extension has an Origin
            await self.handle_ext(ws, first)
        elif role == "cli" and origin is None:
            await self.handle_cli(ws, first)

    async def handle_ext(self, ws, first: dict) -> None:
        self.ext = ws
        self.ext_version = first.get("version")
        self.ext_ready.set()
        log("extension connected", self.ext_version or "")
        pinger = asyncio.ensure_future(self._ping_loop(ws))
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(msg, dict) or msg.get("type") == "pong":
                    continue
                fut = self.pending.pop(msg.get("id"), None)
                if fut is not None and not fut.done():
                    fut.set_result(msg)
        finally:
            pinger.cancel()
            if self.ext is ws:
                self.ext = None
                self.ext_ready.clear()
                for fut in self.pending.values():
                    if not fut.done():
                        fut.set_exception(ConnectionError("extension connection dropped"))
                self.pending.clear()
            log("extension disconnected")

    async def _ping_loop(self, ws) -> None:
        try:
            while True:
                await asyncio.sleep(PING_INTERVAL)
                await ws.send(json.dumps({"type": "ping"}))
        except (asyncio.CancelledError, ConnectionClosed):
            return

    async def handle_cli(self, ws, first: dict) -> None:
        reply = await self.dispatch(first.get("action"), first.get("params") or {})
        try:
            await ws.send(json.dumps(reply))
        except ConnectionClosed:
            pass

    # -- actions -------------------------------------------------------------

    def status(self) -> dict:
        return {
            "protocol": PROTOCOL,
            "extension_connected": self.ext is not None,
            "extension_version": self.ext_version if self.ext is not None else None,
            "uptime": round(time.monotonic() - self.started, 1),
        }

    async def dispatch(self, action, params: dict) -> dict:
        if action == "status":
            return {"ok": True, "data": self.status()}
        if action == "stop":
            self.stopping.set()
            return {"ok": True, "data": {"stopping": True}}
        if not action:
            return {"ok": False, "error": "missing action"}

        uptime = time.monotonic() - self.started
        try:
            await asyncio.wait_for(
                self.ext_ready.wait(), timeout=max(EXT_WAIT_MIN, EXT_WAIT_FRESH - uptime))
        except asyncio.TimeoutError:
            return {"ok": False, "error": NOT_CONNECTED}

        async with self.busy:
            ext = self.ext
            if ext is None:
                return {"ok": False, "error": NOT_CONNECTED}
            mid = uuid.uuid4().hex
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            self.pending[mid] = fut
            try:
                await ext.send(json.dumps({"id": mid, "action": action, "params": params}))
                return await asyncio.wait_for(fut, timeout=REQUEST_TIMEOUT)
            except asyncio.TimeoutError:
                return {"ok": False, "error": "extension timed out"}
            except (ConnectionClosed, ConnectionError):
                return {"ok": False, "error": "extension connection dropped"}
            finally:
                self.pending.pop(mid, None)

    # -- lifecycle -----------------------------------------------------------

    async def serve(self, host: str = HOST, port: int = PORT, ready=None) -> None:
        """Serve until a `stop` action arrives. `ready(port)` is called once bound."""
        async with serve(self.router, host, port, process_request=self.process_request,
                         max_size=MAX_MESSAGE, ping_interval=None) as server:
            bound = server.sockets[0].getsockname()[1]
            log(f"listening on ws://{host}:{bound}")
            if ready:
                ready(bound)
            await self.stopping.wait()
            await asyncio.sleep(0.1)  # let the reply to `stop` go out
        log("stopped")


def main() -> int:
    try:
        asyncio.run(Daemon().serve())
    except OSError as exc:
        log(f"could not bind {HOST}:{PORT}: {exc}")
        return 1
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
