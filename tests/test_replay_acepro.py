"""Replay eines echten Drucks unter Klipper + ACEPRO (Bridge 3.x).

Aufzeichnung der Bridge vom 10.10.2026 (tests/data/asa_acepro_2026-10-10.jsonl.gz, unverändert): ASA-Teil, Druckstart mit
PETG (Slot 1) in der Düse, ein Wechsel auf ASA (Slot 4), 38 min. Die Bridge hat damals gebucht (Spoolman, /api/jobs):
Slot 1 #1 PETG 103,0 mm, Slot 4 #8 ASA 4339,3 mm, 1 Wechsel, 2 Ladevorgänge, keine Warnungen, keine offenen Posten.
Der Test spielt die Aufzeichnung durch den heutigen Code und muss dasselbe ergeben - Änderungen am Verbrauch, an der
Druckphase oder am Druckprotokoll, die echte Drucke anders behandeln würden, fallen so vor dem Drucker auf.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from conftest import DATA, FakeMoonraker, FakeSlots, FakeSpoolman, load_recording, spool

REC = "asa_acepro_2026-10-10.jsonl.gz"
BOOKED = {1: 103.0, 4: 4339.3}            # wie am 10.10. in Spoolman gebucht


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
    assert (DATA / REC).stat().st_size < 150_000          # bleibt klein im Repo


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
    """Druckphase aus derselben Aufzeichnung (vor kobra_phase: nur Wechsel/Druckt) - nie ein Absturz, Wechsel erkannt."""
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
    assert seen[-1] is None                                  # nach dem Druck: nur der Status ("Fertig")


def test_clog_never_raised_an_alarm():
    """Verstopfung: Verhaeltnisse des echten Drucks (vor dem Encoder-Fix ~2,0) - nie ein Verdacht."""
    rows = load_recording(REC)
    suspects = [r for r in rows if r["type"] == "delta" and (r["d"].get("kobra_clog") or {}).get("suspect")]
    assert suspects == []


def test_print_log_renders(cfg):
    from acebridge import printlog
    raw = [json.dumps(r) for r in load_recording(REC)]
    text = printlog.render(raw)
    assert "Print state" in text and "complete" in text
    assert "loaded T" in text and "Auto PA" in text
