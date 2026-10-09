"""Slots ohne Material an der ACE: Hinweis und ACE_SET_SLOT (ACEPRO)."""

from __future__ import annotations

import asyncio

import pytest
from conftest import FakeMoonraker, ace_status

from acebridge.slots import SlotManager, gate_has_tag, gate_needs_info, set_slot_command


class GcodeMoonraker(FakeMoonraker):
    def __init__(self):
        super().__init__()
        self.sent = []
        self.fail = False
        self.db = {}

    async def gcode(self, script, source="Bridge"):
        if self.fail:
            raise ConnectionError("weg")
        self.sent.append(script)

        self.db = {}

    async def db_post(self, ns, key, value):
        self.db[key] = value

    async def db_delete(self, ns, key):
        self.db.pop(key, None)

    async def db_keys(self, ns):
        return list(self.db)


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


def ace(materials, colors=None, present=None, state="standby", tags=None):
    """ACEPRO-Status: je Slot Material/Farbe ("RRGGBB"), present=False = leer, tags = SKU (Spule mit Tag)."""
    slots = []
    for i, m in enumerate(materials):
        if present is not None and not present[i]:
            slots.append(None)
            continue
        sp = {"material": m, "color": (colors or ["000000"] * len(materials))[i]}
        if tags and tags[i]:
            sp["sku"] = tags[i]
        slots.append(sp)
    st = ace_status(slots)
    st["print_stats"] = {"state": state}
    return st


@pytest.fixture
def make(cfg):
    def _make(status, spools, enabled=True):
        cfg.set_ace_slot_info = enabled
        cfg.write_lane_data = False
        moon = GcodeMoonraker()
        moon.merge(status)
        return SlotManager(cfg, moon, SlotSpoolman(spools)), moon
    return _make


def test_set_slot_command():
    info = {"material": "PETG", "color": "685BC7", "display_name": "Sunlu PETG", "nozzle_temp": 245}
    assert set_slot_command(0, info) == "ACE_SET_SLOT T=0 MATERIAL=PETG COLOR=104,91,199 TEMP=245"
    assert set_slot_command(1, {"material": "", "color": "FFFFFF", "nozzle_temp": 210}) is None
    assert set_slot_command(2, {"material": "PLA Silk", "nozzle_temp": 210}).startswith("ACE_SET_SLOT T=2 MATERIAL=PLA ")
    assert "COLOR=255,255,255" in set_slot_command(3, {"material": "PLA", "nozzle_temp": 210})
    assert set_slot_command(0, {"material": "PETG", "color": "685BC7"}) is None      # ACEPRO braucht TEMP


def test_needs_info_only_for_loaded_slots_without_material():
    assert gate_needs_info({"present": True, "material": ""})
    assert not gate_needs_info({"present": True, "material": "PETG"})
    assert not gate_needs_info({"present": False, "material": ""})
    assert gate_has_tag({"rfid": True}) and not gate_has_tag({"rfid": False}) and not gate_has_tag({})


def run(coro):
    return asyncio.run(coro)


def test_only_the_assignment_writes_to_the_ace(make):
    # Spule liegt schon in Slot 1, ACE kennt kein Material: Auswerten allein schreibt nichts
    mgr, moon = make(ace([""]), [petg_spool(8, 1)])
    run(mgr.evaluate())
    assert moon.sent == []
    assert any("neu zuordnen" in h for h in mgr.slots_view()[0]["hints"])
    run(mgr.assign(1, 8))                     # erneut zuordnen -> einmal schreiben
    assert moon.sent == ["ACE_SET_SLOT T=0 MATERIAL=PETG COLOR=104,91,199 TEMP=245"]
    run(mgr.evaluate())
    assert len(moon.sent) == 1


def test_assignment_before_loading_waits_for_the_spool(make):
    mgr, moon = make(ace([""], present=[False]), [petg_spool(8)])
    run(mgr.assign(1, 8))
    assert moon.sent == []
    assert any("sobald die Spule eingelegt" in h for h in mgr.slots_view()[0]["hints"])
    moon.merge(ace([""]))
    run(mgr.evaluate())
    assert len(moon.sent) == 1


def test_waits_for_the_end_of_a_print(make):
    mgr, moon = make(ace([""], state="printing"), [petg_spool(8)])
    run(mgr.assign(1, 8))
    assert moon.sent == []
    moon.merge({"print_stats": {"state": "complete"}})
    run(mgr.evaluate())
    assert len(moon.sent) == 1


def test_nothing_sent_when_ace_already_has_these_values_or_disabled(make):
    mgr, moon = make(ace(["PETG"], ["685BC7"]), [petg_spool(8)])
    run(mgr.assign(1, 8))
    assert moon.sent == []
    mgr, moon = make(ace([""]), [petg_spool(8)], enabled=False)
    run(mgr.assign(1, 8))
    assert moon.sent == []
    assert any("kennt kein Material" in h for h in mgr.slots_view()[0]["hints"])


def test_reassigning_the_slot_cancels_a_waiting_write(make):
    mgr, moon = make(ace([""], present=[False]), [petg_spool(8), petg_spool(9)])
    run(mgr.assign(1, 8))
    run(mgr.assign(1, None))
    moon.merge(ace([""]))
    run(mgr.evaluate())
    assert moon.sent == []


def test_failed_write_is_retried_three_times(make):
    mgr, moon = make(ace([""]), [petg_spool(8)])
    moon.fail = True
    run(mgr.assign(1, 8))
    run(mgr.evaluate())
    run(mgr.evaluate())
    run(mgr.evaluate())
    moon.fail = False
    run(mgr.evaluate())
    assert moon.sent == []                    # nach drei Fehlversuchen aufgegeben


def test_slots_with_rfid_tag_are_never_written(make):
    mgr, moon = make(ace(["PLA"], ["212721"], tags=["AHPEBK-4711"]), [petg_spool(8)])
    run(mgr.assign(1, 8))                     # Spoolman sagt PETG Lavendel, der Tag PLA Schwarz
    assert moon.sent == [] and not mgr._gate_info_pending
    assert any("ACE meldet PLA" in h for h in mgr.slots_view()[0]["hints"])


def test_foreign_lane_data_is_removed_after_each_reconnect(make):
    """ACEPROs eigener Sync schrieb lane1..lane4 (ohne filament_id) - Orca saehe jeden Slot doppelt."""
    sm, moon = make(ace(["PETG", "", "", ""], ["685BC7", "", "", ""], present=[True, False, False, False]),
                    [petg_spool(8, 1)])
    sm.cfg.write_lane_data = True
    moon.db.update({"lane1": {"lane": "0", "material": "PETG"}, "lane4": {"lane": "3"}})
    run(sm.evaluate())
    assert set(moon.db) == {"0"} and moon.db["0"]["filament_id"]
    moon.db["lane2"] = {"lane": "1"}            # kommt erst nach dem Abgleich wieder: bleibt bis zum naechsten
    run(sm.evaluate())
    assert "lane2" in moon.db
    sm.reset_lane_cache()                        # Klipper/Moonraker neu verbunden
    run(sm.evaluate())
    assert set(moon.db) == {"0"}

