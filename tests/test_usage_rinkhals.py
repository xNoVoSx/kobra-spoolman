"""Usage measurement under Rinkhals (GoKlipper) - replay of a real print (test 6, 24.09.2026, bridge 2.x).

Two-colour print on a Kobra S1 with ACE 2 Pro: first four blades in slot 2 (PLA white), then a handle in slot 1 (PLA
silk green), one colour change. At the end the printer counted filament_used = 8025 mm. Recomputed (incl. the
firmware purge, without retractions): slot 2 = 3055 mm, slot 1 = 4970 mm - bridge 2.21 booked exactly that, the
current code must too. GoKlipper flickers the loaded gate while loading; the tracker debounces it.
"""

from __future__ import annotations

import asyncio

import pytest
from conftest import FakeMoonraker, FakeSlots, FakeSpoolman, load_recording, spool

from acebridge import acemodel

EXPECTED = {1: 4970.0, 2: 3055.0}   # slot -> mm


def make(cfg, spools):
    from acebridge.usage import UsageTracker
    moon = FakeMoonraker()
    sm = FakeSpoolman(spools)
    return moon, sm, UsageTracker(cfg, moon, sm, FakeSlots(moon, sm))


def feed(moon, tracker, rows):
    async def run():
        for r in rows:
            if r["type"] == "start":
                moon.merge(r["status"])
                await tracker.on_status(r["status"], True, moon.status)
            else:
                moon.merge(r["d"])
                await tracker.on_status(r["d"], False, moon.status)
    asyncio.run(run())


def test_recording_is_rinkhals():
    status = load_recording()[0]["status"]
    assert acemodel.variant(status) == acemodel.RINKHALS and acemodel.flickers(status)


@pytest.mark.parametrize("debounce_s", [0.0, 3.0])
def test_replay_books_each_slot_exactly(cfg, debounce_s):
    cfg.gate_debounce_s = debounce_s    # 3 s as in the bridge; 0 settles every flicker at once
    moon, sm, tracker = make(cfg, [spool(3, 1), spool(4, 2)])
    feed(moon, tracker, load_recording())

    job = tracker.history[0]
    by_slot = {s["slot"]: s for s in job["slots"]}
    assert job["state"] == "complete"
    assert job["total_mm"] == pytest.approx(8025, abs=0.5)
    assert by_slot[1]["mm"] == pytest.approx(EXPECTED[1], abs=1)
    assert by_slot[2]["mm"] == pytest.approx(EXPECTED[2], abs=1)
    # booked exactly that, per spool
    assert sm.booked(3) == pytest.approx(EXPECTED[1], abs=1)
    assert sm.booked(4) == pytest.approx(EXPECTED[2], abs=1)
    assert job["changes"] == 1 and job["loads"] == 2
    assert tracker.job is None and tracker.open == []


def test_unload_at_start_books_nothing_negative(cfg):
    """13.10.: slot 3 loaded at the print start, GoKlipper unloads it first (-3 retract, -50 cut, '' and +50 back),
    then slot 1 prints. Slot 3 used nothing - no negative booking, no open item with -3 mm."""
    cfg.book_interval_s, cfg.book_min_mm = 0, 1
    moon, sm, tracker = make(cfg, [spool(1, 1), spool(5, 3)])

    def st(cur, used, state="printing"):
        return {"print_stats": {"state": state, "filename": "duck.gcode", "filament_used": used},
                "filament_hub": {"current_filament": cur}}
    steps = [st("0-2", 0), st("0-2", -3), st("0-2", -53), st("", -53), st("", -3), st("0-0", -3), st("0-0", 497),
             st("0-0", 497, "complete")]
    rows = [{"type": "start", "status": steps[0]}] + [{"type": "delta", "d": s} for s in steps[1:]]
    feed(moon, tracker, rows)

    assert [b for b in sm.bookings if b[0] == 5] == []
    assert sm.booked(1) == pytest.approx(500)
    assert tracker.open == [] and tracker.job is None
