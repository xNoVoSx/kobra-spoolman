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


def petg_spool(spool_id=8, slot=1):
    return {"id": spool_id, "location": f"ACE Slot {slot}",
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


def test_pushes_once_and_only_when_ace_differs(make):
    mgr, moon = make(mmu(["", "PETG"], ["000000FF", "685BC7FF"]), [petg_spool(8, 1), petg_spool(9, 2)])
    asyncio.run(mgr.evaluate())
    assert len(moon.sent) == 1 and parse_map(moon.sent[0])[0]["material"] == "PETG"   # Slot 2 passt schon
    asyncio.run(mgr.evaluate())
    assert len(moon.sent) == 1                                                        # nicht wiederholen
    hints = mgr.slots_view()[0]["hints"]
    assert any("kein Material" in h and "setzt es gleich" in h for h in hints)


def test_no_push_while_printing_or_when_disabled(make):
    mgr, moon = make(mmu([""], state="printing"), [petg_spool()])
    asyncio.run(mgr.evaluate())
    assert moon.sent == []
    mgr, moon = make(mmu([""]), [petg_spool()], enabled=False)
    asyncio.run(mgr.evaluate())
    assert moon.sent == []
    assert any("am Display" in h for h in mgr.slots_view()[0]["hints"])


def test_failed_push_is_retried(make):
    mgr, moon = make(mmu([""]), [petg_spool()])
    moon.fail = True
    asyncio.run(mgr.evaluate())
    moon.fail = False
    asyncio.run(mgr.evaluate())
    assert len(moon.sent) == 1
