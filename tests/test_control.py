"""Drucksteuerung (control.py): Nachjustieren und Pause/Weiter/Abbrechen/Not-Aus mit Rueckfragen."""

from __future__ import annotations

import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer
from test_appapi import FakeBridge

from acebridge.control import ControlError, check_action, tune_commands
from acebridge.web import build_app


def test_tune_commands_match_what_the_s1_accepts():
    cmds, confirm = tune_commands({"speed": 150, "flow": 95, "fans": {"part": 30, "box": 30, "filter": 0},
                                   "nozzle": 220, "bed": 60})
    assert cmds == ["M220 S150", "M221 S95", "M106 S76", "SET_FAN_SPEED FAN=box_fan SPEED=0.3",
                    "SET_FAN_SPEED FAN=air_filter_fan SPEED=0", "M104 S220", "M140 S60"]
    assert confirm is None
    assert tune_commands({"nozzle": 280})[1]                       # heiss: Rueckfrage


@pytest.mark.parametrize("body", [{"speed": 5}, {"flow": 200}, {"fans": {"part": 120}}, {"fans": {"turbo": 10}},
                                  {"bed": 130}, {"nozzle": "heiss"}, {}])
def test_tune_rejects_out_of_range(body):
    with pytest.raises(ControlError):
        tune_commands(body)


def test_actions_check_state_and_confirmation():
    assert check_action("pause", "printing", False)[0] == "printer.print.pause"
    with pytest.raises(ControlError):
        check_action("resume", "printing", False)                 # nicht pausiert
    with pytest.raises(ControlError) as e:
        check_action("cancel", "printing", False)
    assert e.value.confirm
    assert check_action("cancel", "paused", True)[0] == "printer.print.cancel"
    with pytest.raises(ControlError) as e:
        check_action("emergency_stop", "standby", False)
    assert e.value.confirm and "neu laden" in str(e.value)
    assert check_action("emergency_stop", "standby", True)[0] == "printer.emergency_stop"


def test_firmware_restart_only_without_print():
    """Klipper neu laden (nach Not-Aus oder Abschaltung) - nie waehrend eines Drucks, immer mit Rueckfrage."""
    for state in ("printing", "paused"):
        with pytest.raises(ControlError) as e:
            check_action("firmware_restart", state, True)
        assert e.value.status == 409 and not e.value.confirm
    with pytest.raises(ControlError) as e:
        check_action("firmware_restart", "shutdown", False)
    assert e.value.confirm
    assert check_action("firmware_restart", "shutdown", True)[0] == "printer.firmware_restart"
    assert check_action("firmware_restart", "standby", True)[0] == "printer.firmware_restart"


@pytest.fixture
def api(cfg):
    cfg.app_token = "geheim"
    bridge = FakeBridge(cfg)
    sent = []

    async def gcode(script, timeout=15, source="Bridge"):
        sent.append(("gcode", script, source))

    async def action(method, label, source="Bridge", timeout=30):
        sent.append(("action", method, source))
    bridge.moon.gcode, bridge.moon.action = gcode, action

    def call(path, body=None, token="geheim"):
        async def go():
            async with TestClient(TestServer(build_app(bridge))) as client:
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                resp = await client.post(path, json=body or {}, headers=headers)
                return resp.status, await resp.json()
        return asyncio.run(go())
    return bridge, call, sent


def test_routes(api):
    bridge, call, sent = api
    assert call("/api/print/pause", token=None)[0] == 401
    assert call("/api/print/tune", {"speed": 120}, token=None)[0] == 401
    bridge.moon.merge({"print_stats": {"state": "printing"}})
    assert call("/api/print/pause")[0] == 200
    assert bridge.last_control["action"] == "pause"          # die App meldet eigene Pausen nicht als Alarm
    status, res = call("/api/print/cancel")
    assert status == 409 and res["confirm"] is True
    assert call("/api/print/cancel", {"confirm": True})[0] == 200
    assert call("/api/print/tune", {"speed": 120, "fans": {"box": 50}})[0] == 200
    assert call("/api/print/tune", {"nozzle": 280})[0] == 409
    assert call("/api/print/tune", {"speed": 400})[0] == 400
    assert call("/api/print/unbekannt")[0] == 404
    assert [s[:2] for s in sent] == [("action", "printer.print.pause"), ("action", "printer.print.cancel"),
                                     ("gcode", "M220 S120\nSET_FAN_SPEED FAN=box_fan SPEED=0.5")]


def test_firmware_restart_after_shutdown_mid_print(api):
    """Not-Aus mitten im Druck: print_stats sagt noch "printing", Klipper ist aber aus - Neuladen muss gehen."""
    bridge, call, sent = api
    bridge.moon.merge({"print_stats": {"state": "printing"}})
    assert call("/api/print/firmware_restart", {"confirm": True})[0] == 409    # Druck laeuft wirklich
    bridge.moon.klippy_ready = False
    status, res = call("/api/print/firmware_restart")
    assert status == 409 and res["confirm"] is True
    assert call("/api/print/firmware_restart", {"confirm": True})[0] == 200
    assert sent[-1][:2] == ("action", "printer.firmware_restart")
