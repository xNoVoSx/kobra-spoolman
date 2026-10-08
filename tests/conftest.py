"""Gemeinsame Test-Hilfen: Pfade, Nachbauten von Moonraker, Spoolman und SlotManager."""

from __future__ import annotations

import asyncio
import gzip
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bridge" / "app"))
DATA = Path(__file__).resolve().parent / "data"


def load_recording(name: str = "blade_print_2026-09-24.jsonl.gz") -> List[Dict[str, Any]]:
    with gzip.open(DATA / name, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


class FakeMoonraker:
    def __init__(self):
        self.status: Dict[str, Dict[str, Any]] = {}
        self.connected = True
        self.klippy_ready = True
        self.components: list = []

    def merge(self, delta: Dict[str, Any]) -> None:
        for obj, fields in delta.items():
            self.status.setdefault(obj, {}).update(fields)


class FakeSpoolman:
    """Spulen/Filamente im Speicher; use_length wird mitgeschrieben."""

    def __init__(self, spools: List[Dict[str, Any]]):
        self.spools = spools
        self.filaments = [s["filament"] for s in spools]
        self.connected = True
        self.bookings: List[tuple] = []
        self.fail = False
        self.missing: set = set()

    async def refresh(self) -> bool:
        return True

    def spool(self, spool_id):
        return next((s for s in self.spools if s["id"] == spool_id), None)

    async def use_length(self, spool_id: int, mm: float):
        if self.fail:
            raise ConnectionError("spoolman down")
        if spool_id in self.missing:
            raise LookupError(spool_id)
        self.bookings.append((spool_id, mm))
        return {}

    def booked(self, spool_id: int) -> float:
        return sum(mm for sid, mm in self.bookings if sid == spool_id)


class FakeSlots:
    """Slot -> Spule wie in Spoolman ('ACE Slot N')."""

    def __init__(self, moon: FakeMoonraker, sm: FakeSpoolman):
        self.moon = moon
        self.sm = sm

    def assignments(self):
        out = {}
        for s in self.sm.spools:
            loc = s.get("location") or ""
            if loc.startswith("ACE Slot "):
                out[int(loc.split()[-1])] = s
        return out, []

    def ace_gate(self, gate: int) -> Dict[str, Any]:
        from acebridge import acemodel
        return acemodel.slot(self.moon.status, gate, self.moon.klippy_ready)


def ace_status(slots: List[Optional[Dict[str, Any]]], current: int = -1, humidity: Any = 20, temp: Any = 25,
               dryer: Optional[Dict[str, Any]] = None, endless: bool = False, connected: bool = True) -> Dict[str, Any]:
    """ACEPRO-Objekte ace/ace_instance_0 wie am Pi (tests/data/acepro_status_2026-10-09.json).

    slots: je Slot None (leer) oder {"material", "color" "RRGGBB", optional "sku" (= Spule mit Tag), "temp"}."""
    raw = []
    for i, sp in enumerate((slots + [None] * 4)[:4]):
        if not sp:
            raw.append({"index": i, "tool": i, "status": "empty", "color": [0, 0, 0], "material": "", "temp": 0,
                        "rfid": False})
            continue
        c = sp.get("color", "FFFFFF")
        entry = {"index": i, "tool": i, "status": sp.get("status", "ready"),
                 "color": [int(c[k:k + 2], 16) for k in (0, 2, 4)], "material": sp.get("material", ""),
                 "temp": sp.get("temp", 0), "rfid": bool(sp.get("sku"))}
        if sp.get("sku"):
            entry["sku"] = sp["sku"]
        raw.append(entry)
    ds = {"status": "stop", "target_temp": 0, "duration": 0, "remain_time": 0}
    ds.update(dryer or {})
    return {
        "ace": {"ace_instances": 1, "current_index": current, "target_index": -1,
                "endless_spool_enabled": endless, "endless_spool_match_mode": "exact"},
        "ace_instance_0": {"status": "ready", "dryer_status": ds, "temp": temp, "humidity": humidity, "slots": raw,
                           "firmware": "V1.1.36", "model": "ACE2 (USB Single Serial)",
                           "connection_state": "connected" if connected else "disconnected"},
    }


def spool(spool_id: int, slot: Optional[int], density: float = 1.24) -> Dict[str, Any]:
    return {"id": spool_id, "location": f"ACE Slot {slot}" if slot else "Regal",
            "filament": {"id": 100 + spool_id, "name": f"Test {spool_id}", "density": density,
                         "diameter": 1.75, "vendor": {"name": "Test"}}}


def grams(mm: float, density: float = 1.24, diameter: float = 1.75) -> float:
    return mm * math.pi * (diameter / 2) ** 2 * density / 1000.0


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MOONRAKER_URL", "http://printer.invalid:7125")
    monkeypatch.setenv("BOOK_INTERVAL_S", "1000000")   # nur Buchungen bei Wechsel/Ende
    monkeypatch.setenv("GATE_DEBOUNCE_S", "0")
    from acebridge.config import Config
    return Config()


os.environ.setdefault("MOONRAKER_URL", "http://printer.invalid:7125")


# ---------------------------------------------------------------- KI (vision)
class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


class FakeCamera:
    def __init__(self):
        self.calls = 0

    async def still(self):
        self.calls += 1
        return b"\xff\xd8fake-jpeg", 0.0


@pytest.fixture
def vision(cfg, monkeypatch):
    """KI mit Nachbau von Kamera und Dienst: v.p_next bestimmt die Sicherheit des naechsten Fundes."""
    from acebridge.vision import Vision
    cfg.vision_url = "http://vision.invalid:7917"
    cfg.vision_interval_s = 10
    moon = FakeMoonraker()
    moon.merge({"print_stats": {"state": "standby", "filename": "Benchy PETG.gcode"}})
    clock = Clock()
    v = Vision(cfg, moon, FakeCamera(), None, clock=clock)
    v.p_next = 0.0

    async def analyze(_img):
        return {"detections": [["failure", v.p_next, [0.5, 0.5, 0.2, 0.2]]] if v.p_next else [],
                "width": 1280, "height": 720, "ms": 50, "provider": "CPUExecutionProvider"}

    async def health():
        v.health = {"ok": True, "model": {"loaded": False, "provider": None}}
    monkeypatch.setattr(v, "analyze", analyze)
    monkeypatch.setattr(v, "check_health", health)
    return v, moon, clock


def run_print(v, moon, clock, p, frames):
    v.p_next = p
    for _ in range(frames):
        clock.t += 10
        asyncio.run(v.tick())
