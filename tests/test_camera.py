"""Kamera (camera.py): eine Verbindung zum Drucker, weiterverteilt an beliebig viele Zuschauer."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from acebridge.auth import CameraKey, Devices
from acebridge.camera import Camera, CameraError, read_mjpeg
from acebridge.web import build_app

JPEG = b"\xff\xd8 fake jpeg \xff\xd9"


def frame(i: int) -> bytes:
    return b"\xff\xd8 frame %d \xff\xd9" % i


@pytest.fixture
def printer():
    """Kamera wie Rinkhals' mjpg-streamer: Stream mit Content-Length und Einzelbilder; zaehlt Verbindungen."""
    hits = {"stream": 0, "snapshot": 0, "open": 0}

    async def webcam(request):
        if request.query.get("action") == "stream":
            hits["stream"] += 1
            if hits.get("no_stream"):
                return web.Response(status=404)
            hits["open"] += 1
            resp = web.StreamResponse(headers={"Content-Type": "multipart/x-mixed-replace;boundary=boundarydonotcross"})
            await resp.prepare(request)
            try:
                await resp.write(b"\r\n--boundarydonotcross\r\n")
                for i in range(10_000):
                    f = frame(i)
                    await resp.write(b"Content-Type: image/jpeg\r\nContent-Length: %d\r\nX-Timestamp: 1.0\r\n\r\n" % len(f)
                                     + f + b"\r\n--boundarydonotcross\r\n")
                    await asyncio.sleep(0.02)
            except (ConnectionResetError, asyncio.CancelledError):
                pass
            finally:
                hits["open"] -= 1
            return resp
        hits["snapshot"] += 1
        return web.Response(body=JPEG, content_type="image/jpeg")

    app = web.Application()
    app.router.add_get("/webcam/", webcam)
    return app, hits


def make_cfg(srv, stream=True, interval=60, fps_max=10.0):
    return SimpleNamespace(camera=True, camera_stream=stream, camera_interval_s=interval,
                           camera_fps_min=1.0, camera_fps_max=fps_max, camera_cpu_low=70.0, camera_cpu_high=85.0,
                           camera_stream_url=str(srv.make_url("/webcam/?action=stream")),
                           camera_snapshot_url=str(srv.make_url("/webcam/?action=snapshot")))


def test_read_mjpeg_without_content_length():
    class Content:                      # liefert den Strom in kleinen Stuecken wie das Netz
        def __init__(self, data):
            self.data = data

        async def read(self, n):
            chunk, self.data = self.data[:7], self.data[7:]
            return chunk

    async def go():
        data = (b"--b\r\nContent-Type: image/jpeg\r\n\r\n" + frame(1) + b"\r\n--b\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame(2) + b"\r\n")
        return [f async for f in read_mjpeg(Content(data))]
    assert asyncio.run(go()) == [frame(1), frame(2)]


def test_snapshots_are_shared_without_stream(printer):
    app, hits = printer

    async def go():
        async with TestServer(app) as srv, aiohttp.ClientSession() as s:
            cfg = make_cfg(srv, stream=False)
            cam = Camera(cfg, SimpleNamespace(), s)
            results = await asyncio.gather(*(cam.snapshot() for _ in range(5)))
            assert {r[0] for r in results} == {JPEG} and hits["snapshot"] == 1 and hits["stream"] == 0
            cfg.camera = False
            with pytest.raises(CameraError):
                await cam.snapshot()
    asyncio.run(go())


def test_many_viewers_one_printer_connection(printer):
    app, hits = printer

    async def go():
        async with TestServer(app) as srv, aiohttp.ClientSession() as s:
            cam = Camera(make_cfg(srv), SimpleNamespace(), s)

            async def viewer(n, fps=None):
                got = []
                async for f in cam.frames(fps):
                    got.append(f)
                    if len(got) == n:
                        break
                return got

            res = await asyncio.gather(viewer(8), viewer(8), viewer(8), viewer(3, fps=10))
            assert all(len(r) == n for r, n in zip(res, (8, 8, 8, 3)))
            assert all(f.startswith(b"\xff\xd8 frame ") for r in res for f in r)    # nie ein leeres Bild
            assert res[0][-1].startswith(b"\xff\xd8 frame ")
            img, _ = await cam.snapshot()                     # Einzelbild kommt aus dem laufenden Stream
            assert img.startswith(b"\xff\xd8 frame ") and hits["snapshot"] == 0
            assert hits["stream"] == 1                          # vier Zuschauer + Einzelbild: eine Verbindung
            assert cam.fps() is not None and cam.fps() > 10
            assert cam.state()["mode"] == "stream"
            cam._wanted_until = 0                               # niemand schaut mehr: Stream schliesst
            await asyncio.wait_for(cam._reader, 2)
            assert not cam.streaming
    asyncio.run(go())


def test_falls_back_to_snapshots_when_printer_has_no_stream(printer):
    app, hits = printer
    hits["no_stream"] = True

    async def go():
        async with TestServer(app) as srv, aiohttp.ClientSession() as s:
            cam = Camera(make_cfg(srv, interval=0), SimpleNamespace(), s)
            img, _ = await cam.snapshot()
            assert img == JPEG
            await asyncio.sleep(0.05)
            await cam.snapshot()
            assert hits["stream"] == 1          # kein Dauerversuch: Einzelbilder fuer eine Weile
    asyncio.run(go())


def test_camera_routes_need_device_or_camera_key(printer, tmp_path):
    app, hits = printer

    async def go():
        async with TestServer(app) as srv, aiohttp.ClientSession() as s:
            devices = Devices(str(tmp_path), "geheim")
            bridge = SimpleNamespace(camera=Camera(make_cfg(srv), SimpleNamespace(), s), devices=devices,
                                     camera_key=CameraKey(str(tmp_path)), cfg=SimpleNamespace(data_dir=str(tmp_path)))
            async with TestClient(TestServer(build_app(bridge))) as client:
                assert (await client.get("/api/camera/snapshot.jpg")).status == 401
                assert (await client.get("/api/camera/stream.mjpg?key=falsch")).status == 401
                r = await client.get("/api/camera/link", headers={"Authorization": "Bearer geheim"})
                key = (await r.json())["key"]
                r = await client.get(f"/api/camera/snapshot.jpg?key={key}")
                assert r.status == 200 and (await r.read()).startswith(b"\xff\xd8")
                r = await client.get(f"/api/camera/stream.mjpg?key={key}")
                assert r.headers["Content-Type"].startswith("multipart/x-mixed-replace")
                frames = []
                async for f in read_mjpeg(r.content):
                    frames.append(f)
                    if len(frames) == 3:
                        break
                assert len(frames) == 3 and frames[0].startswith(b"\xff\xd8 frame ")
                r.close()
                # neuer Schluessel: alter Link tot
                r = await client.post("/api/camera/link", headers={"Authorization": "Bearer geheim"})
                assert (await r.json())["key"] != key
                assert (await client.get(f"/api/camera/snapshot.jpg?key={key}")).status == 401
            assert CameraKey(str(tmp_path)).key == bridge.camera_key.key     # bleibt nach Neustart
    asyncio.run(go())


def test_resolve_skips_the_bridges_own_camera_link():
    """Steht der Kamera-Link der Bridge in Moonrakers Webcam-Liste (Mainsail), darf die Bridge ihn nicht als Quelle nehmen."""
    class Moon:
        async def get_json(self, path):
            return {"webcams": [
                {"name": "Bridge", "enabled": True, "stream_url": "http://bridge:7913/api/camera/stream.mjpg?key=x",
                 "snapshot_url": "http://bridge:7913/api/camera/snapshot.jpg?key=x"},
                {"name": "Webcam", "enabled": True, "stream_url": "/webcam/?action=stream",
                 "snapshot_url": "/webcam/?action=snapshot"}]}

    async def go():
        cfg = SimpleNamespace(camera=True, camera_stream=True, camera_interval_s=1, camera_stream_url="",
                              camera_snapshot_url="", printer_base_url=lambda: "http://drucker")
        cam = Camera(cfg, Moon(), None)
        await cam._resolve()
        return cam.stream_url, cam.snapshot_url
    assert asyncio.run(go()) == ("http://drucker/webcam/?action=stream", "http://drucker/webcam/?action=snapshot")


def test_default_polls_snapshots_and_never_opens_the_printer_stream(printer):
    """Standard (Kobra S1): Einzelbilder nacheinander, verteilt an alle - der teure Drucker-Stream bleibt zu."""
    app, hits = printer

    async def go():
        async with TestServer(app) as srv, aiohttp.ClientSession() as s:
            cam = Camera(make_cfg(srv, stream=False, interval=0), SimpleNamespace(), s)

            async def viewer(n):
                got = []
                async for f in cam.frames():
                    got.append(f)
                    if len(got) == n:
                        break
                return got

            res = await asyncio.gather(viewer(3), viewer(3))
            assert all(f == JPEG for r in res for f in r)
            assert hits["stream"] == 0 and hits["snapshot"] >= 3
            assert cam.state()["mode"] == "snapshots" and cam.state()["target_fps"] == 2.0
            cam._wanted_until = 0
            await asyncio.wait_for(cam._reader, 3)
            stopped = hits["snapshot"]
            await asyncio.sleep(0.2)
            assert hits["snapshot"] == stopped and not cam.streaming       # ohne Zuschauer keine Abfragen mehr
    asyncio.run(go())


def test_rate_follows_printer_cpu():
    cfg = SimpleNamespace(camera=True, camera_stream=False, camera_fps_min=1.0, camera_fps_max=10.0,
                          camera_cpu_low=70.0, camera_cpu_high=85.0, camera_stream_url="x", camera_snapshot_url="y")
    cam = Camera(cfg, SimpleNamespace(), None)
    cam.target_fps = 2.0
    for _ in range(20):
        cam.adjust(40.0)                                   # Drucker hat Luft: hoch bis zum Maximum
    assert cam.target_fps == 10.0 and not cam.throttled
    cam.adjust(95.0)
    assert cam.target_fps == 5.0 and cam.throttled         # zu viel: sofort halbieren
    cam.adjust(78.0)
    assert cam.target_fps == 5.0                           # zwischen den Schwellen: halten
    for _ in range(5):
        cam.adjust(99.0)
    assert cam.target_fps == 1.0                           # nie unter das Minimum
    cam.adjust(None)
    assert cam.target_fps == 1.0                           # ohne CPU-Werte nichts aendern
    for _ in range(9):
        cam.adjust(50.0)
    assert cam.target_fps == 10.0 and not cam.throttled
