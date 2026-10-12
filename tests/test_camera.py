"""Camera (camera.py): one connection to the printer, passed on to any number of viewers."""

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
from acebridge.webcommon import send_mjpeg

JPEG = b"\xff\xd8 fake jpeg \xff\xd9"


def frame(i: int) -> bytes:
    return b"\xff\xd8 frame %d \xff\xd9" % i


@pytest.fixture
def printer():
    """Camera like Rinkhals' mjpg-streamer: stream with Content-Length and single frames; counts connections."""
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
                           camera_fps_min=1.0, camera_fps_max=fps_max, camera_stream_url=str(srv.make_url("/webcam/?action=stream")),
                           camera_snapshot_url=str(srv.make_url("/webcam/?action=snapshot")))


def test_read_mjpeg_without_content_length():
    class Content:                      # delivers the stream in small pieces like the network
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
            assert all(f.startswith(b"\xff\xd8 frame ") for r in res for f in r)    # never an empty image
            assert res[0][-1].startswith(b"\xff\xd8 frame ")
            img, _ = await cam.snapshot()                     # the single frame comes from the running stream
            assert img.startswith(b"\xff\xd8 frame ") and hits["snapshot"] == 0
            assert hits["stream"] == 1                          # four viewers + a single frame: one connection
            assert cam.fps() is not None and cam.fps() > 10
            assert cam.state()["mode"] == "stream"
            cam._wanted_until = 0                               # nobody watches any more: the stream closes
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
            assert hits["stream"] == 1          # no endless retrying: single frames for a while
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
                assert (await client.get("/api/camera/stream.mjpg?key=wrong")).status == 401
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
                # new key: the old link is dead
                r = await client.post("/api/camera/link", headers={"Authorization": "Bearer geheim"})
                assert (await r.json())["key"] != key
                assert (await client.get(f"/api/camera/snapshot.jpg?key={key}")).status == 401
            assert CameraKey(str(tmp_path)).key == bridge.camera_key.key     # survives a restart
    asyncio.run(go())


def test_resolve_skips_the_bridges_own_camera_link():
    """If the bridge's camera link is in Moonraker's webcam list (Mainsail), the bridge must not use it as its source."""
    class Moon:
        async def get_json(self, path):
            return {"webcams": [
                {"name": "Bridge", "enabled": True, "stream_url": "http://bridge:7913/api/camera/stream.mjpg?key=x",
                 "snapshot_url": "http://bridge:7913/api/camera/snapshot.jpg?key=x"},
                {"name": "Webcam", "enabled": True, "stream_url": "/webcam/?action=stream",
                 "snapshot_url": "/webcam/?action=snapshot"}]}

    async def go():
        cfg = SimpleNamespace(camera=True, camera_stream=True, camera_interval_s=1, camera_stream_url="",
                              camera_snapshot_url="", camera_fps_max=10.0, printer_base_url=lambda: "http://printer")
        cam = Camera(cfg, Moon(), None)
        await cam._resolve()
        return cam.stream_url, cam.snapshot_url
    assert asyncio.run(go()) == ("http://printer/webcam/?action=stream", "http://printer/webcam/?action=snapshot")


def test_default_polls_snapshots_and_never_opens_the_printer_stream(printer):
    """Default (Kobra S1): single frames one after another, passed to everyone - the expensive printer stream stays closed."""
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
            assert cam.state()["mode"] == "snapshots" and cam.state()["target_fps"] == 10.0   # the maximum rate right away
            cam._wanted_until = 0
            await asyncio.wait_for(cam._reader, 3)
            stopped = hits["snapshot"]
            await asyncio.sleep(0.2)
            assert hits["snapshot"] == stopped and not cam.streaming       # no more queries without viewers
    asyncio.run(go())


def test_viewer_disconnect_is_not_an_error():
    """aiohttp reports a viewer who left as ConnectionError("Connection lost") - normal, not an error
    (on the real device this was in the log as a traceback every 10 s)."""
    class Gone:
        writes = 0

        async def write(self, data):
            self.writes += 1
            if self.writes == 2:
                raise ConnectionError("Connection lost")

    async def frames():
        while True:
            yield JPEG

    async def go():
        resp, gen = Gone(), frames()
        await send_mjpeg(resp, JPEG, gen, "10.0.0.x")
        return resp.writes
    assert asyncio.run(go()) == 2                       # ends quietly after disconnecting


def test_rate_follows_printer_cpu_on_rinkhals():
    """High thresholds, small steps: the load while printing (75-89 %) comes from GoKlipper, not from the camera."""
    cfg = SimpleNamespace(camera=True, camera_stream=False, camera_fps_min=1.0, camera_fps_max=10.0,
                          camera_cpu_low=90.0, camera_cpu_high=97.0, camera_stream_url="x", camera_snapshot_url="y")
    cam = Camera(cfg, SimpleNamespace(platform="rinkhals"), None)
    assert cam._throttles() and not Camera(cfg, SimpleNamespace(platform="klipper"), None)._throttles()
    cam.target_fps = 2.0
    for _ in range(20):
        cam.adjust(80.0)                                   # normal print: up to the maximum
    assert cam.target_fps == 10.0 and not cam.throttled
    cam.adjust(92.0)
    assert cam.target_fps == 10.0                          # between the thresholds: hold
    cam.adjust(99.0)
    assert cam.target_fps == 9.0 and cam.throttled         # at the limit: only 1 fps less, not halved
    for _ in range(20):
        cam.adjust(100.0)
    assert cam.target_fps == 1.0                           # never below the minimum
    cam.adjust(None)
    assert cam.target_fps == 1.0                           # no CPU values: change nothing
    for _ in range(9):
        cam.adjust(60.0)
    assert cam.target_fps == 10.0 and not cam.throttled
