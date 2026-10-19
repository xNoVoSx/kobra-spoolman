"""Printer CPU (printercpu.py): the printer's own CPU under Rinkhals and beside Klipper on a Pi (USB tunnel).

19.10.: with Klipper on the Pi a continuous camera stream still took the printer CPU to 100 % - mjpg-streamer and the
tunnel stay on the printer. Its Rinkhals Moonraker keeps running there and reports the CPU; the bridge reads it, the
camera follows it (no continuous stream, frame rate by the CPU), web/app/display/HA show it."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

from acebridge import printercpu
from acebridge.camera import Camera
from acebridge.printercpu import PrinterCpu, parse_cpu


def cfg(**kw):
    base = dict(moonraker_url="http://pi.local:7125", printer_cpu_url="", camera=True, camera_stream=True,
                camera_interval_s=0, camera_fps_min=1.0, camera_fps_max=10.0, camera_cpu_low=90.0, camera_cpu_high=97.0,
                camera_stream_url="http://printer.local:8080/?action=stream",
                camera_snapshot_url="http://printer.local:8080/?action=snapshot")
    base.update(kw)
    return SimpleNamespace(**base)


def candidate(c, camera_url="http://printer.local:8080/?action=stream"):
    async def src():
        return camera_url
    return asyncio.run(PrinterCpu(c, SimpleNamespace(platform="klipper"), None, source_url=src)._candidate())


def test_parse_proc_stats():
    assert parse_cpu({"system_cpu_usage": {"cpu": 40.91, "cpu0": 40.91}}) == 40.91
    assert parse_cpu({}) is None and parse_cpu({"system_cpu_usage": {"cpu": "x"}}) is None


def test_address_from_the_camera_unless_it_is_the_klipper_computer():
    assert candidate(cfg()) == "http://printer.local:7125"                         # camera on the printer
    assert candidate(cfg(), "http://pi.local/webcam/?action=stream") is None        # camera on the Pi: says nothing
    assert candidate(cfg(), None) is None
    assert candidate(cfg(printer_cpu_url="off")) is None                            # switched off
    assert candidate(cfg(printer_cpu_url="printer-host:7125")) == "http://printer-host:7125"
    assert candidate(cfg(printer_cpu_url="http://drucker:7125/")) == "http://drucker:7125"


def test_rinkhals_takes_moonrakers_own_value():
    pc = PrinterCpu(cfg(), SimpleNamespace(platform="rinkhals", cpu=lambda w: 77.0), None)
    assert pc.measures() and pc.source() == "rinkhals" and pc.cpu(10) == 77.0
    plain = PrinterCpu(cfg(), SimpleNamespace(platform="klipper", cpu=lambda w: 12.0), None)
    assert not plain.measures() and plain.source() is None and plain.cpu(10) is None   # 12 % is the Pi's CPU


def test_reads_the_printers_moonraker_and_the_camera_follows(monkeypatch):
    monkeypatch.setattr(printercpu, "POLL_S", 0.01)
    hits = {"n": 0}

    async def proc_stats(_):
        hits["n"] += 1
        return web.json_response({"result": {"system_cpu_usage": {"cpu": 98.5, "cpu0": 98.5}}})

    app = web.Application()
    app.router.add_get("/machine/proc_stats", proc_stats)

    async def go():
        async with TestServer(app) as srv, aiohttp.ClientSession() as s:
            c = cfg(printer_cpu_url=str(srv.make_url("")))
            moon = SimpleNamespace(platform="klipper", connected=True)
            cam = Camera(c, moon, s)
            assert cam.use_stream() and cam.state()["printer_cpu"] is None     # nothing known yet: the setting holds
            task = asyncio.create_task(cam.printer_cpu.run())
            for _ in range(200):
                await asyncio.sleep(0.01)
                if hits["n"] >= 3:
                    break
            task.cancel()
            pc = cam.printer_cpu
            assert pc.source() == "printer" and round(pc.cpu(10)) == 98
            st = cam.state()
            assert not cam.use_stream() and st["stream_ignored"] is True and st["printer_cpu"] == 98
            cam.target_fps = 10.0
            cam.adjust(pc.cpu(10))
            assert cam.target_fps == 9.0 and cam.throttled                   # above CAMERA_CPU_HIGH: slower
    asyncio.run(go())


def test_unreachable_printer_is_not_a_source(monkeypatch):
    monkeypatch.setattr(printercpu, "RETRY_S", 0.01)

    async def go():
        async with aiohttp.ClientSession() as s:
            pc = PrinterCpu(cfg(printer_cpu_url="http://127.0.0.1:9"), SimpleNamespace(platform="klipper", connected=True), s)
            task = asyncio.create_task(pc.run())
            await asyncio.sleep(0.3)
            task.cancel()
            assert not pc.measures() and pc.cpu(10) is None and pc.error
    asyncio.run(go())
