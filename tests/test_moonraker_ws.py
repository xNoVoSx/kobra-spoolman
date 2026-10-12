"""Moonraker-WebSocket (moonraker.py): on_status darf selbst Moonraker aufrufen, ohne den Leser zu blockieren.

Bis 3.11.0 lief on_status im Leser: ein G-Code daraus (Auto-PA, Trockner, Slots) wartete 15 s auf eine Antwort,
die niemand las - die Bridge war so lange taub (Weboberflaeche stand, Verwerfen kam nicht an)."""

from __future__ import annotations

import asyncio
import json
import time

import aiohttp
from aiohttp import web

from acebridge.moonraker import Moonraker


async def fake_moonraker(scripts):
    """Kleiner Moonraker: identify/info/subscribe/gcode, schickt nach dem Abo zwei Status-Aenderungen."""
    async def ws_handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            req = json.loads(msg.data)
            method, rid = req["method"], req["id"]
            if method == "server.info":
                result = {"klippy_state": "ready", "components": []}
            elif method == "printer.objects.subscribe":
                result = {"status": {"print_stats": {"state": "standby"}}}
            elif method == "printer.gcode.script":
                scripts.append(req["params"]["script"])
                result = "ok"
            elif method == "server.gcode_store":
                result = {"gcode_store": []}
            else:
                result = {}
            await ws.send_str(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}))
            if method == "printer.objects.subscribe":
                for state in ("printing", "complete"):
                    await ws.send_str(json.dumps({"jsonrpc": "2.0", "method": "notify_status_update",
                                                  "params": [{"print_stats": {"state": state}}, 1.0]}))
        return ws

    app = web.Application()
    app.router.add_get("/websocket", ws_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}"


def test_gcode_from_on_status_does_not_deadlock(cfg):
    async def main():
        scripts, seen = [], []
        runner, url = await fake_moonraker(scripts)
        cfg.moonraker_url, cfg.dry_run = url, False
        async with aiohttp.ClientSession() as session:
            async def on_status(delta, full):
                state = moon.status["print_stats"]["state"]
                seen.append((state, full))
                assert delta["print_stats"]["state"] == state      # Cache passt zum Delta
                if not full:
                    await moon.gcode(f"M117 {state}", timeout=3)    # wartet auf die Antwort - die liest der Leser

            moon = Moonraker(cfg, session, on_status)
            task = asyncio.create_task(moon.run())
            t0 = time.monotonic()
            while len(scripts) < 2 and time.monotonic() - t0 < 5:
                await asyncio.sleep(0.02)
            elapsed = time.monotonic() - t0
            task.cancel()
        await runner.cleanup()
        return scripts, seen, elapsed

    scripts, seen, elapsed = asyncio.run(main())
    assert scripts == ["M117 printing", "M117 complete"]
    assert seen == [("standby", True), ("printing", False), ("complete", False)]   # jeder Wechsel, in Reihenfolge
    assert elapsed < 2
