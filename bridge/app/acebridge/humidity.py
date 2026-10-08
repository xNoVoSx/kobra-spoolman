"""Feuchte-Verlauf der ACE und jede Trocknung als Eintrag.

Quelle: ACE-Treiber (ace_instance_0 im bestehenden Abo, acemodel.dryer) - am Drucker kommt nichts dazu.
- Verlauf: ein Punkt pro Minute (Feuchte, Ist-/Soll-Temperatur, trocknet) in DATA_DIR/humidity/<Tag>.jsonl,
  aelter als cfg.humidity_days wird geloescht.
- Trocknungen: erkannt am Zustand der ACE (also auch, wenn am Display oder in Mainsail gestartet). Was die Bridge
  selbst ausgeloest hat, meldet dryer.py mit Ausloeser und Grund (note_start/note_stop) - das landet im Eintrag.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from .dryer import hub_state

if TYPE_CHECKING:
    from .config import Config
    from .moonraker import Moonraker

log = logging.getLogger("humidity")

POINT_EVERY_S = 60
SESSIONS_KEPT = 300
NOTE_VALID_S = 180            # so lange gilt ein "Bridge hat gestartet/gestoppt"-Hinweis


class HumidityLog:
    def __init__(self, cfg: "Config", moon: "Moonraker", clock: Callable[[], float] = time.time):
        self.cfg = cfg
        self.moon = moon
        self.clock = clock
        self.dir = os.path.join(cfg.data_dir, "humidity")
        self.sessions: List[Dict[str, Any]] = []
        self.open: Optional[Dict[str, Any]] = None
        self._last_point = 0.0
        self._pending_start: Optional[Dict[str, Any]] = None
        self._pending_stop: Optional[Dict[str, Any]] = None
        self._last_day_cleanup = ""
        self._seen_hub = False                     # erster Stand nach dem Start der Bridge
        self.spools_in_ace: Callable[[], List[Dict[str, Any]]] = lambda: []    # setzt die Bridge
        self._load()

    # ------------------------------------------------------------ Speichern
    def _sessions_path(self) -> str:
        return os.path.join(self.dir, "sessions.json")

    def _load(self) -> None:
        try:
            with open(self._sessions_path(), encoding="utf-8") as f:
                data = json.load(f)
            self.sessions = list(data.get("sessions", []))[-SESSIONS_KEPT:]
            self.open = data.get("open")
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            log.warning("humidity/sessions.json unlesbar: %s", e)

    def _save(self) -> None:
        os.makedirs(self.dir, exist_ok=True)
        tmp = self._sessions_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"sessions": self.sessions[-SESSIONS_KEPT:], "open": self.open}, f)
        os.replace(tmp, self._sessions_path())

    def _day(self, t: float) -> str:
        return time.strftime("%Y-%m-%d", time.localtime(t))

    def _append_point(self, t: float, hub: Dict[str, Any]) -> None:
        os.makedirs(self.dir, exist_ok=True)
        p = [round(t), hub["humidity"], hub["temp"], hub["target_temp"] or 0, 1 if hub["drying"] else 0]
        with open(os.path.join(self.dir, self._day(t) + ".jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(p) + "\n")

    def cleanup(self) -> int:
        """Tagesdateien aelter als humidity_days loeschen."""
        if not os.path.isdir(self.dir):
            return 0
        keep_from = self._day(self.clock() - self.cfg.humidity_days * 86400)
        removed = 0
        for name in os.listdir(self.dir):
            if name.endswith(".jsonl") and name[:-6] < keep_from:
                os.remove(os.path.join(self.dir, name))
                removed += 1
        return removed

    # ------------------------------------------------------------ Hinweise von dryer.py
    def note_start(self, source: str, temp: int, hours: float, reason: str = "") -> None:
        self._pending_start = {"at": self.clock(), "source": source, "temp": temp, "hours": hours, "reason": reason}

    def note_stop(self, source: str, reason: str = "") -> None:
        self._pending_stop = {"at": self.clock(), "source": source, "reason": reason}

    def _fresh(self, note: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        return note if note and self.clock() - note["at"] <= NOTE_VALID_S else None

    # ------------------------------------------------------------ Ablauf
    def tick(self) -> None:
        """Jede Sekunde (Ticker): Punkt pro Minute, Beginn/Ende einer Trocknung."""
        hub = hub_state(self.moon.status)
        if not hub["present"] or hub["humidity"] is None:
            return
        now = self.clock()
        if now - self._last_point >= POINT_EVERY_S:
            self._last_point = now
            try:
                self._append_point(now, hub)
            except OSError as e:
                log.warning("Feuchte-Punkt nicht gespeichert: %s", e)
            day = self._day(now)
            if day != self._last_day_cleanup:
                self._last_day_cleanup = day
                self.cleanup()
        first, self._seen_hub = not self._seen_hub, True
        if hub["drying"] and self.open is None:
            self._begin(now, hub, already=first)
        elif not hub["drying"] and self.open is not None:
            self._end(now, hub)
        elif hub["drying"] and self.open is not None:
            o = self.open                              # Soll-Temperatur kann sich aendern (Bridge senkt sie)
            if hub["target_temp"] and hub["target_temp"] != o["temps"][-1][1]:
                o["temps"].append([round(now), hub["target_temp"]])
                self._save()

    def _begin(self, now: float, hub: Dict[str, Any], already: bool = False) -> None:
        note = self._fresh(self._pending_start)
        self._pending_start = None
        if already and not note:                   # lief schon, als die Bridge gestartet ist: Ursprung unbekannt
            note = {"source": "unbekannt", "reason": "lief schon beim Start der Bridge"}
        self.open = {"id": uuid.uuid4().hex[:10], "start": round(now), "temps": [[round(now), hub["target_temp"]]],
                     "planned_min": hub["duration_min"], "humidity_start": hub["humidity"],
                     "source": note["source"] if note else "drucker",
                     "reason": note["reason"] if note else "am Display oder in Mainsail gestartet",
                     "spools": self.spools_in_ace()}
        self._save()
        log.info("Trocknung begonnen: %s °C, %s", hub["target_temp"], self.open["reason"])

    def _end(self, now: float, hub: Dict[str, Any]) -> None:
        o, self.open = self.open, None
        note = self._fresh(self._pending_stop)
        self._pending_stop = None
        dur_min = (now - o["start"]) / 60
        if note:
            end = note["reason"] or {"auto": "Ziel erreicht", "hand": "von Hand gestoppt"}.get(note["source"], note["source"])
        elif o.get("planned_min") and dur_min >= o["planned_min"] - 3:
            end = "Laufzeit um"
        else:
            end = "beendet (Display, Neustart oder Fehler)"
        o.update({"end": round(now), "minutes": round(dur_min), "humidity_end": hub["humidity"], "end_reason": end})
        self.sessions.append(o)
        self.sessions = self.sessions[-SESSIONS_KEPT:]
        self._save()
        log.info("Trocknung beendet nach %d min: %s (Feuchte %s → %s %%)", o["minutes"], end, o["humidity_start"],
                 o["humidity_end"])

    # ------------------------------------------------------------ Lesen
    def points(self, hours: float, max_points: int = 1500) -> List[List[Any]]:
        """Punkte der letzten Stunden, auf hoechstens max_points verdichtet (Mittel je Abschnitt, trocknet = max)."""
        now = self.clock()
        since = now - hours * 3600
        out: List[List[Any]] = []
        if not os.path.isdir(self.dir):
            return out
        days = sorted(n for n in os.listdir(self.dir) if n.endswith(".jsonl") and n[:-6] >= self._day(since))
        for name in days:
            try:
                with open(os.path.join(self.dir, name), encoding="utf-8") as f:
                    for line in f:
                        try:
                            p = json.loads(line)
                        except ValueError:
                            continue
                        if p[0] >= since:
                            out.append(p)
            except OSError:
                continue
        if len(out) <= max_points:
            return out
        def avg(chunk: List[List[Any]], k: int) -> Optional[float]:
            vals = [c[k] for c in chunk if c[k] is not None]
            return round(sum(vals) / len(vals), 1) if vals else None

        step = len(out) / max_points
        dense = []
        for i in range(max_points):
            chunk = out[int(i * step):int((i + 1) * step)] or [out[int(i * step)]]
            dense.append([chunk[len(chunk) // 2][0], avg(chunk, 1), avg(chunk, 2), max(c[3] for c in chunk),
                          max(c[4] for c in chunk)])
        return dense

    def recent_sessions(self, hours: Optional[float] = None) -> List[Dict[str, Any]]:
        since = self.clock() - hours * 3600 if hours else 0
        out = [s for s in self.sessions if s["end"] >= since]
        if self.open:
            out.append({**self.open, "running": True})
        return out[::-1]
