"""Swappable hotends (nozzle.py, Klipper kobra_nozzle): PID, nozzle and Z correction per hotend.

Switching sends exactly KOBRA_NOZZLE, the PID measurement runs in the background, the view warns about an
uncalibrated hotend, the print start check catches a file for another nozzle (files without G9111 NOZZLE=), the
G-code reader finds Orca's nozzle comment, and the switches appear on the Features page."""

from __future__ import annotations

import asyncio
import types

import pytest
from conftest import FakeMoonraker, FakeSlots, FakeSpoolman, spool

from acebridge import printcheck, switches
from acebridge.nozzle import Hotends, NozzleError
from acebridge.render import parse_bytes

HOTENDS = [{"id": "original", "name": "Original 0.4", "diameter": 0.4, "pid": False, "z": 0.0},
           {"id": "ceramic_02", "name": "Keramik 0.2", "diameter": 0.2, "pid": False, "z": 0.0},
           {"id": "ceramic_06", "name": "Keramik 0.6", "diameter": 0.6, "pid": True, "z": 0.03}]


def kn(active="original", **kw):
    h = next(x for x in HOTENDS if x["id"] == active)
    st = {"enabled": True, "check": True, "active": active, "default": "original", "name": h["name"],
          "diameter": h["diameter"], "z": h["z"], "pid": [22.106, 1.179, 103.622], "measuring": False,
          "pid_source": "measured" if h["pid"] else "config", "result": None, "hotends": HOTENDS}
    st.update(kw)
    return {"kobra_nozzle": st}


class GcodeMoon(FakeMoonraker):
    def __init__(self):
        super().__init__()
        self.sent = []
        self.fail = None

    async def gcode(self, script, timeout=15, source="Bridge"):
        self.sent.append((script, timeout))
        if self.fail:
            raise RuntimeError(self.fail)
        if script.startswith("KOBRA_NOZZLE SELECT="):           # Klipper reports the new hotend
            self.merge(kn(script.split("=", 1)[1].split()[0]))


def hot(**kw):
    moon = GcodeMoon()
    moon.merge({"print_stats": {"state": "standby"}, **kn(**kw)})
    return moon, Hotends(moon)


def test_select_and_switches_send_kobra_nozzle():
    moon, h = hot()
    v = asyncio.run(h.set(hotend="ceramic_06"))
    assert moon.sent[-1] == ("KOBRA_NOZZLE SELECT=ceramic_06", 15) and v["active"] == "ceramic_06"
    asyncio.run(h.set(check=False))
    asyncio.run(h.set(z=0.02))
    asyncio.run(h.set(enabled=False))
    assert [s for s, _ in moon.sent[1:]] == ["KOBRA_NOZZLE CHECK_PRINT=0", "KOBRA_NOZZLE Z=0.020", "KOBRA_NOZZLE ENABLE=0"]


@pytest.mark.parametrize("kw, status", [({"hotend": "nix"}, 404), ({"hotend": "a b; G28"}, 404), ({"z": 0.9}, 400),
                                        ({}, 400)])
def test_bad_requests(kw, status):
    moon, h = hot()
    with pytest.raises(NozzleError) as e:
        asyncio.run(h.set(**kw))
    assert e.value.status == status and moon.sent == []


def test_refused_during_a_print_or_measurement_and_without_module():
    moon, h = hot()
    moon.merge({"print_stats": {"state": "printing"}})
    for kw in ({"hotend": "ceramic_02"}, {"enabled": False}):
        with pytest.raises(NozzleError) as e:
            asyncio.run(h.set(**kw))
        assert e.value.status == 409
    asyncio.run(h.set(check=False))                    # the check switch is fine during a print
    with pytest.raises(NozzleError):
        h.measure_pid()
    moon.merge({"print_stats": {"state": "standby"}, **kn(measuring=True)})
    with pytest.raises(NozzleError) as e:
        asyncio.run(h.set(hotend="ceramic_02"))
    assert e.value.status == 409
    moon.status.pop("kobra_nozzle")
    with pytest.raises(NozzleError) as e:
        asyncio.run(h.set(hotend="original"))
    assert e.value.status == 503


def test_pid_measurement_runs_in_the_background():
    moon, h = hot(active="ceramic_02")

    async def go():
        gate, fast = asyncio.Event(), moon.gcode

        async def slow(script, timeout=15, source="Bridge"):     # the real measurement takes minutes
            moon.sent.append((script, timeout))
            await gate.wait()
        moon.gcode = slow
        v = h.measure_pid(260)
        assert v["measuring"]
        await asyncio.sleep(0)
        assert moon.sent[-1] == ("KOBRA_NOZZLE_PID TEMP=260", 900)
        with pytest.raises(NozzleError):            # one at a time
            h.measure_pid()
        gate.set()
        await h.task
        assert not h.view()["measuring"] and h.error is None
        moon.gcode = fast
        moon.fail = "KOBRA_NOZZLE_PID: Messung abgebrochen"
        h.measure_pid()
        await h.task
    asyncio.run(go())
    assert h.error == "KOBRA_NOZZLE_PID: Messung abgebrochen" and h.view()["error"]
    with pytest.raises(NozzleError) as e:
        h.measure_pid(400)
    assert e.value.status == 400


def test_view_warns_about_an_uncalibrated_hotend_only():
    _, h = hot(active="ceramic_02")
    v = h.view()
    assert v["available"] and v["active"] == "ceramic_02" and v["diameter"] == 0.2 and not v["pid_measured"]
    assert "Keramik 0.2" in v["warning"] and [x["id"] for x in v["hotends"]] == ["original", "ceramic_02", "ceramic_06"]
    assert hot(active="original")[1].view()["warning"] is None       # the default hotend: [extruder] is its PID
    assert hot(active="ceramic_06")[1].view()["warning"] is None     # measured
    assert hot(active="ceramic_02", enabled=False)[1].view()["warning"] is None
    v = hot(active="ceramic_06", result={"id": "ceramic_06", "kp": 30.5, "ki": 2.25, "kd": 103.4, "time": 1.0})[1].view()
    assert v["last"] == {"hotend": "ceramic_06", "ok": True, "time": 1.0, "pid": [30.5, 2.25, 103.4], "error": None}
    empty = Hotends(FakeMoonraker()).view()
    assert empty["available"] is False and empty["pid"] == [] and empty["hotends"] == []


def test_diameter_only_when_on():
    assert hot(active="ceramic_06")[1].diameter() == 0.6
    assert hot(active="ceramic_06", enabled=False)[1].diameter() is None


# ---------------------------------------------------------------- print start check
def bridge_with(moon, nozzle):
    sm = FakeSpoolman([spool(1, 1)])
    model = type("M", (), {"e_total": {0: 500.0}, "types": ["PLA"], "colours": ["FFFFFF"], "nozzle": nozzle,
                           "__len__": lambda self: 1})()
    return types.SimpleNamespace(moon=moon, slots=FakeSlots(moon, sm), hotends=Hotends(moon),
                                 preview=types.SimpleNamespace(model=model, status="ready"),
                                 moisture=types.SimpleNamespace(view=lambda s: {"needs_drying": False}))


def kinds(b):
    return [i["kind"] for i in printcheck.check(b)]


def test_print_check_catches_a_file_for_another_nozzle():
    moon = FakeMoonraker()
    moon.merge({"print_stats": {"state": "printing"}, **kn("ceramic_06")})
    assert "nozzle" in kinds(bridge_with(moon, 0.4))
    text = next(i["text"] for i in printcheck.check(bridge_with(moon, 0.4)) if i["kind"] == "nozzle")
    assert "0.4 mm" in text and "Keramik 0.6 (0.6 mm)" in text
    assert "nozzle" not in kinds(bridge_with(moon, 0.6))                 # fits
    assert "nozzle" not in kinds(bridge_with(moon, None))                # file without the comment
    moon.merge(kn("ceramic_06", check=False))
    assert "nozzle" not in kinds(bridge_with(moon, 0.4))                 # check switched off
    moon.merge(kn("ceramic_06", enabled=False))
    assert "nozzle" not in kinds(bridge_with(moon, 0.4))                 # hotends off


def test_print_guard_pauses_for_the_wrong_nozzle(cfg):
    moon = GcodeMoon()
    moon.merge({"print_stats": {"state": "printing", "filename": "a.gcode"}, **kn("ceramic_06")})
    actions = []

    async def action(method, why, source=""):
        actions.append((method, why))
    moon.action = action
    b = bridge_with(moon, 0.4)
    b.cfg = cfg
    guard = printcheck.PrintGuard(b, clock=lambda: 100.0)
    asyncio.run(guard.tick())
    assert actions and actions[0][0] == "printer.print.pause" and "nozzle" in actions[0][1]


def test_gcode_reader_finds_the_nozzle():
    m = parse_bytes(b"G1 X10 Y10 E1\n; nozzle_diameter = 0.6\n; nozzle_diameter = 0.4\n")
    assert m.nozzle == 0.6                                              # the first one (Orca's config block)
    assert parse_bytes(b"; nozzle_diameter = 0.4,0.4\n").nozzle == 0.4    # one per extruder (PrusaSlicer)
    assert parse_bytes(b"G1 X1 E1\n").nozzle is None


# ---------------------------------------------------------------- switches on the Features page
def test_switches_list_and_commands():
    st = kn("ceramic_06")
    items = {i["key"]: i for i in switches.items(st)}
    assert items["hotends"]["on"] is True and items["nozzle_check"]["on"] is True and items["nozzle_check"]["sensitive"]
    off = {i["key"]: i for i in switches.items(kn("ceramic_06", enabled=False))}
    assert off["nozzle_check"]["sensitive"] is False
    assert switches._commands("hotends")(False) == "KOBRA_NOZZLE ENABLE=0"
    assert switches._commands("nozzle_check")(True) == "KOBRA_NOZZLE CHECK_PRINT=1"
    assert "hotends" not in {i["key"] for i in switches.items({})}
