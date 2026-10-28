"""ACE dryer: display, manual control and automation by humidity.

Data comes from the ACE driver (acemodel.dryer: ACEPRO's ace_instance_0, or GoKlipper's filament_hub under Rinkhals).
Control via acemodel's commands: ACE_START_DRYING TEMP= DURATION=<minutes> / ACE_STOP_DRYING (ACEPRO), MMU_DRYER_START
UNIT=0 DURATION=<minutes> TEMP= / MMU_DRYER_STOP UNIT=0 (Rinkhals).

Runs:
- by hand, scheduled or after a damp spool was inserted: runs until the chosen time, however dry the ACE already is.
  If the ACE ends it early by itself, the bridge restarts it with the remaining time (at most MAX_RESTARTS times).
  Only a manual stop ends it early.
- automation: starts only when the humidity stays above the threshold for start_delay_minutes in a row (lid open ->
  a short spike starts nothing); stops at <= stop_below.

Temperature: never higher than the most sensitive loaded filament tolerates - value on the filament (extra field
dry_temp), else on its template, else a cautious start value per material - and never higher than the ACE can do
(ACE Pro 55 degC, ACE 2 Pro 65 degC) or the driver allows (ACEPRO's max_dryer_temperature, default 60, read from
Klipper's configfile). If the driver still refuses a start ("Temp 65°C out of range, skipping" on the console), the
run ends at once with a clear event, nothing restarts and the automation waits until Klipper restarts (2026-10-28:
ACEPRO refused 65 degC for ASA, the bridge took it for "the ACE stopped early" and retried every hour).
Run sources (stable API codes): hand, plan, spule (spool inserted), auto.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from . import acemodel
from .i18n import tr
from .profiles import find_template
from .slots import base_type
from .spoolman import extra_value
from .storage import save_json

if TYPE_CHECKING:
    from .config import Config
    from .moonraker import Moonraker
    from .slots import SlotManager

log = logging.getLogger("dryer")

# start values from the dryer makers' data (Bambu, Sunlu, Polymaker), a little below their upper limit;
# PETG stays at 60 because Sunlu PETG can stick together on the spool at 65 degC over hours.
# Changeable in Spoolman per material/filament (extra field dry_temp)
DEFAULT_DRY_TEMP = {
    "PLA": 55, "PLA-CF": 55, "TPU": 55, "PEBA": 55, "PVA": 50, "BVOH": 50,
    "PETG": 60, "PET": 60, "PCTG": 60, "HIPS": 60,
    "PETG-CF": 65, "PET-CF": 65, "ABS": 65, "ABS-GF": 65, "ASA": 65, "ASA-CF": 65,
    "PA": 65, "PA-CF": 65, "PA6-CF": 65, "PC": 65, "PPS": 65,
}
FALLBACK_DRY_TEMP = 50          # unknown material: more cautious than PLA
# after a command wait briefly until the driver reports the new state
COMMAND_SETTLE_S = 15
COMMAND_SETTLE_RINKHALS_S = 90     # GoKlipper reports the ACE only about every 20 s
# run by hand/plan/insert: restart this often when the ACE stops early; remaining time below: done
MAX_RESTARTS = 3
MIN_REST_MIN = 5
# ACEPRO's answer when TEMP is above its max_dryer_temperature (commands.py ACE_START_DRYING)
REFUSED = re.compile(r"ACE\[\d+\]: Temp (\d+(?:\.\d+)?)°C out of range")
LIMIT_RETRY_S = 60


def ace_max_temp(model: Optional[str]) -> int:
    """ACE 2 Pro dries up to 65 degC, the first ACE Pro up to 55 degC (ACEPRO reports e.g. "ACE2 (USB Single Serial)")."""
    m = (model or "").lower().replace(" ", "")
    return 65 if ("ace2" in m or "2.0" in m) else 55


def dryer_error(status: Any) -> Optional[str]:
    """The ACE reports a dryer fault (13.10. on the real ACE 2 Pro: "PTC_err" - heater, right after the lid was
    closed on a run that had been open for 80 min). Any status with "err" in it counts; None = no fault."""
    s = str(status or "")
    return s if "err" in s.lower() else None


def hub_state(status: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """ACE dryer for display (acemodel.dryer). present=False without a connected ACE."""
    d = acemodel.dryer(status)
    remaining = d.get("remaining_min")
    duration = d.get("duration_min")
    return {
        "present": d["present"],
        "model": d.get("model"),
        "humidity": d.get("humidity"),
        "temp": d.get("temp"),
        "status": d["status"],
        "error": dryer_error(d["status"]),          # dryer fault reported by the ACE, else None
        "drying": d["drying"],
        "target_temp": d.get("target_temp") or None,
        "duration_min": round(duration) if duration else None,
        "remaining_min": round(remaining) if remaining else None,      # app: whole minutes
    }


def filament_dry_temp(fil: Dict[str, Any], templates: List[Dict[str, Any]]) -> tuple:
    """(temperature, source) for a filament: on the filament, on the template, else the start value per material.
    Source codes (stable API): filament, vorlage (template), standard."""
    v = extra_value(fil, "dry_temp")
    if v not in (None, ""):
        return int(float(v)), "filament"
    tpl = find_template(fil, templates)
    if tpl is not None and extra_value(tpl, "dry_temp") not in (None, ""):
        return int(float(extra_value(tpl, "dry_temp"))), "vorlage"
    mat = base_type(fil.get("material") or (tpl or {}).get("material") or "").upper()
    return DEFAULT_DRY_TEMP.get(mat, FALLBACK_DRY_TEMP), "standard"


@dataclass
class DryerConfig:
    enabled: bool = False
    start_above: float = 20.0       # humidity % from which the automation starts
    stop_below: float = 10.0        # humidity % at which it stops
    max_hours: float = 6.0          # longest run time per run (the ACE stops by itself then)
    pause_minutes: float = 60.0     # minimum pause after a run (against on/off flapping)
    while_printing: bool = True
    start_delay_minutes: float = 15.0   # the humidity must stay above start_above this long

    def validate(self) -> None:
        if not 0 <= self.stop_below < self.start_above <= 100:
            raise ValueError(tr("Must hold: 0 <= stop humidity < start humidity <= 100"))
        if not 0.5 <= self.max_hours <= 24:
            raise ValueError(tr("Run time 0.5 to 24 hours"))
        if not 0 <= self.pause_minutes <= 24 * 60:
            raise ValueError(tr("Pause 0 to 1440 minutes"))
        if not 0 <= self.start_delay_minutes <= 240:
            raise ValueError(tr("Delay 0 to 240 minutes"))


class Dryer:
    def __init__(self, cfg: "Config", moon: "Moonraker", slots: "SlotManager",
                 clock: Callable[[], float] = time.time):
        self.cfg = cfg
        self.moon = moon
        self.slots = slots
        self.clock = clock
        self.path = os.path.join(cfg.data_dir, "dryer.json")
        self.config = DryerConfig()
        self.auto_run = False           # is a run going that the automation started?
        self.pause_until = 0.0
        self.last_event: Optional[Dict[str, Any]] = None
        self.schedule: Optional[Dict[str, Any]] = None   # scheduled start: {"at": epoch, "temp", "hours"}
        # running run: {"source", "until": epoch, "temp", "restarts"} - also across a bridge restart
        self.run: Optional[Dict[str, Any]] = None
        self._above_since: Optional[float] = None         # since when the humidity is above start_above in a row
        self._busy = False
        self._error_told: Optional[str] = None        # dryer fault already reported
        self._last_cmd_at = -1e12
        # ACEPRO's max_dryer_temperature (None = unknown / not ACEPRO); read once per Klipper session
        self.driver_max: Optional[int] = None
        self._limit_read = False
        self._limit_tried_at = -1e12
        # the driver refused the last start: {"temp", "at"} - blocks the automation until Klipper restarts
        self.refused: Optional[Dict[str, Any]] = None
        self._load()

    # ------------------------------------------------------------ state
    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            self.config = DryerConfig(**{k: v for k, v in (data.get("config") or {}).items()
                                         if k in DryerConfig.__dataclass_fields__})
            self.config.validate()
            sched = data.get("schedule")
            if isinstance(sched, dict) and isinstance(sched.get("at"), (int, float)):
                self.schedule = sched
            run = data.get("run")
            if isinstance(run, dict) and isinstance(run.get("until"), (int, float)):
                self.run = run
                self.auto_run = run.get("source") == "auto"
        except FileNotFoundError:
            pass
        except Exception as e:  # noqa: BLE001
            log.warning("dryer.json unreadable, using defaults: %s", e)
            self.config = DryerConfig()

    def _save(self) -> None:
        save_json(self.path, {"config": asdict(self.config), "schedule": self.schedule, "run": self.run}, indent=1)

    def set_config(self, changes: Dict[str, Any]) -> DryerConfig:
        data = asdict(self.config)
        for k, v in changes.items():
            if k not in data:
                raise ValueError(tr("Unknown setting {key}", key=k))
            data[k] = bool(v) if isinstance(data[k], bool) else float(v)
        new = DryerConfig(**data)
        new.validate()
        self.config = new
        self._save()
        log.info("Dryer automation: %s", asdict(new))
        return new

    def set_schedule(self, at: float, temp: Optional[float] = None, hours: Optional[float] = None) -> Dict[str, Any]:
        """Schedule a one-off start (time in seconds since 1970). Temperature, like a manual start, never above the
        most sensitive loaded filament; empty = automatic."""
        now = self.clock()
        if at <= now:
            raise ValueError(tr("The time must be in the future"))
        if at > now + 7 * 86400:
            raise ValueError(tr("At most one week ahead"))
        if hours is not None and not 0.5 <= float(hours) <= 24:
            raise ValueError(tr("Run time 0.5 to 24 hours"))
        if temp is not None and not 20 <= float(temp) <= 90:
            raise ValueError(tr("Temperature 20 to 90 °C"))
        self.schedule = {"at": float(at), "temp": None if temp is None else float(temp),
                         "hours": None if hours is None else float(hours)}
        self._save()
        log.info("Drying scheduled: %s", time.strftime("%Y-%m-%d %H:%M", time.localtime(at)))
        return self.schedule

    def clear_schedule(self) -> None:
        if self.schedule:
            self.schedule = None
            self._save()
            log.info("Scheduled drying removed")

    def required_temp(self) -> Dict[str, Any]:
        """Highest temperature all loaded filaments tolerate, with the reason."""
        hub = hub_state(self.moon.status)
        cap = ace_max_temp(hub["model"])
        if self.driver_max is not None:
            cap = min(cap, self.driver_max)
        templates = self.slots.sm.templates()
        assigned, _ = self.slots.assignments()
        parts = []
        for gate in range(self.slots.num_gates()):
            ace = self.slots.ace_gate(gate)
            spool = assigned.get(gate + 1)
            fil = (spool or {}).get("filament") or {}
            if fil.get("id"):
                t, src = filament_dry_temp(fil, templates)
                name = f"{(fil.get('vendor') or {}).get('name', '')} {fil.get('name') or ''}".strip()
            elif ace["present"] and ace["material"]:
                mat = base_type(ace["material"]).upper()
                t, src, name = DEFAULT_DRY_TEMP.get(mat, FALLBACK_DRY_TEMP), "standard", ace["material"]
            else:
                continue
            parts.append({"slot": gate + 1, "name": name, "temp": t, "source": src})
        limit = min([p["temp"] for p in parts], default=None)
        return {"temp": None if limit is None else min(limit, cap), "ace_max": cap, "driver_max": self.driver_max,
                "slots": parts,
                "limited_by": [p["slot"] for p in parts if limit is not None and p["temp"] == limit]}

    def state(self) -> Dict[str, Any]:
        sched = None
        if self.schedule:
            sched = {**self.schedule, "at_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.schedule["at"]))}
        return {**hub_state(self.moon.status), "required": self.required_temp(), "config": asdict(self.config),
                "schedule": sched,
                "auto_run": self.auto_run,
                "run": {**self.run, "until_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.run["until"]))}
                if self.run else None,
                "paused_until": self.pause_until if self.pause_until > self.clock() else None,
                "refused": self.refused,
                "last_event": self.last_event}

    def _event(self, text: str) -> None:
        self.last_event = {"at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.clock())), "text": text}
        log.info("Dryer: %s", text)

    # ------------------------------------------------------------ commands
    log_sink: Any = None          # humidity.HumidityLog (set by the bridge): trigger and reason of every drying run

    async def start(self, temp: Optional[float] = None, hours: Optional[float] = None, source: str = "hand",
                    reason: str = "", until: Optional[float] = None, restarts: int = 0) -> Dict[str, Any]:
        """Start the dryer. source: hand / plan / spule / auto. until: keep the end of a running run (restart with the
        remaining time, temperature lowered)."""
        req = self.required_temp()
        if req["temp"] is None and temp is None:
            raise ValueError(tr("No spool loaded - give a temperature"))
        t = int(round(temp if temp is not None else req["temp"]))
        cap = req["temp"] if req["temp"] is not None else req["ace_max"]
        if t > cap:
            t = cap   # never hotter than the most sensitive loaded filament / the ACE
        h = float(hours if hours is not None else self.config.max_hours)
        if not 0.5 <= h <= 24:
            raise ValueError(tr("Run time 0.5 to 24 hours"))
        if source == "hand":
            self.refused = None         # a person tries again: report the driver's answer afresh
        try:
            await self.moon.gcode(acemodel.dryer_start_command(self.moon.status, t, int(round(h * 60))),
                                  source=tr("Dryer"))
        except asyncio.TimeoutError:
            # Klipper is busy (print moves queued): the command is queued and runs later - count it as sent, else
            # the next evaluation sends it again every few seconds (2026-10-28: 6 starts in 90 s while printing)
            log.info("Dryer start queued - Klipper is busy")
        now = self.clock()
        self._last_cmd_at = now
        self.auto_run = source == "auto"
        self.run = {"source": source, "until": until if until is not None else now + h * 3600, "temp": t,
                    "restarts": restarts}
        self._save()
        if self.log_sink is not None:
            self.log_sink.note_start(source, t, h, reason or {"hand": tr("started by hand"),
                                                            "plan": tr("scheduled")}.get(source, source))
        self._event(tr("Start {t} °C for {h:g} h ({source})", t=t, h=h, source=source))
        return {"temp": t, "hours": h}

    async def stop(self, source: str = "hand", reason: str = "") -> None:
        await self.moon.gcode(acemodel.dryer_stop_command(self.moon.status), source=tr("Dryer"))
        if self.log_sink is not None:
            self.log_sink.note_stop(source, reason)
        self._last_cmd_at = self.clock()
        self.auto_run = False
        self.run = None
        self._save()
        self.pause_until = self.clock() + self.config.pause_minutes * 60
        self._event(tr("Stop ({source})", source=source))

    async def ensure(self, hours: float, reason: str) -> bool:
        """Dry at least this long (damp spool inserted). If a drying run that lasts long enough is already going: do
        nothing. Returns: started anew?"""
        hub = hub_state(self.moon.status)
        if not hub["present"]:
            return False
        if hub["drying"] and (hub["remaining_min"] or 0) >= hours * 60 - 5:
            return False
        await self.start(None, max(0.5, min(24.0, hours)), source="spule", reason=reason)
        return True

    def on_console(self, entry: Dict[str, Any]) -> None:
        """Console listener: the driver refused our start (temperature above its limit)."""
        if entry.get("kind") != "response" or entry.get("time", 0) < self._last_cmd_at - 1:
            return              # backlog after a reconnect, or not ours
        m = REFUSED.search(str(entry.get("text") or ""))
        if not m:
            return
        t = int(float(m.group(1)))
        if self.refused and self.refused.get("temp") == t and self.run is None:
            return              # one start, several ACE instances / lines
        self.refused = {"temp": t, "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.clock()))}
        self.run = None
        self.auto_run = False
        self._save()
        self._event(tr("The ACE driver refused {t} °C (ACEPRO allows at most {max}) – not drying. Raise "
                       "max_dryer_temperature in the [ace] section of printer.cfg (ACE 2 Pro: 65) or start lower",
                       t=t, max=self.driver_max if self.driver_max is not None else "?"))

    async def _read_limit(self) -> None:
        """ACEPRO's max_dryer_temperature from Klipper's configfile (includes the default when it is not set)."""
        if self._limit_read or acemodel.variant(self.moon.status) != acemodel.ACEPRO:
            return
        now = self.clock()
        if now - self._limit_tried_at < LIMIT_RETRY_S:
            return
        self._limit_tried_at = now
        try:
            res = await self.moon.query({"configfile": ["settings"]})
        except Exception as e:  # noqa: BLE001
            log.debug("Dryer limit not readable: %s", str(e) or e.__class__.__name__)
            return
        self._limit_read = True
        v = (((res.get("configfile") or {}).get("settings") or {}).get("ace") or {}).get("max_dryer_temperature")
        try:
            self.driver_max = int(float(v)) if v not in (None, "") else None
        except (TypeError, ValueError):
            self.driver_max = None
        if self.driver_max is not None:
            log.info("ACEPRO allows drying up to %s °C (max_dryer_temperature)", self.driver_max)

    # ------------------------------------------------------------ automation
    async def evaluate(self) -> None:
        """On every ACE update and in the ticker. Commands only on state changes."""
        if not self.moon.klippy_ready:
            # Klipper restarts: the config (max_dryer_temperature) may change - read again, forget a refusal
            self._limit_read = False
            self._limit_tried_at = -1e12
            self.driver_max = None
            self.refused = None
            return
        if self._busy:
            return
        hub = hub_state(self.moon.status)
        if not hub["present"]:
            return
        self._busy = True
        try:
            await self._read_limit()
            await self._evaluate(hub)
        except Exception as e:  # noqa: BLE001
            log.warning("Dryer automation: %s", str(e) or e.__class__.__name__)
        finally:
            self._busy = False

    async def _evaluate(self, hub: Dict[str, Any]) -> None:
        now = self.clock()
        c = self.config
        # watch the automation threshold continuously (also during the wait after a command)
        if hub["humidity"] is not None and hub["humidity"] >= c.start_above:
            if self._above_since is None:
                self._above_since = now
        else:
            self._above_since = None
        settle = COMMAND_SETTLE_RINKHALS_S if acemodel.variant(self.moon.status) == acemodel.RINKHALS else COMMAND_SETTLE_S
        if now - self._last_cmd_at < settle:
            return          # the driver has not confirmed the last command yet
        req = self.required_temp()
        if hub["error"] and not hub["drying"]:
            # dryer fault: never start again by itself (no restart, no automation, no schedule) - a person has to
            # look at the ACE first; a start by hand is still possible
            if self.run is not None:
                self.run = None
                self._save()
            if self._error_told != hub["error"]:
                self._error_told = hub["error"]
                self._event(tr("The ACE reports a dryer fault ({code}) – drying stopped, no automatic restart. "
                               "Check the ACE (lid closed, fan free), then start again by hand", code=hub["error"]))
            return
        self._error_told = None
        if hub["drying"]:
            if self.schedule and now >= self.schedule["at"]:
                self.schedule = None
                self._save()
                self._event(tr("Scheduled drying due – the dryer was already running"))
            # safety, also for a manual start: a more sensitive filament was inserted -> lower the temperature
            if req["temp"] is not None and hub["target_temp"] and hub["target_temp"] > req["temp"]:
                run = self.run or {}
                left = (run["until"] - now) / 3600 if run.get("until") else (hub["remaining_min"] or c.max_hours * 60) / 60
                await self.start(req["temp"], max(0.5, min(24.0, left)),
                                 source=run.get("source") or ("auto" if self.auto_run else "hand"),
                                 reason=tr("Temperature lowered to {t} °C (more sensitive spool inserted)",
                                           t=req["temp"]),
                                 until=run.get("until"), restarts=run.get("restarts", 0))
                self._event(tr("Temperature lowered to {t} °C (slot {slots})", t=req["temp"],
                               slots=", ".join(map(str, req["limited_by"]))))
                return
            # only automation runs end at the humidity - by hand / plan / insert run until their time
            if self.auto_run and hub["humidity"] is not None and hub["humidity"] <= c.stop_below:
                await self.stop(source="auto", reason=tr("Target reached: humidity {rh} % ≤ {stop:g} %",
                                                         rh=hub["humidity"], stop=c.stop_below))
            return
        # ---- dryer off
        if self.run is not None and self.run.get("source") != "auto":
            run = self.run
            left_min = (run["until"] - now) / 60
            if left_min >= MIN_REST_MIN and run.get("restarts", 0) < MAX_RESTARTS and req["temp"] is not None:
                await self.start(run.get("temp"), max(0.5, min(24.0, left_min / 60)), source=run["source"],
                                 reason=tr("The ACE had stopped early – continuing for {min:.0f} min", min=left_min),
                                 until=run["until"], restarts=run.get("restarts", 0) + 1)
                self._event(tr("The ACE had stopped early – restarted, {min:.0f} min left", min=left_min))
                return
            self.run = None
            self._save()
            self._event(tr("Run finished") if left_min < MIN_REST_MIN
                        else tr("Run finished (the ACE stopped early several times)"))
        if self.schedule and now >= self.schedule["at"]:
            sched, self.schedule = self.schedule, None
            self._save()
            if req["temp"] is None and sched.get("temp") is None:
                self._event(tr("Scheduled drying skipped: no spool loaded"))
                return
            await self.start(sched.get("temp"), sched.get("hours"), source="plan", reason=tr("scheduled start"))
            return
        if self.auto_run:       # the ACE ended the run by itself (time is up)
            self.auto_run = False
            self.run = None
            self._save()
            self.pause_until = now + c.pause_minutes * 60
            self._event(tr("Run finished (time is up)"))
        if not c.enabled or hub["humidity"] is None or now < self.pause_until or req["temp"] is None:
            return
        if self.refused:
            return              # the driver refuses - starting again every hour would not help
        if not c.while_printing and self.slots.printing:
            return
        if self._above_since is not None and now - self._above_since >= c.start_delay_minutes * 60:
            await self.start(req["temp"], c.max_hours, source="auto",
                             reason=tr("Automation: humidity {rh} % ≥ {start:g} % for {min:g} min",
                                       rh=hub["humidity"], start=c.start_above, min=c.start_delay_minutes))
