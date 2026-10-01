"""Konsole (console.py): Rueckfragen bei riskanten Befehlen, Verlauf, Bridge-Log - und die HTTP-Routen."""

from __future__ import annotations

import asyncio
import logging

import pytest
from aiohttp.test_utils import TestClient, TestServer
from test_appapi import FakeBridge

from acebridge.console import Console, LogBuffer, check_command
from acebridge.web import build_app


@pytest.mark.parametrize("script,printing,needs", [
    ("M115", False, False),
    ("M112", False, True),
    ("save_config", False, True),                       # klein geschrieben auch
    ("G28", False, False),
    ("G28", True, True),                                # Bewegung im Druck
    ("M104 S240", False, False),
    ("M104 S280", False, True),                         # Duese ueber 260 °C
    ("SET_HEATER_TEMPERATURE HEATER=extruder TARGET=300", False, True),
    ("SET_HEATER_TEMPERATURE HEATER=heater_bed TARGET=100", False, False),
    ("M117 hallo\nFIRMWARE_RESTART", False, True),       # jede Zeile wird geprueft
    ("; nur Kommentar", False, False),
    ("SET_FAN_SPEED FAN=box_fan SPEED=0.5", True, False),
])
def test_check_command(script, printing, needs):
    assert (check_command(script, printing) is not None) is needs


def test_console_seed_and_since():
    c = Console(clock=lambda: 100.0)
    c.seed([{"message": "G28", "type": "command", "time": 1.0}, {"message": "ok", "type": "response", "time": 2.0}])
    c.seed([{"message": "doppelt", "type": "response", "time": 3.0}])       # nach Reconnect kein zweiter Vorlauf
    assert [(x["kind"], x["text"], x["source"]) for x in c.lines] == [("command", "G28", "Verlauf"), ("response", "ok", None)]
    c.add("command", "M115", "Browser")
    c.add("response", "   ")                                                 # leere Zeilen weg
    new = c.since(2)
    assert [x["text"] for x in new] == ["M115"] and new[0]["time"] == 100.0


def test_log_buffer_levels():
    buf = LogBuffer(keep=3)
    lg = logging.getLogger("test-buffer")
    lg.addHandler(buf)
    lg.setLevel(logging.DEBUG)
    try:
        lg.debug("eins")
        lg.warning("zwei")
        lg.error("drei")
        lg.info("vier")
    finally:
        lg.removeHandler(buf)
    assert [r["text"] for r in buf.since()] == ["zwei", "drei", "vier"]          # nur die letzten 3
    assert [r["text"] for r in buf.since(level="WARNING")] == ["zwei", "drei"]
    assert "ERROR" in buf.text()


@pytest.fixture
def api(cfg):
    cfg.app_token = "geheim"
    bridge = FakeBridge(cfg)
    sent = []

    async def gcode(script, timeout=15, source="Bridge"):
        sent.append((script, source))
    bridge.moon.gcode = gcode

    def call(method, path, body=None, token="geheim"):
        async def go():
            async with TestClient(TestServer(build_app(bridge))) as client:
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                resp = await client.request(method, path, json=body, headers=headers)
                return resp.status, await resp.json()
        return asyncio.run(go())
    return bridge, call, sent


def test_console_send_needs_confirm_for_risky(api):
    bridge, call, sent = api
    assert call("POST", "/api/console", {"script": "M115"}, token=None)[0] == 401
    assert call("POST", "/api/console", {"script": "M115"})[0] == 200
    status, res = call("POST", "/api/console", {"script": "SAVE_CONFIG"})
    assert status == 409 and res["confirm"] is True and "SAVE_CONFIG" in res["error"]
    assert call("POST", "/api/console", {"script": "SAVE_CONFIG", "confirm": True})[0] == 200
    bridge.moon.merge({"print_stats": {"state": "printing"}})
    assert call("POST", "/api/console", {"script": "G28"})[0] == 409
    assert [s for s, _ in sent] == ["M115", "SAVE_CONFIG"] and sent[0][1] == "APP_TOKEN (Übergang)"


def test_console_and_logs_read(api):
    bridge, call, _ = api
    bridge.console.add("response", "ok")
    status, res = call("GET", "/api/console?after=0", token=None)
    assert status == 200 and res["lines"][-1]["text"] == "ok"
    status, res = call("GET", "/api/logs?level=INFO", token=None)
    assert status == 200 and isinstance(res["lines"], list)
