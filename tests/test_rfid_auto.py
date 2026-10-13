"""RFID automatic (slots.auto_by_tag): spool with an own tag in the slot -> assign, remember an unknown number."""

from __future__ import annotations

import asyncio

import pytest
from conftest import ace_status
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


def spool(sid, name, tag=None, loc="Shelf"):
    return {"id": sid, "location": loc, "extra": {"tag_nr": str(tag)} if tag else {},
            "filament": {"id": sid, "name": name, "material": "PETG", "color_hex": "685bc7", "vendor": {"name": "Sunlu"}}}


def status(tags, present=None, state="standby"):
    """ACEPRO state: tag number per slot (0 = spool without a tag), present=False = empty."""
    n = len(tags)
    slots = [None if not p else {"material": "PETG", "color": "685BC7", **({"sku": f"AHPEBK-{t}"} if t else {})}
             for t, p in zip(tags, present or [True] * n)]
    st = ace_status(slots)
    st["print_stats"] = {"state": state}
    return st


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
    """See the tag and after the debounce (3 s) once more - like two runs of the ticker."""
    run(sm.auto_by_tag(now=t))
    run(sm.auto_by_tag(now=t + 5))


def loc(sm, sid):
    return sm.sm.spool(sid)["location"]


def test_already_loaded_tag_is_assigned_at_start_after_debounce(make):
    """Lavender is already in the slot (tag already read): assign after the bridge start without taking it out."""
    sm, _ = make(status([34532, 0, 102, 0]), [spool(1, "Lavendel", 34532), spool(2, "Magenta")])
    run(sm.auto_by_tag(now=100))
    assert loc(sm, 1) == "Shelf"                                  # debounce first
    run(sm.auto_by_tag(now=104))
    assert loc(sm, 1) == "ACE Slot 1" and sm.by_tag == {0: 34532}
    assert any("Lavendel recognised by RFID" in e["text"] for e in sm.tag_events)
    assert 2 not in sm.by_tag                                    # Anycubic product code 102 is no number of ours
    assert loc(sm, 2) == "ACE Slot 3"                            # ... but the only fitting spool (by kind)


def test_new_spool_replaces_old_and_manual_choice_is_kept(make):
    sm, moon = make(status([0, 0]), [spool(1, "Lavendel", 34532), spool(2, "Magenta", 4711, loc="ACE Slot 1")])
    moon.merge(status([34532, 0]))
    settle(sm, 10)
    assert loc(sm, 1) == "ACE Slot 1" and loc(sm, 2) == "Shelf"   # old spool to the shelf
    run(sm.assign(1, 2))                                           # bewusst von Hand anders
    settle(sm, 30)
    assert loc(sm, 2) == "ACE Slot 1"                              # not turned back
    moon.merge(status([34532, 0], present=[False, True]))        # herausgenommen ...
    run(sm.auto_by_tag(now=50))
    moon.merge(status([34532, 0]))                                # ... and inserted again
    settle(sm, 60)
    assert loc(sm, 1) == "ACE Slot 1"


def test_spool_moves_from_other_slot(make):
    sm, _ = make(status([0, 34532]), [spool(1, "Lavendel", 34532, loc="ACE Slot 1")])
    settle(sm, 0)
    assert loc(sm, 1) == "ACE Slot 2"


def test_unknown_tag_is_learned_on_manual_assignment(make):
    sm, _ = make(status([55555, 0]), [spool(1, "Lavendel"), spool(2, "Magenta", 4711)])
    settle(sm, 0)
    assert sm.unknown_tags == {0: 55555} and loc(sm, 1) == "Shelf"
    run(sm.assign(1, 1))
    assert sm.sm.spool(1)["extra"]["tag_nr"] == "55555" and sm.unknown_tags == {}
    assert sm.by_tag == {0: 55555}
    run(sm.assign(1, 2))                                           # spool with an own number: overwrite nothing
    assert sm.sm.spool(2)["extra"]["tag_nr"] == "4711"


def test_works_while_printing(make):
    sm, _ = make(status([34532], state="printing"), [spool(1, "Lavendel", 34532)])
    settle(sm, 0)
    assert loc(sm, 1) == "ACE Slot 1"


def test_can_be_switched_off(make, cfg):
    sm, _ = make(status([34532]), [spool(1, "Lavendel", 34532)])
    cfg.auto_assign_by_tag = False
    settle(sm, 0)
    assert loc(sm, 1) == "Shelf"


def test_waits_for_spoolman_and_rechecks_unknown_numbers(make):
    """At start Spoolman may not be loaded yet: no premature "unknown"; and an unknown number is assigned as soon as
    a spool has it (happened on the real printer with the update to 2.14.0)."""
    lav = spool(1, "Lavendel", 34532)
    sm, _ = make(status([34532]), [])
    settle(sm, 0)
    assert sm.unknown_tags == {} and sm.tag_events == []          # without a spool list: decide nothing
    sm.sm.spools.append(spool(9, "Andere"))
    settle(sm, 10)
    assert sm.unknown_tags == {0: 34532}                          # Liste da, Nummer wirklich unbekannt
    sm.sm.spools.append(lav)                                      # now a spool has the number
    run(sm.auto_by_tag(now=20))
    assert loc(sm, 1) == "ACE Slot 1" and sm.unknown_tags == {}


def kind_spool(sid, name, color, loc="Shelf", vendor="Anycubic", material="PETG"):
    return {"id": sid, "location": loc, "extra": {},
            "filament": {"id": sid, "name": name, "material": material, "color_hex": color, "vendor": {"name": vendor}}}


def anycubic(color="212721", present=True):
    """Slot 1 with an original Anycubic tag (product code 102 = PETG black), as seen on the printer 13.10."""
    return ace_status([{"material": "PETG", "color": color, "sku": "AHPEBK-102", "brand": "Anycubic"} if present else None])


def test_anycubic_tag_assigns_the_only_fitting_spool(make):
    sm, moon = make(anycubic(), [kind_spool(5, "Anycubic PETG Schwarz", "212721"),
                                 kind_spool(6, "Anycubic PETG Weiss", "F2F2F2"),
                                 kind_spool(7, "Sunlu PETG Schwarz", "212721", vendor="Sunlu"),
                                 kind_spool(8, "Anycubic PLA Schwarz", "212721", material="PLA")])
    settle(sm, 10)
    assert loc(sm, 5) == "ACE Slot 1" and "Anycubic tag" in sm.tag_events[-1]["text"]
    run(sm.assign(1, 6))                                          # changed by hand: stays
    settle(sm, 30)
    assert loc(sm, 6) == "ACE Slot 1"
    moon.merge(anycubic(present=False))                            # taken out and inserted again
    run(sm.auto_by_tag(now=50))
    moon.merge(anycubic())
    settle(sm, 60)
    assert loc(sm, 5) == "ACE Slot 1" and loc(sm, 6) == "Shelf"


def test_anycubic_tag_with_several_fitting_spools_only_notes(make):
    sm, _ = make(anycubic(), [kind_spool(5, "Anycubic PETG Schwarz", "212721"),
                              kind_spool(9, "Anycubic PETG Schwarz", "202620")])
    settle(sm, 10)
    assert loc(sm, 5) == "Shelf" and loc(sm, 9) == "Shelf"
    assert "2 spools" in sm.tag_events[-1]["text"]


def test_anycubic_tag_switch(make, cfg):
    sm, _ = make(anycubic(), [kind_spool(5, "Anycubic PETG Schwarz", "212721")])
    cfg.auto_assign_by_kind = False
    settle(sm, 10)
    assert loc(sm, 5) == "Shelf"
