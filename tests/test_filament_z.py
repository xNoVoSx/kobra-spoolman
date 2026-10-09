"""Z-Versatz pro Filament (filament_z.py): Spoolman-Feld z_offset -> KOBRA_START slot_z."""

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
    spools[0]["filament"].update(material="PETG", extra={"z_offset": "0.035"})      # eigener Wert
    spools[1]["filament"].update(material="PETG", extra={})                         # von der Vorlage
    spools[2]["filament"].update(material="PLA", extra={})                          # nichts -> 0
    moon = Moon()
    sm = SM(spools, TPL)
    return FilamentZSync(cfg, moon, sm, FakeSlots(moon, sm)), moon, sm


def test_value_from_filament_then_template():
    assert filament_z({"material": "PETG", "extra": {"z_offset": "-0.01"}}, TPL) == -0.01
    assert filament_z({"material": "PETG", "extra": {}}, TPL) == 0.02
    assert filament_z({"material": "PLA", "extra": {}}, TPL) == 0.0
    assert filament_z({"material": "PETG", "extra": {"z_offset": "2.5"}}, TPL) == 0.0    # Tippfehler -> 0
    assert filament_z({"material": "PETG", "extra": {"z_offset": "\"abc\""}}, TPL) == 0.02


def test_pushes_slot_values_once_and_after_restart(cfg):
    zs, moon, sm = make(cfg)
    asyncio.run(zs.tick())
    assert moon.sent == ['SET_GCODE_VARIABLE MACRO=KOBRA_START VARIABLE=slot_z VALUE="[0.035, 0.02, 0.0, 0.0]"']
    asyncio.run(zs.tick())
    assert len(moon.sent) == 1                                     # unveraendert
    sm.spools[0]["location"] = "Regal"                            # Spule raus
    asyncio.run(zs.tick())
    assert moon.sent[-1].endswith('VALUE="[0.0, 0.02, 0.0, 0.0]"')
    asyncio.run(zs.tick(full=True))                               # Klipper neu gestartet
    assert len(moon.sent) == 3


def test_switch_off_and_missing_macro(cfg):
    zs, moon, _ = make(cfg)
    cfg.filament_z_sync = False
    asyncio.run(zs.tick())
    assert moon.sent == []
    cfg.filament_z_sync = True
    moon.fail = True                                              # Drucker ohne KOBRA_START
    asyncio.run(zs.tick())
    moon.fail = False
    asyncio.run(zs.tick())
    assert moon.sent == []                                        # nicht alle 2 s erneut versuchen
    moon.klippy_ready = False
    asyncio.run(zs.tick())
    moon.klippy_ready = True
    asyncio.run(zs.tick())
    assert len(moon.sent) == 1                                    # nach Klipper-Neustart wieder


def test_nothing_is_pushed_before_spoolman_is_loaded(cfg):
    zs, moon, sm = make(cfg)
    sm.connected = False
    asyncio.run(zs.tick())
    assert moon.sent == []
    sm.connected = True
    asyncio.run(zs.tick())
    assert len(moon.sent) == 1
