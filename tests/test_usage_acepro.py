"""Usage measurement under Klipper + ACEPRO (bridge 3.0).

Two-colour print as on 08.10.2026 in the console log: start with slot 2, then a change to slot 1.
Moves at the change (ACEPRO, with patch 0003 at once in print_stats.filament_used):
- unloading, old slot still loaded (current = old, target = new): -2 mm before cutting, -40 mm back
- after unloading (current = -1, target = new): +85 mm from the head sensor to the nozzle
- new slot loaded (current = new): +50 mm purge, then printing
"""

from __future__ import annotations

import asyncio

import pytest
from conftest import FakeMoonraker, FakeSlots, FakeSpoolman, ace_status, grams, spool

LAV, MAG = {"material": "PETG", "color": "685BC7"}, {"material": "PETG", "color": "C52E79"}
# slot 2 (index 1): loading 85 + purge 50 + extra feed 20 + print 2500 - unloading 42
# slot 1 (index 0): loading 85 + purge 50 + print 4000
EXPECTED = {2: 85 + 50 + 20 + 2500 - 42, 1: 85 + 50 + 4000}


def make(cfg, spools):
    from acebridge.usage import UsageTracker
    moon = FakeMoonraker()
    sm = FakeSpoolman(spools)
    return moon, sm, UsageTracker(cfg, moon, sm, FakeSlots(moon, sm))


def print_rows():
    """Lines like the telemetry recording: start (whole state), then deltas."""
    used = [0.0]
    rows = []

    def ace(current, target):
        rows.append({"type": "delta", "d": {"ace": {"current_index": current, "target_index": target}}})

    def use(mm, steps=1):
        for _ in range(steps):
            used[0] += mm / steps
            rows.append({"type": "delta", "d": {"print_stats": {"filament_used": round(used[0], 3)}}})

    status = ace_status([LAV, MAG])
    status["print_stats"] = {"state": "printing", "filename": "zwei.gcode", "filament_used": 0.0}
    status["virtual_sdcard"] = {}
    rows.append({"type": "start", "status": status})
    ace(-1, 1)            # print start loads slot 2
    use(85)
    ace(1, -1)
    use(50)               # purge after loading
    use(20)               # extra feed at print start
    use(2500, steps=25)   # print
    ace(1, 0)             # change to slot 1 begins
    use(-2)
    use(-40)
    ace(-1, 0)            # slot 2 unloaded
    use(85)
    ace(0, -1)            # slot 1 loaded
    use(50)
    use(4000, steps=40)
    rows.append({"type": "delta", "d": {"print_stats": {"state": "complete"}}})
    return rows


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


def test_books_each_slot_exactly(cfg):
    moon, sm, tracker = make(cfg, [spool(3, 1), spool(4, 2)])
    feed(moon, tracker, print_rows())

    job = tracker.history[0]
    by_slot = {s["slot"]: s for s in job["slots"]}
    assert job["state"] == "complete"
    assert job["total_mm"] == pytest.approx(EXPECTED[1] + EXPECTED[2], abs=0.1)
    assert by_slot[1]["mm"] == pytest.approx(EXPECTED[1], abs=0.1)
    assert by_slot[2]["mm"] == pytest.approx(EXPECTED[2], abs=0.1)
    assert sm.booked(3) == pytest.approx(EXPECTED[1], abs=0.1)
    assert sm.booked(4) == pytest.approx(EXPECTED[2], abs=0.1)
    assert job["changes"] == 1 and job["loads"] == 2
    assert job["warnings"] == []
    assert tracker.job is None and tracker.open == []


def test_records_colour_changes(cfg):
    moon, sm, tracker = make(cfg, [spool(3, 1), spool(4, 2)])
    feed(moon, tracker, print_rows())
    job = tracker.history[0]
    assert [(t["from_slot"], t["to_slot"], t["count"]) for t in job["transitions"]] == [(None, 2, 1), (2, 1, 1)]
    assert [(t["from_color"], t["to_color"]) for t in job["transitions"]] == [(None, "C52E79"), ("C52E79", "685BC7")]


def test_restart_in_the_middle_does_not_double_book(cfg):
    rows = print_rows()
    cut = len(rows) // 2
    moon, sm, tracker = make(cfg, [spool(3, 1), spool(4, 2)])
    feed(moon, tracker, rows[:cut])
    booked_before = list(sm.bookings)

    # "crash": new tracker with the same data folder, Moonraker delivers the current state
    from acebridge.usage import UsageTracker
    tracker2 = UsageTracker(cfg, moon, sm, FakeSlots(moon, sm))
    assert tracker2.job is not None
    asyncio.run(tracker2.on_status(moon.status, True, moon.status))
    feed(moon, tracker2, rows[cut:])

    assert sm.bookings[:len(booked_before)] == booked_before
    assert sm.booked(3) == pytest.approx(EXPECTED[1], abs=0.1)
    assert sm.booked(4) == pytest.approx(EXPECTED[2], abs=0.1)


def test_slot_without_spool_becomes_open_item(cfg):
    moon, sm, tracker = make(cfg, [spool(4, 2)])          # slot 1 without a spool
    feed(moon, tracker, print_rows())

    assert sm.booked(4) == pytest.approx(EXPECTED[2], abs=0.1)
    assert len(tracker.open) == 1
    item = tracker.open[0]
    assert item["slot"] == 1 and item["reason"] == "no_spool"
    assert item["mm"] == pytest.approx(EXPECTED[1], abs=0.1)
    assert item["g_est"] == pytest.approx(grams(EXPECTED[1]), abs=0.05)

    sm.spools.append(spool(9, None))
    asyncio.run(tracker.resolve_open(item["id"], 9))
    assert tracker.open == []
    assert sm.booked(9) == pytest.approx(EXPECTED[1], abs=0.1)


def test_spoolman_down_at_the_end_is_retried(cfg):
    moon, sm, tracker = make(cfg, [spool(3, 1), spool(4, 2)])
    rows = print_rows()
    feed(moon, tracker, rows[:-20])
    sm.fail = True
    feed(moon, tracker, rows[-20:])
    assert any(i["reason"] == "retry" for i in tracker.open)

    sm.fail = False
    tracker._backoff_until = 0
    asyncio.run(tracker.tick())
    assert tracker.open == []
    assert sm.booked(3) == pytest.approx(EXPECTED[1], abs=0.1)
    assert sm.booked(4) == pytest.approx(EXPECTED[2], abs=0.1)


def test_endless_spool_books_on_the_new_slot(cfg):
    """Endless spool: in the middle of the print the ACE jumps from slot 1 to slot 3 (same colour)."""
    moon, sm, tracker = make(cfg, [spool(3, 1), spool(5, 3)])
    rows = [r for r in print_rows() if not (r["type"] == "delta" and "ace" in r["d"])][:30]
    status = rows[0]["status"]
    status.update(ace_status([LAV, None, LAV], current=0))
    status["print_stats"] = {"state": "printing", "filename": "lang.gcode", "filament_used": 0.0}
    used = rows[-1]["d"]["print_stats"]["filament_used"]
    rows.append({"type": "delta", "d": {"ace": {"current_index": -1, "target_index": 2}}})
    rows.append({"type": "delta", "d": {"print_stats": {"filament_used": used + 85}}})
    rows.append({"type": "delta", "d": {"ace": {"current_index": 2, "target_index": -1}}})
    rows.append({"type": "delta", "d": {"print_stats": {"filament_used": used + 85 + 300}}})
    rows.append({"type": "delta", "d": {"print_stats": {"state": "complete"}}})
    feed(moon, tracker, rows)
    assert sm.booked(3) == pytest.approx(used, abs=0.1)
    assert sm.booked(5) == pytest.approx(385, abs=0.1)


def test_targets_from_the_gcode_check_the_measurement(cfg):
    """Targets come from the parsed print file (render.py e_total per tool, T<n> = slot n)."""
    moon, sm, tracker = make(cfg, [spool(3, 1), spool(4, 2)])
    rows = print_rows()
    feed(moon, tracker, rows[:3])                                     # the print runs
    tracker.set_targets("andere.gcode", {0: 1.0, 1: 9.0})            # Datei eines anderen Drucks: ignorieren
    assert tracker.job["targets"] is None
    # the G-code wants 5000 mm from slot 1 (measured only 4135) and 2500 mm from slot 2; T3 almost nothing
    tracker.set_targets("zwei.gcode", {0: 5000.0, 1: 2500.0, 3: 0.4})
    tracker.set_targets("zwei.gcode", {0: 1.0})                       # second time: stays with the first
    feed(moon, tracker, rows[3:])
    job = tracker.history[0]
    by = {s["slot"]: s for s in job["slots"]}
    assert by[1]["target_mm"] == 5000.0 and by[2]["target_mm"] == 2500.0
    assert by[2]["overhead_mm"] == pytest.approx(EXPECTED[2] - 2500, abs=0.5)
    assert job["target_mm"] == 7500.0
    assert len(job["warnings"]) == 1 and job["warnings"][0].startswith("Slot 1: measured 4135 mm")


def test_purge_log_per_colour_pair(cfg):
    """Learning purge values, part 1: every purge amount Orca sets before a change lands in the purge log with colour/
    material before/after (across prints); the first load at print start does not count."""
    moon, sm, tracker = make(cfg, [spool(3, 1), spool(4, 2)])
    rows = print_rows()
    change_at = next(i for i, r in enumerate(rows)
                     if r["type"] == "delta" and r["d"].get("ace") == {"current_index": 1, "target_index": 0})
    tracker.on_console({"text": "// ACE: Purge settings updated - Length: 120.5mm, Speed: 300mm/min"})   # before the start:
    feed(moon, tracker, rows[:change_at])          # ... does NOT apply to the first load (print start)
    tracker.on_console({"text": "// ACE: Purge settings updated - Length: 64.2mm, Speed: 300mm/min"})
    feed(moon, tracker, rows[change_at:])
    job = tracker.history[0]
    assert [(t["from_slot"], t["to_slot"], t["purge_mm"]) for t in job["transitions"]] == [(None, 2, None), (2, 1, 64.2)]
    pairs = tracker.purge_pairs()
    assert len(pairs) == 1
    p = pairs[0]
    assert (p["from_color"], p["from_material"], p["to_color"], p["to_material"]) == ("C52E79", "PETG", "685BC7", "PETG")
    assert p["count"] == 1 and p["purge_mm"] == [64.2] and p["last_file"] == "zwei.gcode"
    # second print with the same change: counts on, without an amount set (e.g. purge in the prime tower) -> no number
    moon2, sm2, tracker2 = make(cfg, [spool(3, 1), spool(4, 2)])
    feed(moon2, tracker2, print_rows())
    p = tracker2.purge_pairs()[0]
    assert p["count"] == 2 and p["purge_mm"] == [64.2]
