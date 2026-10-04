"""Druckvorschau (render.py): von der Bridge selbst gerechnet."""

from __future__ import annotations

import asyncio
import base64
import io
import math
import struct
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from PIL import Image

from acebridge.render import simplify, strand_width, BED_MM, GcodeModel, PrintPreview, display_rgb, geometry_bin, parse_bytes, render_png


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


def test_geometry_for_the_3d_view():
    import struct
    from array import array
    m = parse_bytes(sample_gcode())
    g = geometry_bin(m)
    assert g[:4] == b"KSG1"
    ver, _, n, nl, step, bed, zmax = struct.unpack("<HHIIIff", g[4:28])
    assert (ver, n, nl, step, bed) == (2, 4, 2, 1, BED_MM) and zmax == pytest.approx(0.4)
    def arr(code, raw):
        a = array(code)
        a.frombytes(raw)
        return a
    layers = arr("f", g[28:28 + 4 * nl])
    assert list(layers) == pytest.approx([0.2, 0.4])
    cols = g[28 + 4 * nl:]
    x0 = arr("H", cols[:2 * n])
    layer = arr("H", cols[10 * n:12 * n])
    tool = arr("B", cols[12 * n:13 * n])
    assert x0[0] == round(10 / BED_MM * 65535) and list(layer) == [0, 0, 0, 1] and list(tool) == [0, 0, 1, 1]
    width = arr("B", cols[13 * n:14 * n])
    assert all(5 <= w <= 255 for w in width)
    assert len(g) == 28 + 4 * nl + 14 * n
    assert m.done_index(0) == 0 and m.done_index(10 ** 9) == 4
    small = geometry_bin(m, max_segments=2)
    assert struct.unpack("<I", small[8:12])[0] <= 2 and small[16:20] == struct.pack("<I", 1)


def arc_gcode(n=60, r=20.0):
    """Kreis aus n kleinen Stuecken (wie eine runde Wand) plus eine gerade Linie mit anderem Werkzeug."""
    pts = [(100 + r * math.cos(2 * math.pi * i / n), 100 + r * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]
    lines = ["M83", "T0", f"G1 X{pts[0][0]:.4f} Y{pts[0][1]:.4f} Z0.2"]
    lines += [f"G1 X{x:.4f} Y{y:.4f} E0.02" for x, y in pts[1:]]
    lines += ["T1", "G1 X10 Y10", "G1 X60 Y10 E2"]
    return ("\n".join(lines) + "\n").encode()


def test_simplify_merges_curves_without_gaps():
    m = parse_bytes(arc_gcode())
    assert len(simplify(m)) == len(m)                                 # passt unter die Grenze: nichts zusammengefasst
    ends = simplify(m, max_segments=len(m) * 2 // 3)                  # Grenze erzwingt Zusammenfassen
    assert 8 < len(ends) <= len(m) * 2 // 3
    assert ends[-1] == len(m) - 1 and m.tool[ends[-2]] == 0           # Werkzeugwechsel trennt immer
    starts = [0] + [e + 1 for e in ends[:-1]]
    for a, b in zip(starts[1:], ends[:-1], strict=False):             # lueckenlos: jede Strecke beginnt am Ende der vorigen
        assert a == b + 1
    # Abweichung jeder Original-Ecke von ihrer zusammengefassten Strecke <= hoechste Toleranz
    for a, b in zip(starts, ends, strict=True):
        ax, ay, bx, by = m.x0[a], m.y0[a], m.x1[b], m.y1[b]
        L = math.hypot(bx - ax, by - ay) or 1
        for k in range(a, b + 1):
            assert abs((bx - ax) * (ay - m.y1[k]) - (ax - m.x1[k]) * (by - ay)) / L <= 0.2 + 1e-6


def test_progress_counts_merged_segments():
    m = parse_bytes(arc_gcode())
    ends = simplify(m, max_segments=len(m) * 2 // 3)
    g = geometry_bin(m, ends=ends)
    assert struct.unpack("<I", g[8:12])[0] == len(ends)
    import bisect
    mid = len(m) // 2
    done = bisect.bisect_left(ends, m.done_index(m.offset[mid]))      # Position nach Original-Strecke mid
    assert 0 < done < len(ends) and ends[done - 1] <= mid


def test_strand_width_from_extrusion():
    # 0,4 mm breit bei 0,2 mm Schicht: Flaeche (0,4 - 0,2) * 0,2 + pi * 0,01 = 0,0714 mm^2 -> E pro 10 mm
    area = (0.4 - 0.2) * 0.2 + math.pi * 0.1 ** 2
    e = area * 10 / (math.pi * 0.875 ** 2)
    m = parse_bytes(("; filament_diameter = 1.75\nM83\nG1 X0 Y0 Z0.2\n"
                     f"G1 X10 Y0 E{e:.5f}\nG1 X10 Y10 E{2 * e:.5f}\nG1 X10.01 Y10 E0.1\n").encode())
    heights = [m.layers[0]]
    assert strand_width(m, 0, heights, m.layers) == 40
    assert strand_width(m, 1, heights, m.layers) == 76             # doppelte Menge -> breiter
    assert strand_width(m, 2, heights, m.layers) == 45             # zu kurz zum Rechnen -> Standard


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

    app = web.Application()
    app.router.add_get("/server/files/gcodes/{name:.*}", gcode)
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
