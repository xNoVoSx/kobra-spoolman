"""Replay of a real print under Klipper + ACEPRO (bridge 3.x).

Recording of the bridge of 10.10.2026 (tests/data/asa_acepro_2026-10-10.jsonl.gz, unchanged): ASA part, print start with
PETG (slot 1) in the nozzle, one change to ASA (slot 4), 38 min. The bridge booked then (Spoolman, /api/jobs):
slot 1 #1 PETG 103.0 mm, slot 4 #8 ASA 4339.3 mm, 1 change, 2 loads, no warnings, no open items.
The test plays the recording through today's code and must give the same - changes to usage, print phase or the print
log that would treat real prints differently show up before they reach the printer.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from conftest import DATA, FakeMoonraker, FakeSlots, FakeSpoolman, load_recording, spool

REC = "asa_acepro_2026-10-10.jsonl.gz"
BOOKED = {1: 103.0, 4: 4339.3}            # as booked in Spoolman on 10.10.


def replay(cfg, on_row=None):
    from acebridge.usage import UsageTracker
    rows = load_recording(REC)
    moon = FakeMoonraker()
    sm = FakeSpoolman([spool(1, 1), spool(8, 4)])
    tracker = UsageTracker(cfg, moon, sm, FakeSlots(moon, sm))

    async def run():
        for r in rows:
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
    assert rows[-1]["end_state"] == "complete" and rows[-1]["gate_changes"][0]["to"] == 3
    assert (DATA / REC).stat().st_size < 150_000          # stays small in the repo


def test_books_like_the_real_print(cfg):
    _rows, sm, tracker = replay(cfg)
    job = tracker.history[0]
    by_slot = {s["slot"]: s["mm"] for s in job["slots"]}
    assert job["state"] == "complete"
    assert by_slot == pytest.approx(BOOKED, abs=0.1)
    assert sm.booked(1) == pytest.approx(BOOKED[1], abs=0.1)
    assert sm.booked(8) == pytest.approx(BOOKED[4], abs=0.1)
    assert job["changes"] == 1 and job["loads"] == 2 and job["warnings"] == []
    assert [(t["from_slot"], t["to_slot"]) for t in job["transitions"]] == [(None, 1), (1, 4)]
    assert tracker.open == [] and tracker.job is None


def test_phase_follows_the_print(cfg):
    """Print phase from the same recording (before kobra_phase: only change/printing) - never a crash, change recognised."""
    from acebridge import phase
    seen = []

    def watch(_r, status):
        d = phase.describe(status)
        text = d["text"] if d else None
        if not seen or seen[-1] != text:
            seen.append(text)
    replay(cfg, watch)
    assert "Change to slot 4" in seen
    assert "Printing" in seen
    assert seen[-1] is None                                  # after the print: only the state ("Finished")


def test_clog_never_raised_an_alarm():
    """Clog: ratios of the real print (before the encoder fix ~2.0) - never a suspicion."""
    rows = load_recording(REC)
    suspects = [r for r in rows if r["type"] == "delta" and (r["d"].get("kobra_clog") or {}).get("suspect")]
    assert suspects == []


def test_print_log_renders(cfg):
    from acebridge import printlog
    raw = [json.dumps(r) for r in load_recording(REC)]
    text = printlog.render(raw)
    assert "Print state" in text and "complete" in text
    assert "loaded T" in text and "Auto PA" in text
