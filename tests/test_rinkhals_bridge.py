"""Bridge parts on a Rinkhals printer: slot data via MMU_GATE_MAP, dryer via MMU_DRYER_*, the print check through the
ACE's ttg_map, the remaining-amount forecast with the firmware purge, the printer card's change text."""

from __future__ import annotations

import ast
import asyncio
import shlex
from types import SimpleNamespace

from conftest import FakeMoonraker
from test_acemodel_rinkhals import rinkhals_status
from test_slot_info import SlotSpoolman, petg_spool

from acebridge.appapi import printer_state
from acebridge.dryer import Dryer
from acebridge.slots import SlotManager


class Moon(FakeMoonraker):
    def __init__(self):
        super().__init__()
        self.sent, self.db = [], {}
        self.components = ["kobra", "mmu_ace"]

    @property
    def platform(self):
        return "rinkhals"

    async def gcode(self, script, source="Bridge"):
        self.sent.append(script)

    async def db_post(self, ns, key, value):
        self.db[key] = value

    async def db_delete(self, ns, key):
        self.db.pop(key, None)

    async def db_keys(self, ns):
        return list(self.db)


def run(c):
    return asyncio.run(c)


def no_material_status():
    return rinkhals_status(gate_material=["", "PLA", "Unknown", "PLA Silk"], gate_status=[1, -1, 0, 1])


def test_slot_without_material_warns_and_assignment_sends_mmu_gate_map(cfg):
    moon = Moon()
    moon.merge(no_material_status())
    mgr = SlotManager(cfg, moon, SlotSpoolman([petg_spool(8, 1)]))
    run(mgr.evaluate())
    hint = mgr.slots_view()[0]["hints"]
    assert any("gets cancelled" in h for h in hint) and moon.sent == []
    run(mgr.assign(1, 8))
    assert len(moon.sent) == 1
    name, arg = shlex.split(moon.sent[0])
    entry = ast.literal_eval(arg[4:])[0]
    assert name == "MMU_GATE_MAP" and entry["material"] == "PETG" and entry["color"] == "685BC7FF"
    assert entry["spool_id"] == 8


def test_tagged_slot_is_never_overwritten(cfg):
    moon = Moon()
    st = no_material_status()
    st["mmu"]["gate_material"][3] = ""
    moon.merge(st)
    spool = petg_spool(8, 4)
    mgr = SlotManager(cfg, moon, SlotSpoolman([spool]))
    run(mgr.assign(4, 8))
    assert moon.sent == []                     # slot 4 has an Anycubic tag (rfid 2)


class SM:
    spools: list = []

    def templates(self):
        return []


def test_dryer_commands_on_rinkhals(cfg):
    moon = Moon()
    moon.merge(rinkhals_status())
    d = Dryer(cfg, moon, SlotManager(cfg, moon, SM()))
    assert d.state()["humidity"] == 24 and d.state()["drying"]
    run(d.stop())
    run(d.start(50, 2.0))
    assert moon.sent == ["MMU_DRYER_STOP UNIT=0", "MMU_DRYER_START UNIT=0 DURATION=120 TEMP=50"]


def test_printer_card_change_text_and_restart():
    st = rinkhals_status(action="Loading")
    st["print_stats"] = {"state": "printing", "filename": "a.gcode"}
    p = printer_state(st, True, True, 1, platform="rinkhals")
    assert p["changing_filament"] and p["mmu_action"] == "Loading"
    assert p["platform"] == "rinkhals" and p["can_restart"] is False
    assert printer_state(st, True, True, 1)["can_restart"] is True


def test_print_check_uses_the_tool_map(cfg):
    from acebridge.printcheck import check

    class Model(SimpleNamespace):
        def __len__(self):
            return 1
    moon = Moon()
    st = rinkhals_status(ttg_map=[3, 1, 2, 0])
    st["print_stats"] = {"state": "printing", "filename": "part.gcode"}
    moon.merge(st)
    model = Model(e_total={0: 500.0}, types=["PLA"], colours=["52D2BC"])
    bridge = SimpleNamespace(moon=moon, cfg=cfg, preview=SimpleNamespace(model=model, status="ready",
                                                                      file="part.gcode"),
                             slots=SimpleNamespace(assignments=lambda: ({}, []),
                                                   ace_gate=lambda g: SlotManager(cfg, moon, SM()).ace_gate(g)),
                             sm=SimpleNamespace(templates=lambda: []), moisture=None)
    out = check(bridge)
    assert out and all(p["slot"] == 4 for p in out)       # T0 -> slot 4 by the ttg_map
