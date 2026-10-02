"""RFID automatisch (slots.auto_by_tag): Spule mit eigenem Tag im Slot -> zuordnen, unbekannte Nummer merken."""

from __future__ import annotations

import asyncio

import pytest
from test_slot_info import GcodeMoonraker, SlotSpoolman

from acebridge.slots import SlotManager


class TagSpoolman(SlotSpoolman):
    async def patch_spool(self, spool_id, patch):
        sp = self.spool(spool_id)
        extra = patch.pop("extra", None)
        sp.update(patch)
        if extra:
            sp.setdefault("extra", {}).update(extra)

    async def ensure_field(self, *a):
        return True


def spool(sid, name, tag=None, loc="Regal"):
    return {"id": sid, "location": loc, "extra": {"tag_nr": str(tag)} if tag else {},
            "filament": {"id": sid, "name": name, "material": "PETG", "color_hex": "685bc7", "vendor": {"name": "Sunlu"}}}


def status(tags, present=None, state="standby"):
    n = len(tags)
    return {"mmu": {"num_gates": n, "gate_status": [1 if p else 0 for p in (present or [True] * n)],
                    "gate_material": ["PETG"] * n, "gate_color": ["685BC7FF"] * n, "gate_spool_id": tags},
            "print_stats": {"state": state}}


@pytest.fixture
def make(cfg):
    def _make(st, spools):
        cfg.set_ace_slot_info = False
        cfg.write_lane_data = False
        cfg.gate_debounce_s = 3
        moon = GcodeMoonraker()
        moon.merge(st)
        return SlotManager(cfg, moon, TagSpoolman(spools)), moon
    return _make


def run(coro):
    return asyncio.run(coro)


def settle(sm, t):
    """Tag sehen und nach der Entprellung (3 s) noch einmal - wie zwei Durchlaeufe des Tickers."""
    run(sm.auto_by_tag(now=t))
    run(sm.auto_by_tag(now=t + 5))


def loc(sm, sid):
    return sm.sm.spool(sid)["location"]


def test_already_loaded_tag_is_assigned_at_start_after_debounce(make):
    """Lavendel liegt schon im Slot (Tag schon gelesen): nach dem Bridge-Start ohne Herausnehmen zuordnen."""
    sm, _ = make(status([34532, 0, 102, 0]), [spool(1, "Lavendel", 34532), spool(2, "Magenta")])
    run(sm.auto_by_tag(now=100))
    assert loc(sm, 1) == "Regal"                                  # erst entprellen
    run(sm.auto_by_tag(now=104))
    assert loc(sm, 1) == "ACE Slot 1" and sm.by_tag == {0: 34532}
    assert "Lavendel per RFID erkannt" in sm.tag_events[-1]["text"]
    assert 2 not in sm.by_tag                                    # Anycubic-Sortencode 102 bleibt manuell


def test_new_spool_replaces_old_and_manual_choice_is_kept(make):
    sm, moon = make(status([0, 0]), [spool(1, "Lavendel", 34532), spool(2, "Magenta", 4711, loc="ACE Slot 1")])
    moon.merge({"mmu": {"gate_spool_id": [34532, 0]}})
    settle(sm, 10)
    assert loc(sm, 1) == "ACE Slot 1" and loc(sm, 2) == "Regal"   # alte Spule ins Regal
    run(sm.assign(1, 2))                                           # bewusst von Hand anders
    settle(sm, 30)
    assert loc(sm, 2) == "ACE Slot 1"                              # nicht zurueckgedreht
    moon.merge({"mmu": {"gate_status": [0, 1]}})                  # herausgenommen ...
    run(sm.auto_by_tag(now=50))
    moon.merge({"mmu": {"gate_status": [1, 1]}})                  # ... und wieder eingelegt
    settle(sm, 60)
    assert loc(sm, 1) == "ACE Slot 1"


def test_spool_moves_from_other_slot(make):
    sm, _ = make(status([0, 34532]), [spool(1, "Lavendel", 34532, loc="ACE Slot 1")])
    settle(sm, 0)
    assert loc(sm, 1) == "ACE Slot 2"


def test_unknown_tag_is_learned_on_manual_assignment(make):
    sm, _ = make(status([55555, 0]), [spool(1, "Lavendel"), spool(2, "Magenta", 4711)])
    settle(sm, 0)
    assert sm.unknown_tags == {0: 55555} and loc(sm, 1) == "Regal"
    run(sm.assign(1, 1))
    assert sm.sm.spool(1)["extra"]["tag_nr"] == "55555" and sm.unknown_tags == {}
    assert sm.by_tag == {0: 55555}
    run(sm.assign(1, 2))                                           # Spule mit eigener Nummer: nichts ueberschreiben
    assert sm.sm.spool(2)["extra"]["tag_nr"] == "4711"


def test_works_while_printing(make):
    sm, _ = make(status([34532], state="printing"), [spool(1, "Lavendel", 34532)])
    settle(sm, 0)
    assert loc(sm, 1) == "ACE Slot 1"


def test_can_be_switched_off(make, cfg):
    sm, _ = make(status([34532]), [spool(1, "Lavendel", 34532)])
    cfg.auto_assign_by_tag = False
    settle(sm, 0)
    assert loc(sm, 1) == "Regal"
