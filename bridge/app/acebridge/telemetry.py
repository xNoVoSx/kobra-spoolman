"""Telemetrie: Rohdaten jedes Drucks als JSONL.

Zeichnet waehrend eines Drucks die Aenderungen von mmu / print_stats / virtual_sdcard auf.
Moonraker reicht nur noch echte Aenderungen weiter, die Dateien bleiben dadurch klein.
Die Verbrauchsrechnung macht allein usage.py - hier stehen nur Rohdaten fuer Fehlersuche
und Nachrechnen. Es bleiben die letzten TELEMETRY_KEEP Drucke erhalten.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict, IO, List, Optional

from .config import Config
from .usage import active_gate

log = logging.getLogger("telemetry")

PRINTING_STATES = ("printing", "paused")
FLUSH_INTERVAL_S = 2.0
TAIL_AFTER_END_S = 30.0


class Recorder:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.dir = os.path.join(cfg.data_dir, "telemetry")
        os.makedirs(self.dir, exist_ok=True)
        self._fh: Optional[IO[str]] = None
        self._path: Optional[str] = None
        self._buffer: Dict[str, Dict[str, Any]] = {}
        self._last_flush = 0.0
        self._end_at: Optional[float] = None
        self._start = 0.0
        self._used_start: Optional[float] = None
        self._used_updates = 0
        self._gate_changes: List[Dict[str, Any]] = []
        self._last_gate: Optional[int] = None

    # ------------------------------------------------------------------ Datei
    def _open(self, status: Dict[str, Dict[str, Any]]) -> None:
        fname = (status.get("print_stats", {}) or {}).get("filename") or "unbekannt"
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(fname))[:80]
        self._path = os.path.join(self.dir, time.strftime("%Y-%m-%d_%H-%M-%S_") + safe + ".jsonl")
        self._fh = open(self._path, "w", encoding="utf-8")
        self._start = time.time()
        self._write({"t": 0, "type": "start", "status": status})
        self._used_start = (status.get("print_stats", {}) or {}).get("filament_used")
        self._used_updates = 0
        self._gate_changes = []
        self._last_gate = active_gate(status.get("mmu", {}) or {})
        log.info("Telemetrie-Aufzeichnung gestartet: %s", os.path.basename(self._path))
        self._prune()

    def _prune(self) -> None:
        keep = max(1, self.cfg.telemetry_keep)
        files = sorted(n for n in os.listdir(self.dir) if n.endswith(".jsonl"))
        for name in files[:-keep]:
            path = os.path.join(self.dir, name)
            if path != self._path:
                try:
                    os.remove(path)
                    log.info("Telemetrie aufgeraeumt: %s", name)
                except OSError:
                    pass

    def _write(self, obj: Dict[str, Any]) -> None:
        if self._fh:
            self._fh.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")

    def _flush(self, force: bool = False) -> None:
        now = time.time()
        if self._buffer and (force or now - self._last_flush >= FLUSH_INTERVAL_S):
            self._write({"t": round(now - self._start, 2), "type": "delta", "d": self._buffer})
            self._buffer = {}
            self._last_flush = now
            if self._fh:
                self._fh.flush()

    def _close(self, status: Dict[str, Dict[str, Any]]) -> None:
        self._flush(force=True)
        ps = status.get("print_stats", {}) or {}
        self._write({
            "type": "summary",
            "end_state": ps.get("state"),
            "duration_s": round(time.time() - self._start, 1),
            "filament_used_start": self._used_start,
            "filament_used_end": ps.get("filament_used"),
            "filament_used_updates": self._used_updates,
            "gate_changes": self._gate_changes,
            "note": "Verbrauch pro Slot: siehe /api/jobs",
        })
        if self._fh:
            self._fh.close()
        log.info("Telemetrie beendet: %s", os.path.basename(self._path or ""))
        self._fh, self._path, self._end_at = None, None, None

    # ------------------------------------------------------------------ Eingang
    def on_status(self, delta: Dict[str, Any], full: bool, status: Dict[str, Dict[str, Any]]) -> None:
        if not self.cfg.telemetry:
            return
        state = (status.get("print_stats", {}) or {}).get("state", "")

        if self._fh is None:
            if state in PRINTING_STATES:
                self._open(status)
            return

        ps_delta = delta.get("print_stats") if isinstance(delta.get("print_stats"), dict) else {}
        if "filament_used" in ps_delta:
            self._used_updates += 1
        mmu_delta = delta.get("mmu") if isinstance(delta.get("mmu"), dict) else None
        if mmu_delta is not None:
            gate = active_gate(status.get("mmu", {}) or {})
            if gate != self._last_gate:
                self._gate_changes.append({"t": round(time.time() - self._start, 1), "from": self._last_gate,
                                           "to": gate,
                                           "filament_used": (status.get("print_stats", {}) or {}).get("filament_used")})
                self._last_gate = gate

        for obj, fields in delta.items():
            if isinstance(fields, dict):
                self._buffer.setdefault(obj, {}).update(fields)
        # mmu-Aenderungen und Statuswechsel sofort, alles andere gedrosselt
        self._flush(force=mmu_delta is not None or "state" in ps_delta or full)

        if state in PRINTING_STATES:
            self._end_at = None
        elif self._end_at is None:
            self._end_at = time.time() + TAIL_AFTER_END_S
        elif time.time() >= self._end_at:
            self._close(status)

    def tick(self, status: Dict[str, Dict[str, Any]]) -> None:
        """Regelmaessig aufrufen, damit die Nachlaufzeit auch ohne neue Updates endet."""
        if self._fh is not None:
            self._flush()
            if self._end_at is not None and time.time() >= self._end_at:
                self._close(status)

    # ------------------------------------------------------------------ API
    def list_files(self) -> List[Dict[str, Any]]:
        out = []
        for name in sorted(os.listdir(self.dir), reverse=True):
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(self.dir, name)
            summary = None
            try:
                with open(path, "rb") as f:
                    f.seek(max(0, os.path.getsize(path) - 65536))
                    last = f.read().decode("utf-8", "replace").strip().splitlines()[-1]
                obj = json.loads(last)
                if obj.get("type") == "summary":
                    summary = obj
            except Exception:  # noqa: BLE001
                pass
            out.append({"name": name, "size": os.path.getsize(path),
                        "recording": path == self._path, "summary": summary})
        return out

    def path_for(self, name: str) -> Optional[str]:
        if "/" in name or "\\" in name or not name.endswith(".jsonl"):
            return None
        p = os.path.join(self.dir, name)
        return p if os.path.isfile(p) else None
