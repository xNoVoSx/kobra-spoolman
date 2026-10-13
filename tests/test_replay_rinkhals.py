"""Replay of a real print under Rinkhals (GoKlipper, bridge 3.17.0).

Recording of the bridge of 13.10.2026 (tests/data/rinkhals_duck_2026-10-13.jsonl.gz): three-colour duck, PETG, 4 h 57 min,
56 slot changes (slot 3 loaded at the start, then 1 <-> 2 26 times each, 3 at the end). Shrunk for the repo with
tools/recordings/trim-rinkhals.py (private): GoKlipper's counter fields (decorder, remain, temperatures, keystate,
tracker_detection_length, print durations) dropped, everything usage/phase/printlog read kept unchanged.
The printer counted filament_used = 26414 mm; the bridge booked slot 1 #1 22397 mm, slot 2 #2 3651 mm, slot 3 #5 366 mm,
56 changes, 57 loads, no open items. A live logger saw the bridge follow every change (no mismatch over 20 s).

GoKlipper at every unload: -3 mm retract and -50 mm cut while the old slot is still loaded, then current_filament ''
and +50 mm back, then the new slot. Interim bookings must never go negative (3.17.0 booked -53 mm on slot 3 for a
moment); the net retract is settled with the slot's later consumption.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from conftest import DATA, FakeMoonraker, FakeSlots, FakeSpoolman, load_recording, spool

from acebridge import acemodel

REC = "rinkhals_duck_2026-10-13.jsonl.gz"
BOOKED = {1: 22397.0, 2: 3651.0, 3: 366.0}         # slot -> mm, as booked on 13.10.
SPOOLS = {1: 1, 2: 2, 3: 5}                       # slot -> spool


class RecordingClock:
    """time for usage.py, monotonic = the recording's t (debounce and booking intervals as in the real print)."""

    def __init__(self):
        self.t = 1_000_000.0

    def monotonic(self):
        return self.t

    def __getattr__(self, name):
        return getattr(time, name)


def replay(cfg, on_row=None, monkeypatch=None):
    from acebridge import usage
    rows = load_recording(REC)
    moon = FakeMoonraker()
    sm = FakeSpoolman([spool(sid, slot) for slot, sid in SPOOLS.items()])
    tracker = usage.UsageTracker(cfg, moon, sm, FakeSlots(moon, sm))
    clock = RecordingClock()
    if monkeypatch is not None:
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
            if on_row:
                on_row(r, moon.status)
    asyncio.run(run())
    return rows, sm, tracker


def test_recording_is_the_real_print():
    rows = load_recording(REC)
    assert rows[0]["type"] == "start" and rows[-1]["type"] == "summary"
    assert acemodel.variant(rows[0]["status"]) == acemodel.RINKHALS
    assert rows[-1]["end_state"] == "complete" and rows[-1]["filament_used_end"] == 26414
    assert (DATA / REC).stat().st_size < 150_000          # stays small in the repo


@pytest.mark.parametrize("debounce_s", [0.0, 3.0])
def test_books_like_the_real_print(cfg, monkeypatch, debounce_s):
    cfg.gate_debounce_s = debounce_s                    # 3 s as in the bridge
    _rows, sm, tracker = replay(cfg, monkeypatch=monkeypatch)
    job = tracker.history[0]
    by_slot = {s["slot"]: s["mm"] for s in job["slots"]}
    assert job["state"] == "complete"
    assert job["total_mm"] == pytest.approx(26414, abs=0.5)
    assert by_slot == pytest.approx(BOOKED, abs=0.5)
    for slot, sid in SPOOLS.items():
        assert sm.booked(sid) == pytest.approx(BOOKED[slot], abs=0.5)
    assert job["changes"] == 56 and job["loads"] == 57 and job["warnings"] == []
    assert tracker.open == [] and tracker.job is None


@pytest.mark.parametrize("interval_s", [0, 300])
def test_interim_bookings_never_go_negative(cfg, monkeypatch, interval_s):
    """Interim bookings (every update / every 5 min as in the bridge): the cut/retract at an unload never reaches
    Spoolman as a negative booking - a correction at a change or the end only takes back what this print booked."""
    cfg.book_interval_s, cfg.gate_debounce_s = interval_s, 3.0
    _rows, sm, tracker = replay(cfg, monkeypatch=monkeypatch)
    total = dict.fromkeys(SPOOLS.values(), 0.0)
    for sid, mm in sm.bookings:
        total[sid] += mm
        assert total[sid] >= -0.01, f"spool #{sid} went below what this print booked"
    for sid in SPOOLS.values():
        assert next(mm for s, mm in sm.bookings if s == sid) > 0     # 3.17.0: -53 mm on #5 first
    for slot, sid in SPOOLS.items():
        assert sm.booked(sid) == pytest.approx(BOOKED[slot], abs=0.5)
    if interval_s == 300:
        assert [(sid, mm) for sid, mm in sm.bookings if mm < 0] == [(5, -51.0)]   # only the unload at the end
    assert tracker.open == []


def test_bridge_follows_every_change():
    """Active slot from current_filament: 56 changes during the print, never a busy gate (-1) taken as loaded."""
    rows = load_recording(REC)
    from conftest import FakeMoonraker as M
    moon, seen = M(), []
    for r in rows:
        if r["type"] == "start":
            moon.merge(r["status"])
        elif r["type"] == "delta":
            moon.merge(r["d"])
        else:
            continue
        s = acemodel.active_slot(moon.status)
        if s is not None and (not seen or seen[-1] != s):
            seen.append(s)
    assert len(seen) == 57                                  # start slot + 56 changes
    assert seen[0] == 2 and seen[1] == 0 and seen[-1] == 2
    assert set(seen) == {0, 1, 2}


def test_phase_follows_the_print(cfg):
    from acebridge import phase
    texts = set()

    def watch(_r, status):
        d = phase.describe(status)
        texts.add(d["text"] if d else None)
    replay(cfg, watch)
    assert "Printing" in texts


def test_print_log_renders():
    import json

    from acebridge import printlog
    text = printlog.render([json.dumps(r) for r in load_recording(REC)])
    assert "Print state" in text and "complete" in text
