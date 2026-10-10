"""Schalter der Klipper-Module (switches.py): Stand aus dem Abo, nur Befehle aus der festen Liste."""

from __future__ import annotations

import asyncio

import pytest
from conftest import FakeMoonraker

from acebridge.switches import SwitchError, Switches

STATUS = {
    "kobra_pa": {"enabled": True, "auto": False},
    "save_variables": {"variables": {"kobra_use_filament_z": 0}},
    "gcode_macro KOBRA_START": {"use_filament_z": True},
    "ace": {"endless_spool_enabled": True, "endless_spool_match_mode": "material"},
    "kobra_resume": {"enabled": True, "pending": None},
    "kobra_clog": {"enabled": True, "action": "warn", "available": True},
    "kobra_io": {"sound": True, "light_auto": True, "light": False, "available": True,
                 "events": {"done": True, "error": True, "clog": False, "change": True, "prompt": True}},
}


class Moon(FakeMoonraker):
    def __init__(self):
        super().__init__()
        self.sent = []

    async def gcode(self, script, timeout=15, source="Bridge"):
        self.sent.append(script)


@pytest.fixture
def env():
    moon = Moon()
    moon.merge({k: dict(v) for k, v in STATUS.items()})
    return Switches(moon), moon


def test_view_lists_everything_with_state(env):
    sw, _ = env
    v = sw.view()
    items = {i["key"]: i for i in v["items"]}
    assert [g["key"] for g in v["groups"]] == ["print", "watch", "io"]
    assert items["pa"]["on"] and not items["pa_auto"]["on"] and items["pa_auto"]["sensitive"]
    assert items["filament_z"]["on"] is False                   # gespeicherter Schalter gewinnt
    assert items["endless_mode"]["current"] == "material" and items["endless_mode"]["kind"] == "choice"
    assert items["clog_action"]["current"] == "warn"
    assert not items["sound_clog"]["on"] and items["light"]["group"] == "io"
    assert "cmd" not in str(v)                                  # Befehle bleiben in der Bridge


def test_set_sends_only_listed_commands(env):
    sw, moon = env
    for key, value in (("pa", False), ("pa_auto", True), ("filament_z", True), ("endless", False),
                       ("endless_mode", "next"), ("powerloss", False), ("clog", True), ("clog_action", "pause"),
                       ("light", True), ("light_auto", False), ("sound", False), ("sound_done", False)):
        asyncio.run(sw.set(key, value))
    assert moon.sent == ["KOBRA_PA ENABLE=0", "KOBRA_PA AUTO=1", "KOBRA_FILAMENT_Z ENABLE=1",
                         "ACE_DISABLE_ENDLESS_SPOOL", "ACE_SET_ENDLESS_SPOOL_MODE MODE=next", "KOBRA_POWERLOSS ENABLE=0",
                         "KOBRA_CLOG ENABLE=1", "KOBRA_CLOG ACTION=pause", "KOBRA_IO LIGHT=1", "KOBRA_IO LIGHT_AUTO=0",
                         "KOBRA_IO SOUND=0", "KOBRA_IO EVENT=done ON=0"]


@pytest.mark.parametrize("key,value,status", [
    ("pa", "ja", 400), ("clog_action", "explode", 400), ("endless_mode", "M104 S300", 400),
    ("FIRMWARE_RESTART", True, 404), ("pa", 1, 400)])
def test_rejects_bad_requests(env, key, value, status):
    sw, moon = env
    with pytest.raises(SwitchError) as e:
        asyncio.run(sw.set(key, value))
    assert e.value.status == status and moon.sent == []


def test_locked_and_missing(env):
    sw, moon = env
    moon.merge({"kobra_pa": {"enabled": False}})
    with pytest.raises(SwitchError) as e:
        asyncio.run(sw.set("pa_auto", True))
    assert e.value.status == 409
    moon.status.pop("kobra_io")
    assert "light" not in {i["key"] for i in sw.view()["items"]}
    with pytest.raises(SwitchError) as e:
        asyncio.run(sw.set("light", True))
    assert e.value.status == 404
    moon.klippy_ready = False
    assert sw.view()["items"] == []
    with pytest.raises(SwitchError) as e:
        asyncio.run(sw.set("pa", True))
    assert e.value.status == 503 and moon.sent == []


def test_debug_switch(env):
    sw, moon = env
    moon.merge({"kobra_debug": {"enabled": True}})
    items = {i["key"]: i for i in sw.view()["items"]}
    assert items["debug"]["on"] and items["debug"]["group"] == "watch"
    asyncio.run(sw.set("debug", False))
    assert moon.sent[-1] == "KOBRA_DEBUG ENABLE=0"
