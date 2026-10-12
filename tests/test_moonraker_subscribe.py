"""Subscription per platform: only objects the printer has. On Rinkhals an absent object can make GoKlipper panic,
so the bridge asks objects/list first and adds Rinkhals' ACE objects (mmu, filament_hub) itself."""

from __future__ import annotations

import asyncio
import json

import aiohttp
from aiohttp import web


async def fake_moonraker(components, listed, requests):
    async def ws_handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            req = json.loads(msg.data)
            method, rid = req["method"], req["id"]
            requests.append(req)
            result = {}
            if method == "server.info":
                result = {"klippy_state": "ready", "components": components}
            elif method == "printer.objects.list":
                result = {"objects": listed}
            elif method == "printer.objects.subscribe":
                result = {"status": {k: {} for k in req["params"]["objects"]}}
            elif method == "server.gcode_store":
                result = {"gcode_store": []}
            await ws.send_str(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}))
        return ws

    app = web.Application()
    app.router.add_get("/websocket", ws_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"


def subscribed(cfg, components, listed):
    from acebridge.moonraker import Moonraker
    requests = []

    async def main():
        runner, url = await fake_moonraker(components, listed, requests)
        cfg.moonraker_url = url
        async with aiohttp.ClientSession() as session:
            async def on_status(delta, full):
                pass
            moon = Moonraker(cfg, session, on_status)
            task = asyncio.create_task(moon.run())
            for _ in range(100):
                if any(r["method"] == "printer.objects.subscribe" for r in requests):
                    break
                await asyncio.sleep(0.02)
            task.cancel()
            platform = moon.platform
        await runner.cleanup()
        return platform, next(r["params"]["objects"] for r in requests if r["method"] == "printer.objects.subscribe")

    return asyncio.run(main())


def test_rinkhals_never_subscribes_absent_objects(cfg):
    listed = ["print_stats", "virtual_sdcard", "extruder", "heater_bed", "fan", "gcode_move", "bed_mesh",
              "fan_generic box_fan", "fan_generic air_filter_fan"]
    platform, objs = subscribed(cfg, ["kobra", "mmu_ace", "file_manager"], listed)
    assert platform == "rinkhals"
    assert "mmu" in objs and "filament_hub" in objs and "fan_generic box_fan" in objs
    assert not {"ace", "ace_instance_0", "kobra_pa", "kobra_resume", "kobra_phase"} & set(objs)


def test_klipper_subscribes_what_objects_list_names(cfg):
    listed = ["print_stats", "virtual_sdcard", "extruder", "heater_bed", "fan", "gcode_move", "bed_mesh",
              "ace", "ace_instance_0", "kobra_pa"]
    platform, objs = subscribed(cfg, ["file_manager"], listed)
    assert platform == "klipper"
    assert {"ace", "ace_instance_0", "kobra_pa"} <= set(objs)
    assert "mmu" not in objs and "filament_hub" not in objs and "kobra_resume" not in objs
