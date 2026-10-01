"""Druckvorschau (render.py) und Kamera (camera.py): von der Bridge selbst gerechnet bzw. verteilt."""

from __future__ import annotations

import asyncio
import base64
import io
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from PIL import Image

from acebridge.camera import Camera, CameraError
from acebridge.render import GcodeModel, PrintPreview, display_rgb, parse_bytes, render_png


def png_bytes(w=8, h=8):
    out = io.BytesIO()
    Image.new("RGB", (w, h), (255, 0, 0)).save(out, "PNG")
    return out.getvalue()


def sample_gcode() -> bytes:
    """Zwei Schichten, zwei Werkzeuge, ein Vorschaubild, relative Extrusion wie bei Orca."""
    big = base64.b64encode(png_bytes(16, 16)).decode()
    small = base64.b64encode(png_bytes(4, 4)).decode()
    lines = [
        "; HEADER_BLOCK_START",
        f"; thumbnail begin 4x4 {len(small)}", f"; {small}", "; thumbnail end",
        f"; thumbnail begin 16x16 {len(big)}", f"; {big[:40]}", f"; {big[40:]}", "; thumbnail end",
        "G90", "M83", "T0",
        "G1 Z0.2 F600",
        "G1 X10 Y10 F3000",                   # Leerfahrt
        "G1 X20 Y10 E0.5", "G1 X30 Y10 E0.5",  # gerade weiter -> eine Strecke
        "G1 X30 Y20 E0.5",                    # Ecke -> neue Strecke
        "G1 E-0.8", "T1",
        "G1 X40 Y40", "G1 X50 Y40 E0.4",
        "G1 Z0.4", "G1 X50 Y50 E0.4 ; Kommentar",
        "; filament_colour = #685BC7;#EC008C",
    ]
    return ("\n".join(lines) + "\n").encode()


def test_parser_builds_segments_layers_thumbnail_and_colours():
    m = parse_bytes(sample_gcode())
    assert len(m) == 4                         # 20->30 mit 10->20 zusammengelegt
    assert list(m.tool) == [0, 0, 1, 1]
    assert m.layers == pytest.approx([0.2, 0.4])
    assert Image.open(io.BytesIO(m.thumbnail)).size == (16, 16)     # das groesste Bild gewinnt
    assert m.colours == ["685BC7", "EC008C"]
    assert m.layer_at(0) == 1 and m.layer_at(10 ** 9) == 2


def test_absolute_extrusion_and_resets():
    m = GcodeModel()
    for i, line in enumerate(["M82", "G92 E0", "G1 X0 Y0", "G1 X10 Y0 E1", "G1 X10 Y10 E1",   # E steht -> keine Strecke
                              "G92 E0", "G1 X0 Y10 E0.5"]):
        m.feed_line(line, i * 10)
    assert len(m) == 2


def test_render_marks_progress_and_is_a_png():
    data = sample_gcode()
    m = parse_bytes(data)
    full = render_png(m, None, ["685BC7", "EC008C"], width=300, height=200)
    half = render_png(m, len(data) // 2, ["685BC7", "EC008C"], width=300, height=200)
    assert Image.open(io.BytesIO(full)).size == (300, 200)
    assert full != half
    assert render_png(GcodeModel(), None, [], width=50, height=40).startswith(b"\x89PNG")


def test_dark_filament_stays_visible():
    r, g, b = display_rgb("212721")
    assert (r + g + b) / 3 > 60                # Schwarz wird fuer den dunklen Hintergrund aufgehellt
    assert display_rgb("EFF0F1") == (239, 240, 241)


@pytest.fixture
def gcode_server():
    hits = {"n": 0}

    async def gcode(request):
        hits["n"] += 1
        return web.Response(body=sample_gcode())

    async def camera(request):
        hits["n"] += 1
        return web.Response(body=b"\xff\xd8 fake jpeg", content_type="image/jpeg")

    app = web.Application()
    app.router.add_get("/server/files/gcodes/{name:.*}", gcode)
    app.router.add_get("/webcam/", camera)
    return app, hits


def test_preview_loads_the_running_file(gcode_server):
    app, hits = gcode_server

    async def go():
        async with TestServer(app) as srv, aiohttp.ClientSession() as s:
            cfg = SimpleNamespace(render=True, render_max_mb=200, render_interval_s=0,
                                  moonraker_url=str(srv.make_url("")).rstrip("/"))
            moon = SimpleNamespace(_headers=lambda: {})
            p = PrintPreview(cfg, moon, s)
            status = {"print_stats": {"state": "printing", "filename": "sub dir/test.gcode"},
                      "virtual_sdcard": {"file_position": 100},
                      "mmu": {"gate_color": ["FF0000FF", "00FF00FF"], "ttg_map": [1, 0]}}
            p.watch(status)
            await p._task
            assert p.status == "ready" and len(p.model) == 4
            assert p.colours(status)[:2] == ["00FF00", "FF0000"]    # Werkzeug -> Slot ueber ttg_map
            png = await p.render(status)
            assert png.startswith(b"\x89PNG") and p.info(status)["layers"] == 2
            p.watch(status)                                            # gleiche Datei: nicht neu laden
            assert hits["n"] == 1
    asyncio.run(go())


def test_camera_shares_one_snapshot(gcode_server):
    app, hits = gcode_server

    async def go():
        async with TestServer(app) as srv, aiohttp.ClientSession() as s:
            cfg = SimpleNamespace(camera=True, camera_interval_s=60,
                                  camera_snapshot_url=str(srv.make_url("/webcam/?action=snapshot")))
            cam = Camera(cfg, SimpleNamespace(), s)
            results = await asyncio.gather(*(cam.snapshot() for _ in range(5)))
            assert {r[0] for r in results} == {b"\xff\xd8 fake jpeg"} and hits["n"] == 1   # fuenf Zuschauer, ein Abruf
            cfg.camera = False
            with pytest.raises(CameraError):
                await cam.snapshot()
    asyncio.run(go())
