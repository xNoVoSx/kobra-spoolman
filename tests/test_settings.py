"""Einstellungen im laufenden Betrieb: Startwert aus der Umgebung, gespeichert in settings.json."""

from __future__ import annotations

import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer
from test_appapi import FakeBridge

from acebridge.config import Config
from acebridge.runtime_settings import SPECS, RuntimeSettings
from acebridge.web import build_app


def test_every_setting_exists_in_the_config(cfg):
    for s in SPECS:
        assert hasattr(cfg, s.key), s.key


def test_update_validates_saves_and_survives_restart(cfg, monkeypatch):
    rs = RuntimeSettings(cfg)
    rs.update({"low_spool_g": 150, "camera": False})
    assert cfg.low_spool_g == 150 and cfg.camera is False
    for bad in ({"low_spool_g": -1}, {"camera": "ja"}, {"telemetry_keep": 2.5}, {"moonraker_url": "x"}, {"gibtsnicht": 1}):
        with pytest.raises(ValueError):
            rs.update(bad)
    with pytest.raises(ValueError):                        # mindestens > hoechstens: nichts uebernommen
        rs.update({"camera_fps_min": 12, "camera_fps_max": 5})
    assert cfg.camera_fps_min == 1.0 and cfg.camera_fps_max == 10.0
    fresh = Config()                                       # Neustart: Umgebung liefert die Startwerte ...
    RuntimeSettings(fresh)                                 # ... gespeicherte Werte gewinnen
    assert fresh.low_spool_g == 150 and fresh.camera is False
    rs.reset("low_spool_g")
    assert cfg.low_spool_g == 100 and "low_spool_g" not in rs.saved
    item = next(i for g in rs.view()["groups"] for i in g["items"] if i["key"] == "camera")
    assert item["value"] is False and item["default"] is True and item["changed"]


def test_low_spool_threshold_is_used_by_messages(cfg):
    from acebridge.status import notices
    bridge = FakeBridge(cfg)
    spool = bridge.sm.spools[0]
    spool["remaining_weight"] = 120
    before = [m for m in notices(bridge)["messages"] if m["key"].startswith("low")]
    bridge.settings.update({"low_spool_g": 200})
    after = [m for m in notices(bridge)["messages"] if m["key"].startswith("low")]
    assert len(after) == len(before) + 1


def test_api_needs_pairing(cfg):
    cfg.app_token = "geheim"
    bridge = FakeBridge(cfg)

    async def go():
        async with TestClient(TestServer(build_app(bridge))) as c:
            v = await (await c.get("/api/settings")).json()
            assert {g["name"] for g in v["groups"]} >= {"Kamera", "Meldungen", "Daten"} and v["readonly"]
            assert (await c.post("/api/settings", json={"low_spool_g": 50})).status == 401
            h = {"Authorization": "Bearer geheim"}
            r = await c.post("/api/settings", json={"low_spool_g": 5000}, headers=h)
            assert r.status == 400 and "erlaubt" in (await r.json())["error"]
            assert (await c.post("/api/settings", json={"low_spool_g": 50}, headers=h)).status == 200
            assert cfg.low_spool_g == 50
            assert (await c.post("/api/settings/reset", json={"key": "low_spool_g"}, headers=h)).status == 200
            assert cfg.low_spool_g == 100
    asyncio.run(go())
