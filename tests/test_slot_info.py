"""Slots ohne Material am Drucker: Hinweis und MMU_GATE_MAP an Rinkhals."""

from __future__ import annotations

import ast
import asyncio
import shlex

import pytest
from conftest import FakeMoonraker

from acebridge.slots import SlotManager, gate_map_command, gate_needs_info


class GcodeMoonraker(FakeMoonraker):
    def __init__(self):
        super().__init__()
        self.sent = []
        self.fail = False

    async def gcode(self, script):
        if self.fail:
            raise ConnectionError("weg")
        self.sent.append(script)

    async def db_post(self, *a):
        pass

    async def db_delete(self, *a):
        pass


class SlotSpoolman:
    def __init__(self, spools):
        self.spools = spools

    def templates(self):
        return []

    async def refresh(self):
        return True

    def spool(self, spool_id):
        return next((s for s in self.spools if s["id"] == spool_id), None)

    def is_template(self, fil):
        return False

    async def patch_spool(self, spool_id, patch):
        self.spool(spool_id).update(patch)


def petg_spool(spool_id=8, slot=None):
    return {"id": spool_id, "location": f"ACE Slot {slot}" if slot else "Regal",
            "filament": {"id": 20, "name": "PETG \"Lavendel\" {neu}", "material": "PETG", "color_hex": "685bc7",
                         "vendor": {"name": "Sunlu"}, "settings_extruder_temp": 245}}


def mmu(materials, colors=None, status=None, state="standby"):
    n = len(materials)
    return {"mmu": {"num_gates": n, "gate_status": status or [1] * n, "gate_material": materials,
                    "gate_color": colors or ["000000FF"] * n},
            "print_stats": {"state": state}}


@pytest.fixture
def make(cfg):
    def _make(status, spools, enabled=True):
        cfg.set_ace_slot_info = enabled
        cfg.write_lane_data = False
        moon = GcodeMoonraker()
        moon.merge(status)
        return SlotManager(cfg, moon, SlotSpoolman(spools)), moon
    return _make


def parse_map(cmd):
    """So wie Rinkhals: shlex-Teile, MAP=... per ast.literal_eval."""
    parts = shlex.split(cmd)
    assert parts[0] == "MMU_GATE_MAP" and parts[1].startswith("MAP=")
    return ast.literal_eval(parts[1][len("MAP="):])


def test_gate_map_command_is_readable_by_rinkhals():
    info = {"material": "PETG", "color": "685BC7", "display_name": "Sunlu PETG \"Lav'endel\" {x}: a=b",
            "nozzle_temp": 245}
    m = parse_map(gate_map_command(0, 8, info))
    assert m == {0: {"status": 1, "name": "Sunlu PETG Lav endel x a b", "material": "PETG",
                     "color": "685BC7FF", "temp": 245, "spool_id": 8, "speed_override": 100}}
    assert gate_map_command(1, 8, {"material": "", "color": "FFFFFF"}) is None
    assert parse_map(gate_map_command(2, 3, {"material": "PLA Silk"}))[2]["material"] == "PLA"


def test_needs_info_only_for_loaded_slots_without_material():
    assert gate_needs_info({"present": True, "material": ""})
    assert not gate_needs_info({"present": True, "material": "PETG"})
    assert not gate_needs_info({"present": False, "material": ""})


def run(coro):
    return asyncio.run(coro)


def test_only_the_assignment_writes_to_the_ace(make):
    # Spule liegt schon in Slot 1, ACE kennt kein Material: Auswerten allein schreibt nichts
    mgr, moon = make(mmu([""]), [petg_spool(8, 1)])
    run(mgr.evaluate())
    assert moon.sent == []
    assert any("neu zuordnen" in h for h in mgr.slots_view()[0]["hints"])
    run(mgr.assign(1, 8))                     # erneut zuordnen -> einmal schreiben
    assert len(moon.sent) == 1 and parse_map(moon.sent[0])[0]["color"] == "685BC7FF"
    run(mgr.evaluate())
    assert len(moon.sent) == 1


def test_assignment_before_loading_waits_for_the_spool(make):
    mgr, moon = make(mmu([""], status=[0]), [petg_spool(8)])
    run(mgr.assign(1, 8))
    assert moon.sent == []
    assert any("sobald die Spule eingelegt" in h for h in mgr.slots_view()[0]["hints"])
    moon.merge({"mmu": {"gate_status": [1]}})
    run(mgr.evaluate())
    assert len(moon.sent) == 1


def test_waits_for_the_end_of_a_print(make):
    mgr, moon = make(mmu([""], state="printing"), [petg_spool(8)])
    run(mgr.assign(1, 8))
    assert moon.sent == []
    moon.merge({"print_stats": {"state": "complete"}})
    run(mgr.evaluate())
    assert len(moon.sent) == 1


def test_nothing_sent_when_ace_already_has_these_values_or_disabled(make):
    mgr, moon = make(mmu(["PETG"], ["685BC7FF"]), [petg_spool(8)])
    run(mgr.assign(1, 8))
    assert moon.sent == []
    mgr, moon = make(mmu([""]), [petg_spool(8)], enabled=False)
    run(mgr.assign(1, 8))
    assert moon.sent == []
    assert any("am Display" in h for h in mgr.slots_view()[0]["hints"])


def test_reassigning_the_slot_cancels_a_waiting_write(make):
    mgr, moon = make(mmu([""], status=[0]), [petg_spool(8), petg_spool(9)])
    run(mgr.assign(1, 8))
    run(mgr.assign(1, None))
    moon.merge({"mmu": {"gate_status": [1]}})
    run(mgr.evaluate())
    assert moon.sent == []


def test_failed_write_is_retried_three_times(make):
    mgr, moon = make(mmu([""]), [petg_spool(8)])
    moon.fail = True
    run(mgr.assign(1, 8))
    run(mgr.evaluate())
    run(mgr.evaluate())
    run(mgr.evaluate())
    moon.fail = False
    run(mgr.evaluate())
    assert moon.sent == []                    # nach drei Fehlversuchen aufgegeben
