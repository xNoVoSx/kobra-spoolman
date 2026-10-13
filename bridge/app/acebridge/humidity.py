"""Humidity history of the ACE and every drying run as an entry.

Source: ACE driver (ace_instance_0 in the existing subscription, acemodel.dryer) - nothing extra on the printer.
- History: one point per minute (humidity, actual/target temperature, drying) in DATA_DIR/humidity/<day>.jsonl,
  older than cfg.humidity_days is deleted.
- Drying runs: detected from the ACE state (so also when started on the display or in Mainsail). What the bridge
  started itself, dryer.py reports with trigger and reason (note_start/note_stop) - that goes into the entry.
  Trigger keys (stable API codes, translated by web and app): auto, hand, plan, spule (spool inserted),
  drucker (display/Mainsail), unbekannt (already running).
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from .dryer import hub_state
from .i18n import tr
from .storage import save_json

if TYPE_CHECKING:
    from .config import Config
    from .moonraker import Moonraker

log = logging.getLogger("humidity")

POINT_EVERY_S = 60
SESSIONS_KEPT = 300
NOTE_VALID_S = 180            # a "the bridge started/stopped it" note is valid this long
# lid check: closed, the ACE 2 Pro reaches 52 °C after 18 min and 57 °C after 28 min (10.10.); with the lid open it
# stayed at 44 °C for over an hour (13.10.). Suspect after LID_GRACE_S at least LID_BELOW_C under the target for
# LID_WINDOW_S in a row.
LID_GRACE_S = 30 * 60
LID_WINDOW_S = 5 * 60
LID_BELOW_C = 10.0


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
        self._seen_hub = False                     # first state after the bridge started
        self.spools_in_ace: Callable[[], List[Dict[str, Any]]] = lambda: []    # set by the bridge
        self._load()

    # ------------------------------------------------------------ storage
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
            log.warning("humidity/sessions.json unreadable: %s", e)

    def _save(self) -> None:
        os.makedirs(self.dir, exist_ok=True)
        save_json(self._sessions_path(), {"sessions": self.sessions[-SESSIONS_KEPT:], "open": self.open})

    def _day(self, t: float) -> str:
        return time.strftime("%Y-%m-%d", time.localtime(t))

    def _append_point(self, t: float, hub: Dict[str, Any]) -> None:
        os.makedirs(self.dir, exist_ok=True)
        p = [round(t), hub["humidity"], hub["temp"], hub["target_temp"] or 0, 1 if hub["drying"] else 0]
        with open(os.path.join(self.dir, self._day(t) + ".jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(p) + "\n")

    def cleanup(self) -> int:
        """Delete day files older than humidity_days."""
        if not os.path.isdir(self.dir):
            return 0
        keep_from = self._day(self.clock() - self.cfg.humidity_days * 86400)
        removed = 0
        for name in os.listdir(self.dir):
            if name.endswith(".jsonl") and name[:-6] < keep_from:
                os.remove(os.path.join(self.dir, name))
                removed += 1
        return removed

    # ------------------------------------------------------------ notes from dryer.py
    def note_start(self, source: str, temp: int, hours: float, reason: str = "") -> None:
        self._pending_start = {"at": self.clock(), "source": source, "temp": temp, "hours": hours, "reason": reason}

    def note_stop(self, source: str, reason: str = "") -> None:
        self._pending_stop = {"at": self.clock(), "source": source, "reason": reason}

    def _fresh(self, note: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        return note if note and self.clock() - note["at"] <= NOTE_VALID_S else None

    # ------------------------------------------------------------ flow
    def tick(self) -> None:
        """Every second (ticker): one point per minute, start/end of a drying run."""
        hub = hub_state(self.moon.status)
        if not hub["present"] or hub["humidity"] is None:
            return
        now = self.clock()
        if now - self._last_point >= POINT_EVERY_S:
            self._last_point = now
            try:
                self._append_point(now, hub)
            except OSError as e:
                log.warning("Humidity point not saved: %s", e)
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
            o = self.open                              # the target may change (the bridge lowers it)
            if hub["target_temp"] and hub["target_temp"] != o["temps"][-1][1]:
                o["temps"].append([round(now), hub["target_temp"]])
                self._save()
            if getattr(self.cfg, "dryer_lid_check", True):
                self._lid(now, hub)

    def _lid(self, now: float, hub: Dict[str, Any]) -> None:
        """Does the ACE reach its drying temperature? If not (lid open, ...): mark the run, the message comes from
        lid_open(); the minutes stay in the entry (lid_minutes) - such a run is a candidate for "discard"."""
        o = self.open
        temp, target = hub.get("temp"), hub.get("target_temp")
        low = temp is not None and bool(target) and temp < target - LID_BELOW_C
        if low:
            o.setdefault("low_since", round(now))
            if (now - o["start"] >= LID_GRACE_S and now - o["low_since"] >= LID_WINDOW_S
                    and not o.get("lid_open_now")):
                o["lid_open_now"] = True
                o.setdefault("lid_since", o["low_since"])
                log.warning("Dryer: %s °C instead of %s °C for %d min - lid open?", temp, target,
                            (now - o["low_since"]) / 60)
                self._save()
        elif "low_since" in o:
            since = o.pop("low_since")
            if o.pop("lid_open_now", False):
                o["lid_minutes"] = round(o.get("lid_minutes", 0) + (now - since) / 60)
                log.info("Dryer: temperature reached again (%s °C)", temp)
            self._save()

    def lid_open(self) -> Optional[Dict[str, Any]]:
        """Running run that does not reach its temperature right now: {since, temp, target}, else None."""
        o = self.open
        if not o or not o.get("lid_open_now"):
            return None
        hub = hub_state(self.moon.status)
        return {"since": o.get("low_since"), "temp": hub.get("temp"), "target": hub.get("target_temp")}

    def discard(self, sid: str) -> Dict[str, Any]:
        """Mark an ended run as "did not dry"; the moisture model goes back for its spools (done by the caller)."""
        s = next((x for x in self.sessions if x.get("id") == sid), None)
        if s is None:
            if self.open and self.open.get("id") == sid:
                raise ValueError(tr("The drying run is still running – stop it first"))
            raise KeyError(tr("Drying run not found"))
        s["discarded"] = round(self.clock())
        self._save()
        return s

    def _begin(self, now: float, hub: Dict[str, Any], already: bool = False) -> None:
        note = self._fresh(self._pending_start)
        self._pending_start = None
        if already and not note:                   # was already running when the bridge started: origin unknown
            note = {"source": "unbekannt", "reason": tr("was already running when the bridge started")}
        self.open = {"id": uuid.uuid4().hex[:10], "start": round(now), "temps": [[round(now), hub["target_temp"]]],
                     "planned_min": hub["duration_min"], "humidity_start": hub["humidity"],
                     "source": note["source"] if note else "drucker",
                     "reason": note["reason"] if note else tr("started on the display or in Mainsail"),
                     "spools": self.spools_in_ace()}
        self._save()
        log.info("Drying started: %s °C, %s", hub["target_temp"], self.open["reason"])

    def _end(self, now: float, hub: Dict[str, Any]) -> None:
        o, self.open = self.open, None
        note = self._fresh(self._pending_stop)
        self._pending_stop = None
        dur_min = (now - o["start"]) / 60
        if note:
            end = note["reason"] or {"auto": tr("target reached"),
                                     "hand": tr("stopped by hand")}.get(note["source"], note["source"])
        elif o.get("planned_min") and dur_min >= o["planned_min"] - 3:
            end = tr("time is up")
        else:
            end = tr("ended (display, restart or error)")
        if o.pop("lid_open_now", False) and "low_since" in o:
            o["lid_minutes"] = round(o.get("lid_minutes", 0) + (now - o["low_since"]) / 60)
        o.pop("low_since", None)
        o.update({"end": round(now), "minutes": round(dur_min), "humidity_end": hub["humidity"], "end_reason": end})
        self.sessions.append(o)
        self.sessions = self.sessions[-SESSIONS_KEPT:]
        self._save()
        log.info("Drying ended after %d min: %s (humidity %s → %s %%)", o["minutes"], end, o["humidity_start"],
                 o["humidity_end"])

    # ------------------------------------------------------------ reading
    def points(self, hours: float, max_points: int = 1500) -> List[List[Any]]:
        """Points of the last hours, condensed to at most max_points (mean per section, drying = max)."""
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
