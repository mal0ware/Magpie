"""The daemon and client against a fake extension on an ephemeral local port."""

import asyncio
import json
from pathlib import Path

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from magpie import cli
from magpie.sources import bridge, daemon, feed, sync as sync_mod
from magpie.sources.cli import load_steps

FIX = Path(__file__).parent / "fixtures"
EXT_ORIGIN = {"Origin": "chrome-extension://abcdefghijklmnop"}


async def start_daemon():
    d = daemon.Daemon()
    port = asyncio.get_running_loop().create_future()
    task = asyncio.create_task(d.serve(port=0, ready=port.set_result))
    return d, await port, task


async def fake_extension(port, answer):
    """Connect like the extension does and answer each request with answer(msg)."""
    async with connect(f"ws://127.0.0.1:{port}/ext", additional_headers=EXT_ORIGIN) as ws:
        await ws.send(json.dumps({"role": "ext", "version": "9.9"}))
        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("type") == "ping":
                continue
            await ws.send(json.dumps({"id": msg["id"], **answer(msg)}))


def test_request_is_relayed_to_the_extension_and_back():
    body = json.loads((FIX / "sources_saved_page_1.json").read_text(encoding="utf-8"))
    got = []

    def answer(msg):
        got.append((msg["action"], msg["params"]))
        return {"ok": True, "data": {"status": 200, "logged_in": True, "body": body}}

    async def scenario():
        d, port, task = await start_daemon()
        ext = asyncio.create_task(fake_extension(port, answer))
        reply = await bridge._request("saved", {"max_id": "abc"}, port, 10)
        status = (await bridge._request("status", {}, port, 5))["data"]
        await bridge._request("stop", {}, port, 5)
        await asyncio.wait_for(task, 5)
        ext.cancel()
        return reply, status

    reply, status = asyncio.run(scenario())
    assert got == [("saved", {"max_id": "abc"})]
    assert [i.shortcode for i in feed.read_reply(reply).items] == [
        "DReelAAA111", "DImageBBB22", "DCarouselC3"]
    assert status["extension_connected"] and status["extension_version"] == "9.9"
    assert status["protocol"] == daemon.PROTOCOL


def test_no_extension_gives_a_not_connected_stop(monkeypatch):
    monkeypatch.setattr(daemon, "EXT_WAIT_FRESH", 0)
    monkeypatch.setattr(daemon, "EXT_WAIT_MIN", 0.05)

    async def scenario():
        d, port, task = await start_daemon()
        status = (await bridge._request("status", {}, port, 5))["data"]
        reply = await bridge._request("saved", {}, port, 5)
        task.cancel()
        return status, reply

    status, reply = asyncio.run(scenario())
    assert status["extension_connected"] is False
    assert reply == {"ok": False, "error": daemon.NOT_CONNECTED}
    with pytest.raises(feed.SourceStop) as exc:
        feed.read_reply(reply)
    assert exc.value.kind == feed.NOT_CONNECTED


def test_websites_cannot_use_the_bridge():
    async def scenario():
        d, port, task = await start_daemon()
        try:
            with pytest.raises(InvalidStatus) as exc:
                async with connect(f"ws://127.0.0.1:{port}/cli",
                                   additional_headers={"Origin": "https://evil.example"}):
                    pass
            assert exc.value.response.status_code == 403

            # An extension origin may not pose as the CLI, nor a local program as the extension.
            async with connect(f"ws://127.0.0.1:{port}/cli", additional_headers=EXT_ORIGIN) as ws:
                await ws.send(json.dumps({"role": "cli", "action": "status"}))
                with pytest.raises(Exception):
                    await asyncio.wait_for(ws.recv(), 2)
            async with connect(f"ws://127.0.0.1:{port}/ext") as ws:
                await ws.send(json.dumps({"role": "ext"}))
                with pytest.raises(Exception):
                    await asyncio.wait_for(ws.recv(), 2)
            assert d.ext is None
        finally:
            task.cancel()

    asyncio.run(scenario())


def test_origin_rule():
    assert daemon.origin_allowed(None)
    assert daemon.origin_allowed("chrome-extension://abc")
    assert not daemon.origin_allowed("https://www.instagram.com")
    assert not daemon.origin_allowed("null")


def test_port_does_not_clash():
    assert daemon.PORT not in (19833, 8765, 8766)
    js = (Path(__file__).parents[1] / "extension" / "background.js").read_text(encoding="utf-8")
    assert f"ws://127.0.0.1:{daemon.PORT}/" in js  # extension and daemon agree


def test_status_is_none_when_nothing_listens():
    assert bridge.status(port=1) is None


def test_sync_cli_explains_how_to_load_the_extension(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MAGPIE_HOME", str(tmp_path))
    monkeypatch.setattr(bridge, "ensure_daemon", lambda: {})
    monkeypatch.setattr(bridge, "request",
                        lambda action, params=None, **kw: {"ok": False, "error": daemon.NOT_CONNECTED})
    assert cli.main(["sync", "--limit", "30"]) == 1
    out = capsys.readouterr()
    assert "extension is not connected" in out.err and "Load unpacked" in out.err
    assert "opera://extensions" in out.err
    assert "0 new" in out.out
    assert load_steps() in out.err


def test_sync_cli_end_to_end_through_a_stubbed_bridge(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MAGPIE_HOME", str(tmp_path))
    monkeypatch.setattr(sync_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(bridge, "ensure_daemon", lambda: {})
    pages = {None: 1, "QVFDcursorPage2": 2}
    asked = []

    def request(action, params=None, **kw):
        asked.append(params.get("max_id"))
        body = json.loads((FIX / f"sources_saved_page_{pages[params.get('max_id')]}.json")
                          .read_text(encoding="utf-8"))
        return {"ok": True, "data": {"status": 200, "logged_in": True, "body": body}}

    monkeypatch.setattr(bridge, "request", request)
    raw = tmp_path / "raw"
    assert cli.main(["sync", "--all", "--raw-dir", str(raw)]) == 0
    assert "4 new" in capsys.readouterr().out
    assert asked == [None, "QVFDcursorPage2"]
    assert sorted(p.name for p in raw.iterdir()) == ["page-001.json", "page-002.json"]

    from magpie.store import Store
    assert [i.shortcode for i in Store().recent()] == [
        "DReelAAA111", "DImageBBB22", "DCarouselC3", "DVideoDDD44"]

    monkeypatch.setattr(bridge, "request", lambda *a, **k: {"ok": True, "data": {"status": 429}})
    assert cli.main(["sync"]) == 1
    assert "rate limiting" in capsys.readouterr().err
