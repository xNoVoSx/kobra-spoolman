"""Slot seen empty -> spool to the shelf (AUTO_UNASSIGN_ON_EMPTY), but not when the whole ACE vanishes.

13.10.2026 under Rinkhals: the ACE was power-cycled to clear a dryer fault. The firmware reported all four slots empty,
the bridge moved all four spools to the shelf, put them back by their tags afterwards, and the moisture model took that
for "spools inserted" - and started drying.
"""

from __future__ import annotations

import asyncio

from conftest import FakeMoonraker, ace_status, spool

from acebridge.slots import SlotManager

LOADED = [{"material": "PETG", "color": "685BC7"}, {"material": "PETG", "color": "C52E79"},
          {"material": "PETG", "color": "212721"}, {"material": "ASA", "color": "808080"}]


class SM:
    def __init__(self, spools):
        self.spools = spools
        self.connected = True
        self.patched = []

    def templates(self):
        return []

    async def refresh(self):
        return True

    async def patch_spool(self, sid, data):
        self.patched.append((sid, data))
        for s in self.spools:
            if s["id"] == sid:
                s.update(data)


def make(cfg):
    cfg.empty_debounce_s = 0
    cfg.write_lane_data = cfg.auto_assign_by_tag = cfg.auto_assign_by_kind = False
    moon = FakeMoonraker()
    moon.merge({**ace_status(LOADED), "print_stats": {"state": "standby"}})
    sm = SM([spool(sid, slot) for sid, slot in ((1, 1), (2, 2), (5, 3), (8, 4))])
    return moon, sm, SlotManager(cfg, moon, sm)


def run(slots, times=2):
    async def go():
        for _ in range(times):           # becoming empty, then the debounce (0 s) is over
            await slots.evaluate()
    asyncio.run(go())


def test_a_slot_emptied_by_hand_goes_to_the_shelf(cfg):
    moon, sm, slots = make(cfg)
    run(slots, 1)
    moon.merge(ace_status(LOADED[:2] + [None, LOADED[3]]))
    run(slots)
    assert sm.patched == [(5, {"location": cfg.shelf_location})]


def test_ace_switched_off_moves_nothing(cfg):
    moon, sm, slots = make(cfg)
    run(slots, 1)
    moon.merge(ace_status([None, None, None, None]))          # every slot empty at once: the ACE is gone
    run(slots, 3)
    assert sm.patched == []
    moon.merge(ace_status(LOADED))                            # back on: nothing to undo
    run(slots)
    assert sm.patched == []
    assert [s["location"] for s in sm.spools] == [f"ACE Slot {n}" for n in (1, 2, 3, 4)]


def test_printer_switched_off_and_on_moves_nothing(cfg):
    """Printer off: Klipper is gone (not ready). Back on: Klipper is ready before the ACE reports its slots - for a
    moment every slot looks empty. Neither moves a spool."""
    moon, sm, slots = make(cfg)
    run(slots, 1)
    moon.klippy_ready = False                                 # printer off
    run(slots, 3)
    moon.klippy_ready = True                                  # back on, the ACE has not reported yet
    moon.merge(ace_status([None, None, None, None]))
    run(slots, 3)
    moon.merge(ace_status(LOADED))                            # the ACE is there
    run(slots)
    assert sm.patched == []
    assert [s["location"] for s in sm.spools] == [f"ACE Slot {n}" for n in (1, 2, 3, 4)]


def test_overview_keeps_the_spools_and_says_offline(cfg):
    """Printer off: the overview still shows each slot's spool (Spoolman's location), marked as not live."""
    moon, sm, slots = make(cfg)
    run(slots, 1)
    assert all(s["live"] for s in slots.slots_view())
    moon.klippy_ready = False
    run(slots, 3)
    view = slots.slots_view()
    assert [s["spool"]["spool_id"] for s in view] == [1, 2, 5, 8]
    assert not any(s["live"] for s in view)
