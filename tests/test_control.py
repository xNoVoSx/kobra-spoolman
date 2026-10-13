"""Print control (control.py): tune and pause/resume/cancel/emergency stop with confirmations."""

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
    assert tune_commands({"nozzle": 280})[1]                       # hot: confirmation


@pytest.mark.parametrize("body", [{"speed": 5}, {"flow": 200}, {"fans": {"part": 120}}, {"fans": {"turbo": 10}},
                                  {"bed": 130}, {"nozzle": "heiss"}, {}])
def test_tune_rejects_out_of_range(body):
    with pytest.raises(ControlError):
        tune_commands(body)


def test_actions_check_state_and_confirmation():
    assert check_action("pause", "printing", False)[0] == "printer.print.pause"
    with pytest.raises(ControlError):
        check_action("resume", "printing", False)                 # not paused
    with pytest.raises(ControlError) as e:
        check_action("cancel", "printing", False)
    assert e.value.confirm
    assert check_action("cancel", "paused", True)[0] == "printer.print.cancel"
    with pytest.raises(ControlError) as e:
        check_action("emergency_stop", "standby", False)
    assert e.value.confirm and "reload Klipper" in str(e.value)
    assert check_action("emergency_stop", "standby", True)[0] == "printer.emergency_stop"


def test_firmware_restart_only_without_print():
    """Reload Klipper (after an emergency stop or shutdown) - never during a print, always with confirmation."""
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
    assert bridge.last_control["action"] == "pause"          # the app does not report its own pauses as an alarm
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
    """Emergency stop in the middle of a print: print_stats still says "printing" but Klipper is off - reloading must work."""
    bridge, call, sent = api
    bridge.moon.merge({"print_stats": {"state": "printing"}})
    assert call("/api/print/firmware_restart", {"confirm": True})[0] == 409    # the print really runs
    bridge.moon.klippy_ready = False
    status, res = call("/api/print/firmware_restart")
    assert status == 409 and res["confirm"] is True
    assert call("/api/print/firmware_restart", {"confirm": True})[0] == 200
    assert sent[-1][:2] == ("action", "printer.firmware_restart")


def test_rinkhals_never_reloads_klipper():
    """Rinkhals blocks FIRMWARE_RESTART (GoKlipper would hang): refused, with the way out in the message."""
    from acebridge.control import ControlError, check_action
    with pytest.raises(ControlError) as e:
        check_action("firmware_restart", "shutdown", True, platform="rinkhals")
    assert e.value.status == 409 and "off and on" in str(e.value)
    with pytest.raises(ControlError) as e:
        check_action("emergency_stop", "printing", False, platform="rinkhals")
    assert e.value.confirm and "off and on" in str(e.value)
    assert check_action("firmware_restart", "shutdown", True)[0] == "printer.firmware_restart"



def test_slow_firmware_answers_early_and_shows_the_pending_action(api):
    """13.10. Rinkhals: resume took ~50 s (the nozzle heats back up from 140 °C), cancel ~45 s. The app gave up after
    15 s ("bridge not reachable") and still offered "Resume". Now: answer after ANSWER_S with pending, the printer state
    shows the action until the printer is done."""
    from acebridge import control
    from acebridge.appapi import printer_state
    bridge, call, sent = api
    waited = []

    async def slow(method, label, source="Bridge", timeout=30):
        waited.append(timeout)
        sent.append(("action", method, source))
        raise asyncio.TimeoutError
    bridge.moon.action = slow
    bridge.moon.merge({"print_stats": {"state": "paused"}})
    status, res = call("/api/print/resume")
    assert status == 202 and res == {"ok": True, "pending": True}
    assert waited == [control.ANSWER_S] and control.ANSWER_S < 15     # the app's read timeout
    assert bridge.last_control["action"] == "resume"
    p = printer_state(bridge.moon.status, True, True, None, pending=bridge.pending_control)
    assert p["pending_action"] == "resume"                   # still paused: web/app show "Resuming …"
    bridge.moon.merge({"print_stats": {"state": "printing"}})
    assert printer_state(bridge.moon.status, True, True, None, pending=bridge.pending_control)["pending_action"] is None
    # never stuck: forgotten after PENDING_MAX_S even if the printer never got there
    old = {"action": "cancel", "at": 1000.0}
    assert control.pending_action(old, "printing", 1000.0 + 10) == "cancel"
    assert control.pending_action(old, "printing", 1000.0 + control.PENDING_MAX_S + 1) is None
    assert control.pending_action(old, "cancelled", 1010.0) is None
    # an emergency stop that times out is still an error, never "pending"
    bridge.moon.merge({"print_stats": {"state": "printing"}})
    assert call("/api/print/emergency_stop", {"confirm": True})[0] == 503


def test_fast_answer_clears_the_pending_action(api):
    bridge, call, _sent = api
    bridge.pending_control = {"action": "resume", "at": 0.0}
    bridge.moon.merge({"print_stats": {"state": "printing"}})
    status, res = call("/api/print/pause")
    assert status == 200 and res == {"ok": True, "pending": False}
    assert bridge.pending_control is None
