"""Home Assistant ingress (ingress.py): the web UI under a base path, trust only for the Supervisor's proxy, the camera
as single images (frame.jpg), relative paths in the web UI."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp.test_utils import TestServer
from test_camera import frame, make_cfg, printer  # noqa: F401 - pytest fixture

from acebridge import ingress
from acebridge.assets import index_html
from acebridge.auth import AuthError, Devices
from acebridge.camera import Camera

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "bridge/app/acebridge/static/js"


def req(remote="172.30.32.2", path="/api/hassio_ingress/abc", key=None):
    headers = {}
    if path:
        headers[ingress.HEADER] = path
    if key:
        headers["Authorization"] = "Bearer " + key
    return SimpleNamespace(headers=headers, remote=remote)


def test_ingress_only_from_the_supervisor_proxy():
    assert ingress.via_ingress(req())
    assert not ingress.via_ingress(req(remote="192.168.1.20"))       # header sent to the direct port: not ingress
    assert not ingress.via_ingress(req(path=None))
    cfg = SimpleNamespace(camera_ingress_snapshots=True, bridge_public_url="http://ha.local:7913/", http_port=7913)
    assert ingress.meta(req(), cfg) == {"ingress": "snapshots", "bridge-url": "http://ha.local:7913",
                                         "bridge-port": "7913"}
    assert ingress.meta(req(remote="10.1.1.1"), cfg) is None
    cfg.camera_ingress_snapshots = False
    assert ingress.meta(req(), cfg)["ingress"] == "stream"


def test_trust_is_off_by_default_and_never_for_a_spoofed_header(tmp_path):
    d = Devices(str(tmp_path))
    with pytest.raises(AuthError):
        d.require_request(req())
    t = Devices(str(tmp_path), trust_ingress=True)
    assert t.identify_request(req())["id"] == "ha_ingress"
    assert t.identify_request(req(remote="192.168.1.20")) is None
    with pytest.raises(AuthError) as e:
        t.require_request(req(remote="192.168.1.20"))
    assert e.value.status == 403                       # nothing paired yet
    key = t.pair(t.setup_code, "Phone", "app")["token"]
    assert t.identify_request(req(remote="192.168.1.20", path=None, key=key))["name"] == "Phone"
    assert t.identify_request(req(key=key))["name"] == "Phone"   # a key wins over the ingress device


def test_start_page_tells_the_browser():
    html = index_html(extra={"ingress": "snapshots", "bridge-url": 'x"><script>'})
    assert '<meta name="ingress" content="snapshots">' in html
    assert "<script>" not in html.split("bridge-url")[1].split(">")[0]       # escaped
    assert 'name="ingress"' not in index_html()


def test_web_ui_uses_relative_paths_only():
    bad = []
    for f in JS.glob("*.js"):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"""fetch\(\s*["'`]/|src=\$\{\s*`/|href=["'`]/(?!/)|new WebSocket\(\s*["'`]/""", line):
                bad.append(f"{f.name}:{i}")
    assert not bad, f"absolute paths break the UI under a base path (HA ingress): {bad}"
    for page in ("index.html", "display.html", "viewer.html"):
        text = (JS.parent / page).read_text(encoding="utf-8")
        assert not re.search(r"""(href|src)=["']/(?!/)""", text), page


def test_next_frame_waits_for_a_newer_image(printer):  # noqa: F811
    app, hits = printer

    async def go():
        async with TestServer(app) as srv, aiohttp.ClientSession() as s:
            cam = Camera(make_cfg(srv), SimpleNamespace(), s)
            img, no = await cam.next_frame(-1)
            assert img.startswith(b"\xff\xd8 frame ") and no >= 1
            img2, no2 = await cam.next_frame(no)
            assert no2 > no and img2 != img
            assert hits["stream"] == 1 and hits["snapshot"] == 0     # rides on the one stream to the printer
            cam._wanted_until = 0
            await asyncio.wait_for(cam._reader, 2)
    asyncio.run(go())


def test_ingress_path_is_learned_from_the_proxy_only_and_kept(tmp_path):
    seen = ingress.IngressPath(str(tmp_path))
    assert seen.view()["ha_ingress"] is None
    seen.seen(req(remote="192.168.1.20", path="/api/hassio_ingress/spoofed"))   # not from the Supervisor's proxy
    seen.seen(req(path="/api/hassio_ingress/../../etc"))                         # not a token
    assert seen.path == ""
    seen.seen(req(path="/api/hassio_ingress/s65bor48v40w3r0m8v-cn945mwdj5icjvwsd43cfnm3/"))
    assert seen.view()["ha_ingress"] == "/api/hassio_ingress/s65bor48v40w3r0m8v-cn945mwdj5icjvwsd43cfnm3"
    assert ingress.IngressPath(str(tmp_path)).path == seen.path                  # survives a restart


def test_ingress_path_from_the_supervisor(tmp_path):
    from aiohttp import web

    async def info(request):
        assert request.headers["Authorization"] == "Bearer sup"
        return web.json_response({"result": "ok", "data": {"slug": "abc_kobra",
                                                            "ingress_entry": "/api/hassio_ingress/tok123"}})

    app = web.Application()
    app.router.add_get("/addons/self/info", info)

    async def go():
        async with TestServer(app) as srv, aiohttp.ClientSession() as s:
            seen = ingress.IngressPath(str(tmp_path))
            await seen.discover(s, token="")                          # not an add-on: nothing
            assert seen.path == ""
            await seen.discover(s, token="sup", base=str(srv.make_url("")).rstrip("/"))
            assert seen.path == "/api/hassio_ingress/tok123"
            await seen.discover(s, token="sup", base="http://127.0.0.1:9")   # Supervisor gone: keeps what it knows
            assert seen.path == "/api/hassio_ingress/tok123"
    asyncio.run(go())
