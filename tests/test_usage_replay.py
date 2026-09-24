"""Verbrauchsmessung mit einem echten Druck (Test 6, 24.09.2026).

Zweifarbiger Druck auf einem Kobra S1 mit ACE 2 Pro: erst vier Klingen in Slot 2 (PLA Weiss),
dann ein Griff in Slot 1 (PLA Silk Gruen), ein Farbwechsel. Orca-Sollwerte (Modell):
Slot 2 = 2660 mm, Slot 1 = 4830 mm. Der Drucker zaehlte am Ende filament_used = 8025 mm.
Nachgerechnet (inkl. Spuelen, ohne Rueckzuege): Slot 2 = 3055 mm, Slot 1 = 4970 mm.
"""

from __future__ import annotations

import asyncio

import pytest

from conftest import FakeMoonraker, FakeSlots, FakeSpoolman, grams, load_recording, spool

EXPECTED = {1: 4970.0, 2: 3055.0}   # Slot -> mm


def make(cfg, spools):
    from acebridge.usage import UsageTracker
    moon = FakeMoonraker()
    sm = FakeSpoolman(spools)
    slots = FakeSlots(moon, sm)
    return moon, sm, UsageTracker(cfg, moon, sm, slots)


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


def test_replay_books_each_slot_exactly(cfg):
    moon, sm, tracker = make(cfg, [spool(3, 1), spool(4, 2)])
    feed(moon, tracker, load_recording())

    job = tracker.history[0]
    by_slot = {s["slot"]: s for s in job["slots"]}
    assert job["state"] == "complete"
    assert job["total_mm"] == pytest.approx(8025, abs=0.5)
    assert by_slot[1]["mm"] == pytest.approx(EXPECTED[1], abs=1)
    assert by_slot[2]["mm"] == pytest.approx(EXPECTED[2], abs=1)
    # gebucht wurde genau das, pro Spule
    assert sm.booked(3) == pytest.approx(EXPECTED[1], abs=1)
    assert sm.booked(4) == pytest.approx(EXPECTED[2], abs=1)
    # Sollwerte aus dem G-code-Kopf (Firmware meldet cm3 unter "m")
    assert by_slot[1]["target_mm"] == pytest.approx(4830, rel=0.002)
    assert by_slot[2]["target_mm"] == pytest.approx(2660, rel=0.002)
    assert job["changes"] == 1 and job["loads"] == 2
    assert job["warnings"] == []
    assert tracker.job is None and tracker.open == []


def test_restart_in_the_middle_does_not_double_book(cfg):
    rows = load_recording()
    cut = len(rows) // 2
    spools = [spool(3, 1), spool(4, 2)]
    moon, sm, tracker = make(cfg, spools)
    feed(moon, tracker, rows[:cut])
    booked_before = list(sm.bookings)

    # "Absturz": neuer Tracker mit demselben Datenordner, Moonraker liefert den aktuellen Stand
    from acebridge.usage import UsageTracker
    tracker2 = UsageTracker(cfg, moon, sm, FakeSlots(moon, sm))
    assert tracker2.job is not None
    asyncio.run(tracker2.on_status(moon.status, True, moon.status))
    feed(moon, tracker2, rows[cut:])

    assert sm.bookings[:len(booked_before)] == booked_before
    assert sm.booked(3) == pytest.approx(EXPECTED[1], abs=1)
    assert sm.booked(4) == pytest.approx(EXPECTED[2], abs=1)


def test_slot_without_spool_becomes_open_item(cfg):
    moon, sm, tracker = make(cfg, [spool(4, 2)])          # Slot 1 ohne Spule
    feed(moon, tracker, load_recording())

    assert sm.booked(4) == pytest.approx(EXPECTED[2], abs=1)
    assert len(tracker.open) == 1
    item = tracker.open[0]
    assert item["slot"] == 1 and item["reason"] == "no_spool"
    assert item["mm"] == pytest.approx(EXPECTED[1], abs=1)
    assert item["g_est"] == pytest.approx(grams(EXPECTED[1]), abs=0.05)

    # nachbuchen auf eine Spule
    sm.spools.append(spool(9, None))
    asyncio.run(tracker.resolve_open(item["id"], 9))
    assert tracker.open == []
    assert sm.booked(9) == pytest.approx(EXPECTED[1], abs=1)


def test_spoolman_down_at_the_end_is_retried(cfg):
    moon, sm, tracker = make(cfg, [spool(3, 1), spool(4, 2)])
    rows = load_recording()
    feed(moon, tracker, rows[:-40])
    sm.fail = True
    feed(moon, tracker, rows[-40:])
    assert any(i["reason"] == "retry" for i in tracker.open)

    sm.fail = False
    tracker._backoff_until = 0
    asyncio.run(tracker.tick())
    assert tracker.open == []
    assert sm.booked(3) == pytest.approx(EXPECTED[1], abs=1)
    assert sm.booked(4) == pytest.approx(EXPECTED[2], abs=1)
