"""Telemetry: raw data of every print as JSONL.

Records all subscribed changes during a print (ACE driver, print_stats, virtual_sdcard ...). Moonraker passes on only
real changes, so the files stay small. The consumption calculation is done by usage.py alone - here are only raw data
for debugging and recalculating. The last TELEMETRY_KEEP prints are kept.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict, IO, List, Optional

from . import acemodel
from .config import Config

log = logging.getLogger("telemetry")

PRINTING_STATES = ("printing", "paused")
FLUSH_INTERVAL_S = 2.0
TAIL_AFTER_END_S = 30.0
TEMP_REPORT = re.compile(r"^(ok\s*)?(B|T\d?):\s*-?\d")   # "B:112.0 /110.0 T0:..." (M105-Antworten)


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

    # ------------------------------------------------------------------ file
    def _open(self, status: Dict[str, Dict[str, Any]]) -> None:
        fname = (status.get("print_stats", {}) or {}).get("filename") or "unknown"
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(fname))[:80]
        self._path = os.path.join(self.dir, time.strftime("%Y-%m-%d_%H-%M-%S_") + safe + ".jsonl")
        self._fh = open(self._path, "w", encoding="utf-8")
        self._start = time.time()
        self._write({"t": 0, "type": "start", "at": round(self._start, 3), "status": status})
        self._used_start = (status.get("print_stats", {}) or {}).get("filament_used")
        self._used_updates = 0
        self._gate_changes = []
        self._last_gate = acemodel.active_slot(status)
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
            "note": "consumption per slot: see /api/jobs",
        })
        if self._fh:
            self._fh.close()
        log.info("Telemetrie beendet: %s", os.path.basename(self._path or ""))
        self._fh, self._path, self._end_at = None, None, None

    # ------------------------------------------------------------------ input
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
        ace_delta = delta.get("ace") if isinstance(delta.get("ace"), dict) else None
        if ace_delta is not None:
            gate = acemodel.active_slot(status)
            if gate != self._last_gate:
                self._gate_changes.append({"t": round(time.time() - self._start, 1), "from": self._last_gate,
                                           "to": gate,
                                           "filament_used": (status.get("print_stats", {}) or {}).get("filament_used")})
                self._last_gate = gate

        for obj, fields in delta.items():
            if isinstance(fields, dict):
                self._buffer.setdefault(obj, {}).update(fields)
        # tool changes (object ace) and state changes at once, everything else throttled
        self._flush(force=ace_delta is not None or "state" in ps_delta or full)

        if state in PRINTING_STATES:
            self._end_at = None
        elif self._end_at is None:
            self._end_at = time.time() + TAIL_AFTER_END_S
        elif time.time() >= self._end_at:
            self._close(status)

    def on_console(self, entry: Dict[str, Any]) -> None:
        """Console line (G-code answer, sent command, error) into the running recording - without the temperature
        reports every second."""
        if self._fh is None or TEMP_REPORT.match(entry.get("text") or ""):
            return
        self._flush(force=True)                     # order: first the states before
        self._write({"t": round(float(entry.get("time") or time.time()) - self._start, 2), "type": "console",
                     "kind": entry.get("kind"), "text": entry.get("text"), "source": entry.get("source")})

    def tick(self, status: Dict[str, Dict[str, Any]]) -> None:
        """Call regularly so the trailing time also ends without new updates."""
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
