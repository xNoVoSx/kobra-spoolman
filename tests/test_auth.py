"""Geraete koppeln: Einrichtungscode, Kopplungscodes, Schluessel, Bremse, Entfernen."""

from __future__ import annotations

import asyncio
import json

import pytest
from aiohttp.test_utils import TestClient, TestServer
from test_appapi import FakeBridge

from acebridge.auth import CODE_TTL_S, AuthError, Devices
from acebridge.web import build_app


class Clock:
    t = 1_000_000.0

    def __call__(self):
        return self.t


def test_setup_code_pairs_the_first_device_and_is_then_gone(tmp_path):
    d = Devices(str(tmp_path), clock=Clock())
    assert d.setup_required and d.setup_code
    res = d.pair(d.setup_code, "Browser Büro", "web")
    assert res["device"]["name"] == "Browser Büro" and len(res["token"]) > 30
    assert d.setup_code is None and not d.setup_required
    assert d.identify(f"Bearer {res['token']}")["name"] == "Browser Büro"
    assert d.identify("Bearer falsch") is None and d.identify(None) is None
    # nur der Hash liegt auf der Platte
    saved = json.loads((tmp_path / "devices.json").read_text())
    assert res["token"] not in json.dumps(saved)
    # neu geladen: weiter gekoppelt
    assert Devices(str(tmp_path)).identify(f"Bearer {res['token']}") is not None


def test_pairing_codes_are_single_use_and_expire(tmp_path):
    clock = Clock()
    d = Devices(str(tmp_path), clock=clock)
    d.pair(d.setup_code, "PC", "web")
    code = d.new_code()["code"]
    d.pair(code, "Handy", "app")
    with pytest.raises(AuthError):
        d.pair(code, "Nochmal", "app")               # einmal verwendbar
    code = d.new_code()["code"]
    clock.t += CODE_TTL_S + 1
    with pytest.raises(AuthError):
        d.pair(code, "Zu spät", "app")               # abgelaufen


def test_wrong_codes_are_throttled(tmp_path):
    clock = Clock()
    d = Devices(str(tmp_path), clock=clock)
    for _ in range(5):
        with pytest.raises(AuthError) as e:
            d.pair("000000" if d.setup_code != "000000" else "111111", "x", "web")
        assert e.value.status == 401
    with pytest.raises(AuthError) as e:
        d.pair(d.setup_code, "x", "web")             # auch der richtige Code: erst warten
    assert e.value.status == 429
    clock.t += 61
    assert d.pair(d.setup_code, "x", "web")["token"]


def test_legacy_app_token_still_works(tmp_path):
    d = Devices(str(tmp_path), legacy_token="alt")
    assert not d.setup_required and d.identify("Bearer alt") is not None
    assert d.pair("alt", "Handy", "app")["token"]    # zum Koppeln verwendbar


def test_removing_the_last_device_brings_back_a_setup_code(tmp_path):
    d = Devices(str(tmp_path))
    dev = d.pair(d.setup_code, "PC", "web")["device"]
    d.remove(dev["id"])
    assert d.setup_code and d.setup_required


def test_http_flow(cfg, tmp_path):
    cfg.app_token = ""
    bridge = FakeBridge(cfg)

    async def go():
        async with TestClient(TestServer(build_app(bridge))) as c:
            st = await (await c.get("/api/auth/status")).json()
            assert st["setup_required"] and st["device"] is None
            r = await c.post("/api/auth/pair", json={"code": bridge.devices.setup_code, "name": "PC", "kind": "web"})
            assert r.status == 201
            token = (await r.json())["token"]
            h = {"Authorization": f"Bearer {token}"}
            assert (await (await c.get("/api/app/state", headers=h)).json())["can_write"] is True
            assert (await (await c.get("/api/app/state")).json())["can_write"] is False
            code = (await (await c.post("/api/auth/code", headers=h)).json())["code"]
            r = await c.post("/api/auth/pair", json={"code": code, "name": "S26", "kind": "app"})
            phone = (await r.json())["device"]
            devs = (await (await c.get("/api/auth/devices", headers=h)).json())["devices"]
            assert [(x["name"], x["me"]) for x in devs] == [("PC", True), ("S26", False)]
            assert (await c.delete(f"/api/auth/devices/{phone['id']}", headers=h)).status == 200
            assert (await c.post("/api/auth/code")).status == 401        # ohne Schluessel kein Code
    asyncio.run(go())
