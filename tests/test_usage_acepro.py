"""Verbrauchsmessung unter Klipper + ACEPRO (Bridge 3.0).

Zweifarbiger Druck wie am 08.10.2026 im Konsolenprotokoll: Start mit Slot 2, dann Wechsel auf Slot 1.
Bewegungen beim Wechsel (ACEPRO, mit Patch 0003 sofort in print_stats.filament_used):
- Entladen, alter Slot noch geladen (current = alt, target = neu): -2 mm vor dem Schneiden, -40 mm zurueck
- nach dem Entladen (current = -1, target = neu): +85 mm vom Kopf-Sensor bis zur Duese
- neuer Slot geladen (current = neu): +50 mm Spuelen, dann Druck
"""

from __future__ import annotations

import asyncio

import pytest
from conftest import FakeMoonraker, FakeSlots, FakeSpoolman, ace_status, grams, spool

LAV, MAG = {"material": "PETG", "color": "685BC7"}, {"material": "PETG", "color": "C52E79"}
# Slot 2 (Index 1): Laden 85 + Spuelen 50 + Nachfoerdern 20 + Druck 2500 - Entladen 42
# Slot 1 (Index 0): Laden 85 + Spuelen 50 + Druck 4000
EXPECTED = {2: 85 + 50 + 20 + 2500 - 42, 1: 85 + 50 + 4000}


def make(cfg, spools):
    from acebridge.usage import UsageTracker
    moon = FakeMoonraker()
    sm = FakeSpoolman(spools)
    return moon, sm, UsageTracker(cfg, moon, sm, FakeSlots(moon, sm))


def print_rows():
    """Zeilen wie die Telemetrie-Aufzeichnung: start (ganzer Status), dann Deltas."""
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
    ace(-1, 1)            # Druckstart laedt Slot 2
    use(85)
    ace(1, -1)
    use(50)               # Spuelen nach dem Laden
    use(20)               # Nachfoerdern im Druckstart
    use(2500, steps=25)   # Druck
    ace(1, 0)             # Wechsel auf Slot 1 beginnt
    use(-2)
    use(-40)
    ace(-1, 0)            # Slot 2 entladen
    use(85)
    ace(0, -1)            # Slot 1 geladen
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

    # "Absturz": neuer Tracker mit demselben Datenordner, Moonraker liefert den aktuellen Stand
    from acebridge.usage import UsageTracker
    tracker2 = UsageTracker(cfg, moon, sm, FakeSlots(moon, sm))
    assert tracker2.job is not None
    asyncio.run(tracker2.on_status(moon.status, True, moon.status))
    feed(moon, tracker2, rows[cut:])

    assert sm.bookings[:len(booked_before)] == booked_before
    assert sm.booked(3) == pytest.approx(EXPECTED[1], abs=0.1)
    assert sm.booked(4) == pytest.approx(EXPECTED[2], abs=0.1)


def test_slot_without_spool_becomes_open_item(cfg):
    moon, sm, tracker = make(cfg, [spool(4, 2)])          # Slot 1 ohne Spule
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
    """Endlosspule: die ACE springt mitten im Druck von Slot 1 auf Slot 3 (gleiche Farbe)."""
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
    """Sollwerte kommen aus der gelesenen Druckdatei (render.py e_total je Werkzeug, T<n> = Slot n)."""
    moon, sm, tracker = make(cfg, [spool(3, 1), spool(4, 2)])
    rows = print_rows()
    feed(moon, tracker, rows[:3])                                     # Druck laeuft
    tracker.set_targets("andere.gcode", {0: 1.0, 1: 9.0})            # Datei eines anderen Drucks: ignorieren
    assert tracker.job["targets"] is None
    # G-code will 5000 mm von Slot 1 (gemessen nur 4135) und 2500 mm von Slot 2; T3 fast nichts
    tracker.set_targets("zwei.gcode", {0: 5000.0, 1: 2500.0, 3: 0.4})
    tracker.set_targets("zwei.gcode", {0: 1.0})                       # zweites Mal: bleibt beim ersten
    feed(moon, tracker, rows[3:])
    job = tracker.history[0]
    by = {s["slot"]: s for s in job["slots"]}
    assert by[1]["target_mm"] == 5000.0 and by[2]["target_mm"] == 2500.0
    assert by[2]["overhead_mm"] == pytest.approx(EXPECTED[2] - 2500, abs=0.5)
    assert job["target_mm"] == 7500.0
    assert len(job["warnings"]) == 1 and job["warnings"][0].startswith("Slot 1: gemessen 4135 mm")
