"""Z offset per filament (filament_z.py): Spoolman field z_offset -> KOBRA_START slot_z."""

from __future__ import annotations

import asyncio

from conftest import FakeMoonraker, FakeSlots, FakeSpoolman, spool

from acebridge.filament_z import FilamentZSync, filament_z


class Moon(FakeMoonraker):
    def __init__(self):
        super().__init__()
        self.sent = []
        self.fail = False

    async def gcode(self, script, timeout=15, source="Bridge"):
        if self.fail:
            raise RuntimeError("Unknown gcode_macro KOBRA_START")
        self.sent.append(script)


class SM(FakeSpoolman):
    def __init__(self, spools, templates):
        super().__init__(spools)
        self._templates = templates

    def templates(self):
        return self._templates


TPL = [{"id": 900, "name": "Vorlage PETG", "material": "PETG", "extra": {"z_offset": "0.02"}}]


def make(cfg):
    spools = [spool(1, 1), spool(2, 2), spool(3, 4)]
    spools[0]["filament"].update(material="PETG", extra={"z_offset": "0.035"})      # own value
    spools[1]["filament"].update(material="PETG", extra={})                         # from the template
    spools[2]["filament"].update(material="PLA", extra={})                          # nothing -> 0
    moon = Moon()
    sm = SM(spools, TPL)
    return FilamentZSync(cfg, moon, sm, FakeSlots(moon, sm)), moon, sm


def test_value_from_filament_then_template():
    assert filament_z({"material": "PETG", "extra": {"z_offset": "-0.01"}}, TPL) == -0.01
    assert filament_z({"material": "PETG", "extra": {}}, TPL) == 0.02
    assert filament_z({"material": "PLA", "extra": {}}, TPL) == 0.0
    assert filament_z({"material": "PETG", "extra": {"z_offset": "2.5"}}, TPL) == 0.0    # typo -> 0
    assert filament_z({"material": "PETG", "extra": {"z_offset": "\"abc\""}}, TPL) == 0.02


def test_pushes_slot_values_once_and_after_restart(cfg):
    zs, moon, sm = make(cfg)
    asyncio.run(zs.tick())
    assert moon.sent == ['SET_GCODE_VARIABLE MACRO=KOBRA_START VARIABLE=slot_z VALUE="[0.035, 0.02, 0.0, 0.0]"']
    asyncio.run(zs.tick())
    assert len(moon.sent) == 1                                     # unchanged
    sm.spools[0]["location"] = "Shelf"                            # spool out
    asyncio.run(zs.tick())
    assert moon.sent[-1].endswith('VALUE="[0.0, 0.02, 0.0, 0.0]"')
    asyncio.run(zs.tick(full=True))                               # Klipper restarted
    assert len(moon.sent) == 3


def test_switch_off_and_missing_macro(cfg):
    zs, moon, _ = make(cfg)
    cfg.filament_z_sync = False
    asyncio.run(zs.tick())
    assert moon.sent == []
    cfg.filament_z_sync = True
    moon.fail = True                                              # printer without KOBRA_START
    asyncio.run(zs.tick())
    moon.fail = False
    asyncio.run(zs.tick())
    assert moon.sent == []                                        # don't retry every 2 s
    moon.klippy_ready = False
    asyncio.run(zs.tick())
    moon.klippy_ready = True
    asyncio.run(zs.tick())
    assert len(moon.sent) == 1                                    # again after a Klipper restart


def test_nothing_is_pushed_before_spoolman_is_loaded(cfg):
    zs, moon, sm = make(cfg)
    sm.connected = False
    asyncio.run(zs.tick())
    assert moon.sent == []
    sm.connected = True
    asyncio.run(zs.tick())
    assert len(moon.sent) == 1


def test_nothing_is_pushed_on_rinkhals(cfg):
    zs, moon, _ = make(cfg)
    moon.platform = "rinkhals"                 # GoKlipper has no KOBRA_START
    asyncio.run(zs.tick())
    assert moon.sent == []
