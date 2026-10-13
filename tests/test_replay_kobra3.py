"""Replay of a real print on a Kobra 3 with ACE Pro (first generation) under Rinkhals - recorded and shared by MineTech13.

Recording of his bridge of 09.10.2026 (tests/data/rinkhals_kobra3_2026-10-09.jsonl.gz, shrunk with
tools/recordings/trim-rinkhals.py): steam-frame-fixture-ams, PLA, 9 h 6 min. Four hours white (slot 2), then three times
white -> black (slot 1) and back. The printer counted filament_used = 94372 mm. GoKlipper on the Kobra 3 changes like on
the S1 (current_filament '' while unloading, -3/-50 mm cut, +50 mm back, then the new slot).

Orca's plan from the G-code header ("filament used [mm]"): slot 1 418.43 mm, slot 2 92698.74 mm, 6 changes, prime tower.
The rest is the firmware's own purge, which Orca does not know about under Rinkhals.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from conftest import DATA, FakeMoonraker, FakeSlots, FakeSpoolman, load_recording, spool

from acebridge import acemodel
from acebridge.purge import PurgeModel

REC = "rinkhals_kobra3_2026-10-09.jsonl.gz"
COUNTER = 94372.0
BOOKED = {1: 619.0, 2: 93753.0}                   # slot -> mm
PLAN = {1: 418.43, 2: 92698.74}                   # slot -> mm, Orca's G-code header
SPOOLS = {1: 11, 2: 12, 3: 13, 4: 14}             # slot -> spool


class RecordingClock:
    """time for usage.py, monotonic = the recording's t (debounce and booking intervals as in the real print)."""

    def __init__(self):
        self.t = 1_000_000.0

    def monotonic(self):
        return self.t

    def __getattr__(self, name):
        return getattr(time, name)


def replay(cfg, monkeypatch):
    from acebridge import usage
    rows = load_recording(REC)
    moon = FakeMoonraker()
    sm = FakeSpoolman([spool(sid, slot) for slot, sid in SPOOLS.items()])
    tracker = usage.UsageTracker(cfg, moon, sm, FakeSlots(moon, sm))
    clock = RecordingClock()
    monkeypatch.setattr(usage, "time", clock)

    async def run():
        for r in rows:
            if "t" in r:
                clock.t = 1_000_000.0 + r["t"]
            if r["type"] == "start":
                moon.merge(r["status"])
                await tracker.on_status(r["status"], True, moon.status)
            elif r["type"] == "delta":
                moon.merge(r["d"])
                await tracker.on_status(r["d"], False, moon.status)
    asyncio.run(run())
    return sm, tracker


def test_recording_is_the_kobra3_print():
    rows = load_recording(REC)
    assert rows[0]["type"] == "start" and rows[-1]["type"] == "summary"
    status = rows[0]["status"]
    assert acemodel.variant(status) == acemodel.RINKHALS
    assert status["print_stats"]["filename"] == "steam-frame-fixture-ams_PLA_0.2_10h9m.gcode"
    assert rows[-1]["end_state"] == "complete" and rows[-1]["filament_used_end"] == COUNTER
    assert (DATA / REC).stat().st_size < 150_000          # stays small in the repo


@pytest.mark.parametrize("debounce_s", [0.0, 3.0])
@pytest.mark.parametrize("interval_s", [0.0, 300.0])
def test_books_each_slot_like_the_printer(cfg, monkeypatch, debounce_s, interval_s):
    cfg.gate_debounce_s, cfg.book_interval_s = debounce_s, interval_s
    sm, tracker = replay(cfg, monkeypatch)

    job = tracker.history[0]
    assert job["state"] == "complete"
    assert job["total_mm"] == pytest.approx(COUNTER)
    assert job["changes"] == 6 and job["loads"] == 7
    assert [(t["from_slot"], t["to_slot"], t["count"]) for t in job["transitions"]] == [(None, 2, 1), (2, 1, 3), (1, 2, 3)]
    for slot, mm in BOOKED.items():
        assert sm.booked(SPOOLS[slot]) == pytest.approx(mm, abs=1)
    assert sum(sm.booked(s) for s in SPOOLS.values()) == pytest.approx(COUNTER, abs=0.5)
    assert sm.booked(SPOOLS[3]) == 0 and sm.booked(SPOOLS[4]) == 0
    assert tracker.job is None and tracker.open == []


def test_no_spool_is_ever_booked_below_zero(cfg, monkeypatch):
    """Interim bookings only go forward; a correction at a change (the cut after an interim booking) never takes back
    more than was booked."""
    cfg.gate_debounce_s, cfg.book_interval_s, cfg.book_min_mm = 3.0, 0.0, 10.0
    sm, _tracker = replay(cfg, monkeypatch)
    total = {}
    for sid, mm in sm.bookings:
        total[sid] = total.get(sid, 0.0) + mm
        assert total[sid] >= -0.5, (sid, mm, total[sid])


def test_firmware_purge_model_fits_the_kobra3(cfg, monkeypatch):
    """The purge model (purge.py, default values calibrated on a Kobra S1 with ACE 2 Pro) predicts the extra use over
    Orca's plan on the Kobra 3 within a few percent: in total 1141 mm predicted for 1255 mm measured."""
    _sm, tracker = replay(cfg, monkeypatch)
    predicted = PurgeModel().predict(tracker.history[0]["transitions"])
    measured = {slot: BOOKED[slot] - PLAN[slot] for slot in PLAN}
    assert sum(predicted.values()) == pytest.approx(sum(measured.values()), rel=0.10)
    for slot in PLAN:
        assert predicted[slot] == pytest.approx(measured[slot], rel=0.15)
