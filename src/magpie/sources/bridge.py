"""Client side of the bridge: start the daemon if needed and ask it things.

`request()` sends exactly one message and returns the reply. Nothing here
retries a request to Instagram.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from websockets.asyncio.client import connect

from .. import store
from . import daemon

# The daemon may wait for the extension, then for Instagram.
REPLY_TIMEOUT = daemon.EXT_WAIT_FRESH + daemon.REQUEST_TIMEOUT + 10


class BridgeDown(Exception):
    """The local daemon could not be reached or started."""


def _url(port: int) -> str:
    return f"ws://{daemon.HOST}:{port}/cli"


async def _request(action: str, params: dict, port: int, timeout: float) -> dict:
    async with connect(_url(port), open_timeout=5, max_size=daemon.MAX_MESSAGE,
                       ping_interval=None) as ws:
        await ws.send(json.dumps({"role": "cli", "action": action, "params": params}))
        return json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))


def request(action: str, params: dict | None = None, *, port: int = daemon.PORT,
            timeout: float = REPLY_TIMEOUT) -> dict:
    """One request to the daemon. Returns its reply: {"ok": bool, "data"|"error": ...}.

    Blocking; call it from a worker thread if you are inside an event loop.
    """
    try:
        return asyncio.run(_request(action, params or {}, port, timeout))
    except (OSError, asyncio.TimeoutError, ValueError) as exc:
        raise BridgeDown(f"could not reach the Magpie bridge daemon: {exc}") from exc
    except Exception as exc:  # websockets handshake / close errors
        raise BridgeDown(f"could not reach the Magpie bridge daemon: {exc}") from exc


def status(port: int = daemon.PORT) -> dict | None:
    """The daemon's status dict, or None if no daemon is listening."""
    try:
        reply = request("status", port=port, timeout=3)
    except BridgeDown:
        return None
    return reply.get("data") if reply.get("ok") else None


def release(port: int = daemon.PORT) -> bool:
    """Tell the extension we are done, so it closes an Instagram tab it opened
    itself. Best effort: never starts a daemon, never raises. An older
    extension answers "unknown action", which is fine."""
    try:
        st = status(port)
        if not st or not st.get("extension_connected"):
            return False
        return bool(request("release", port=port, timeout=10).get("ok"))
    except Exception:
        return False


def log_path() -> Path:
    return store.home() / "bridge.log"


def start_daemon() -> None:
    """Start the daemon detached, so it outlives this command, and wait for it."""
    flags = 0
    if os.name == "nt":
        # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP. Not DETACHED_PROCESS: with no
        # console at all, the interpreter a virtualenv launcher hands off to
        # opens a visible, empty terminal window.
        flags = 0x08000000 | 0x00000200
    with open(log_path(), "ab") as logf:
        subprocess.Popen(
            [sys.executable, "-m", "magpie.sources.daemon"],
            stdout=logf, stderr=logf, stdin=subprocess.DEVNULL,
            creationflags=flags, close_fds=True,
        )
    for _ in range(40):
        if status() is not None:
            return
        time.sleep(0.25)
    raise BridgeDown(f"the bridge daemon did not start; see {log_path()}")


def ensure_daemon() -> dict:
    """Make sure a daemon is running and return its status."""
    st = status()
    if st is None:
        start_daemon()
        st = status()
    if st is None:
        raise BridgeDown(f"the bridge daemon did not start; see {log_path()}")
    if st.get("protocol") != daemon.PROTOCOL:
        raise BridgeDown(
            "an older Magpie bridge daemon is running; stop it with `magpie bridge --stop`")
    return st


def stop_daemon() -> bool:
    """Ask a running daemon to exit. False if none was running."""
    try:
        return bool(request("stop", timeout=3).get("ok"))
    except BridgeDown:
        return False
