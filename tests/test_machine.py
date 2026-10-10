"""Steuerung am Drucker (machine.py): nur feste Befehle mit Grenzen, im Druck gesperrt, lange Aktionen im Hintergrund."""

from __future__ import annotations

import asyncio

import pytest
from conftest import FakeMoonraker

from acebridge.machine import MachineError, Machine


class Moon(FakeMoonraker):
    def __init__(self):
        super().__init__()
        self.sent = []
        self.fail = None
        self.position = {"position": [120.0, 130.5, 10.0, 0.0], "homed_axes": "xyz"}

    async def gcode(self, script, timeout=15, source="Bridge"):
        self.sent.append(script)
        if self.fail:
            raise RuntimeError(self.fail)

    async def query(self, objects, timeout=5):
        return {"toolhead": dict(self.position)}


@pytest.fixture
def env():
    moon = Moon()
    moon.merge({"print_stats": {"state": "standby"}, "extruder": {"temperature": 240.0}})
    return Machine(moon), moon


def run(coro):
    async def go():
        res = await coro
        for _ in range(3):
            await asyncio.sleep(0)
        return res
    return asyncio.run(go())


def test_view(env):
    m, _ = env
    v = run(m.view())
    assert v["position"] == [120.0, 130.5, 10.0] and v["homed"] == "xyz" and v["move_allowed"]
    assert v["macros"][0]["key"] == "bed_mesh_all" and v["steps"] == [0.1, 1.0, 10.0, 50.0]


def test_allowed_commands(env):
    m, moon = env
    run(m.run("jog", {"axis": "x", "dist": -10}, "Display"))
    run(m.run("jog", {"axis": "z", "dist": 0.1}, "Display"))
    run(m.run("motors_off", {}, "Display"))
    run(m.run("extrude", {"mm": 10}, "Display"))
    run(m.run("home", {"axes": "xy"}, "Display"))
    run(m.run("load", {"slot": 2}, "Display"))
    run(m.run("unload", {}, "Display"))
    run(m.run("macro", {"key": "bed_mesh_all", "confirm": True}, "Display"))
    assert moon.sent == ["G91\nG1 X-10 F6000\nG90", "G91\nG1 Z0.1 F600\nG90", "M84", "M83\nG1 E10 F300", "G28 X Y",
                         "T1", "ACE_SMART_UNLOAD", "KOBRA_BED_MESH_ALL"]


@pytest.mark.parametrize("action,body,status", [
    ("jog", {"axis": "x", "dist": 7}, 400), ("jog", {"axis": "e", "dist": 1}, 400), ("jog", {"axis": "z", "dist": 50}, 400),
    ("jog", {"axis": "x", "dist": True}, 400), ("load", {"slot": 5}, 400), ("load", {"slot": "1"}, 400),
    ("extrude", {"mm": 200}, 400), ("home", {"axes": "e"}, 400), ("macro", {"key": "SAVE_CONFIG"}, 404),
    ("gcode", {"script": "M104 S300"}, 404)])
def test_rejects(env, action, body, status):
    m, moon = env
    with pytest.raises(MachineError) as e:
        run(m.run(action, body, "Display"))
    assert e.value.status == status and moon.sent == []


def test_guards(env):
    m, moon = env
    with pytest.raises(MachineError) as e:                 # Makro nur mit Rueckfrage
        run(m.run("macro", {"key": "bed_mesh_all"}, "Display"))
    assert e.value.status == 409 and e.value.confirm
    moon.position["homed_axes"] = "xy"
    with pytest.raises(MachineError) as e:                 # Z nicht gehomt
        run(m.run("jog", {"axis": "z", "dist": 1}, "Display"))
    assert "homen" in str(e.value)
    moon.merge({"extruder": {"temperature": 25.0}})
    with pytest.raises(MachineError) as e:                 # kalt
        run(m.run("extrude", {"mm": 10}, "Display"))
    assert "kalt" in str(e.value)
    moon.merge({"print_stats": {"state": "printing"}, "extruder": {"temperature": 240.0}})
    for action, body in (("home", {}), ("jog", {"axis": "x", "dist": 1}), ("load", {"slot": 1}), ("extrude", {"mm": 5})):
        with pytest.raises(MachineError) as e:
            run(m.run(action, body, "Display"))
        assert e.value.status == 409
    moon.merge({"print_stats": {"state": "paused"}})
    run(m.run("extrude", {"mm": 5}, "Display"))            # in der Pause freispuelen erlaubt
    assert moon.sent == ["M83\nG1 E5 F300"]
    moon.klippy_ready = False
    with pytest.raises(MachineError) as e:
        run(m.run("motors_off", {}, "Display"))
    assert e.value.status == 503


def test_long_actions_in_background_and_errors(env):
    m, moon = env
    moon.fail = "Must home axis first"
    res = run(m.run("load", {"slot": 1}, "Display"))
    assert res["started"] and m.running is None and m.error == "Must home axis first"
    with pytest.raises(MachineError) as e:                 # kurze Aktion: Fehler direkt
        run(m.run("motors_off", {}, "Display"))
    assert e.value.status == 400


def test_zadjust_exclude_and_save(env):
    from types import SimpleNamespace
    m, moon = env
    saved = []

    async def patch(fid, data):
        saved.append((fid, data))
    fil = {"id": 8, "name": "PETG Lavendel", "extra": {"z_offset": "0.02"}}
    m.sm = SimpleNamespace(templates=lambda: [], patch_filament=patch)
    m.slots = SimpleNamespace(assignments=lambda: ({1: {"filament": fil}}, []))
    moon.merge({"print_stats": {"state": "printing"}, "ace": {"current_index": 0}})
    run(m.view())                                            # Druck beginnt: Summe 0
    run(m.run("zadjust", {"delta": 0.025}, "Display"))
    run(m.run("zadjust", {"delta": -0.01}, "Display"))
    assert moon.sent[-2:] == ["SET_GCODE_OFFSET Z_ADJUST=+0.025 MOVE=1", "SET_GCODE_OFFSET Z_ADJUST=-0.010 MOVE=1"]
    assert m.z_session == 0.015
    with pytest.raises(MachineError):
        run(m.run("zadjust", {"delta": 0.5}, "Display"))
    res = run(m.save_z())
    assert res["new"] == 0.035 and saved == [(8, {"extra": {"z_offset": "0.035"}})] and m.z_session == 0
    with pytest.raises(MachineError):                        # nichts mehr nachgestellt
        run(m.save_z())
    with pytest.raises(MachineError) as e:                   # Objekt nur mit Rueckfrage
        run(m.run("exclude", {"name": "Teil_2"}, "Display"))
    assert e.value.confirm
    run(m.run("exclude", {"name": "Teil_2", "confirm": True}, "Display"))
    assert moon.sent[-1] == "EXCLUDE_OBJECT NAME=Teil_2"
    for bad in ("Teil 2", "A;M104 S300", ""):
        with pytest.raises(MachineError):
            run(m.run("exclude", {"name": bad, "confirm": True}, "Display"))
