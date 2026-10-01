"""ACE-Trockner: Anzeige, Steuerung von Hand und Automatik nach Luftfeuchte.

Daten kommen aus GoKlippers Objekt "filament_hub" (im bestehenden Moonraker-Abo, die ACE meldet
etwa alle 20 s). Rinkhals' eigene mmu-Sicht liefert Feuchte und Restzeit nicht richtig (0), deshalb
direkt von dort. Gesteuert wird ueber Rinkhals' Befehle MMU_DRYER_START / MMU_DRYER_STOP.

Temperatur: nie hoeher, als das empfindlichste eingelegte Filament vertraegt - Wert am Filament
(Zusatzfeld dry_temp), sonst an seiner Vorlage, sonst ein vorsichtiger Startwert je Material - und
nie hoeher als die ACE kann (ACE Pro 55 degC, ACE 2 Pro 65 degC).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from .profiles import find_template
from .slots import base_type
from .spoolman import extra_value

if TYPE_CHECKING:
    from .config import Config
    from .moonraker import Moonraker
    from .slots import SlotManager

log = logging.getLogger("dryer")

# Vorsichtige Startwerte (unterhalb der Erweichung); in Spoolman je Material/Filament aenderbar
DEFAULT_DRY_TEMP = {
    "PLA": 45, "PLA-CF": 50, "TPU": 50, "PEBA": 50, "PVA": 45, "BVOH": 45,
    "PETG": 60, "PET": 60, "PCTG": 60, "HIPS": 60,
    "PETG-CF": 65, "PET-CF": 65, "ABS": 65, "ABS-GF": 65, "ASA": 65, "ASA-CF": 65,
    "PA": 65, "PA-CF": 65, "PA6-CF": 65, "PC": 65, "PPS": 65,
}
FALLBACK_DRY_TEMP = 45          # unbekanntes Material: wie PLA
# Die ACE meldet ihren Zustand nur etwa alle 20 s: nach einem Befehl so lange nichts neu entscheiden
COMMAND_SETTLE_S = 90


def ace_max_temp(model: Optional[str]) -> int:
    """ACE 2 Pro trocknet bis 65 degC, die erste ACE Pro bis 55 degC."""
    m = (model or "").lower()
    return 65 if ("2.0" in m or " 2 " in f" {m} ") else 55


def hub_state(status: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Rohdaten aus filament_hub -> Anzeige. present=False, wenn es keine ACE gibt."""
    hubs = ((status.get("filament_hub") or {}).get("filament_hubs")) or []
    h = hubs[0] if hubs and isinstance(hubs[0], dict) else {}
    ds = h.get("dryer_status") or {}
    return {
        "present": bool(h),
        "model": h.get("filament_model"),
        "humidity": h.get("humidity"),
        "temp": h.get("temp"),
        "status": ds.get("status") or "stop",
        "drying": (ds.get("status") or "stop") == "drying",
        "target_temp": ds.get("target_temp") or None,
        "duration_min": ds.get("duration") or None,
        "remaining_min": ds.get("remain_time") or None,
    }


def filament_dry_temp(fil: Dict[str, Any], templates: List[Dict[str, Any]]) -> tuple:
    """(Temperatur, Quelle) fuer ein Filament: am Filament, an der Vorlage, sonst Startwert je Material."""
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
    start_above: float = 20.0       # Feuchte %, ab der die Automatik startet
    stop_below: float = 10.0        # Feuchte %, bei der sie stoppt
    max_hours: float = 6.0          # laengste Laufzeit pro Durchgang (ACE stoppt dann selbst)
    pause_minutes: float = 60.0     # Mindestpause nach einem Durchgang (gegen An/Aus-Flattern)
    while_printing: bool = True

    def validate(self) -> None:
        if not 0 <= self.stop_below < self.start_above <= 100:
            raise ValueError("Es muss gelten: 0 <= Stopp-Feuchte < Start-Feuchte <= 100")
        if not 0.5 <= self.max_hours <= 24:
            raise ValueError("Laufzeit 0,5 bis 24 Stunden")
        if not 0 <= self.pause_minutes <= 24 * 60:
            raise ValueError("Pause 0 bis 1440 Minuten")


class Dryer:
    def __init__(self, cfg: "Config", moon: "Moonraker", slots: "SlotManager",
                 clock: Callable[[], float] = time.time):
        self.cfg = cfg
        self.moon = moon
        self.slots = slots
        self.clock = clock
        self.path = os.path.join(cfg.data_dir, "dryer.json")
        self.config = DryerConfig()
        self.auto_run = False           # laeuft ein Durchgang, den die Automatik gestartet hat?
        self.pause_until = 0.0
        self.last_event: Optional[Dict[str, Any]] = None
        self.schedule: Optional[Dict[str, Any]] = None   # geplanter Start: {"at": epoch, "temp", "hours"}
        self._busy = False
        self._last_cmd_at = -1e12
        self._load()

    # ------------------------------------------------------------ Zustand
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
        except FileNotFoundError:
            pass
        except Exception as e:  # noqa: BLE001
            log.warning("dryer.json unlesbar, nehme Standardwerte: %s", e)
            self.config = DryerConfig()

    def _save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"config": asdict(self.config), "schedule": self.schedule}, fh, indent=1)
        os.replace(tmp, self.path)

    def set_config(self, changes: Dict[str, Any]) -> DryerConfig:
        data = asdict(self.config)
        for k, v in changes.items():
            if k not in data:
                raise ValueError(f"Unbekannte Einstellung {k}")
            data[k] = bool(v) if isinstance(data[k], bool) else float(v)
        new = DryerConfig(**data)
        new.validate()
        self.config = new
        self._save()
        log.info("Trockner-Automatik: %s", asdict(new))
        return new

    def set_schedule(self, at: float, temp: Optional[float] = None, hours: Optional[float] = None) -> Dict[str, Any]:
        """Einmaligen Start planen (Zeitpunkt in Sekunden seit 1970). Temperatur wie beim Start von Hand
        nie ueber dem empfindlichsten eingelegten Filament; leer = automatisch."""
        now = self.clock()
        if at <= now:
            raise ValueError("Der Zeitpunkt muss in der Zukunft liegen")
        if at > now + 7 * 86400:
            raise ValueError("Höchstens eine Woche im Voraus")
        if hours is not None and not 0.5 <= float(hours) <= 24:
            raise ValueError("Laufzeit 0,5 bis 24 Stunden")
        if temp is not None and not 20 <= float(temp) <= 90:
            raise ValueError("Temperatur 20 bis 90 °C")
        self.schedule = {"at": float(at), "temp": None if temp is None else float(temp),
                         "hours": None if hours is None else float(hours)}
        self._save()
        log.info("Trocknen geplant: %s", time.strftime("%d.%m. %H:%M", time.localtime(at)))
        return self.schedule

    def clear_schedule(self) -> None:
        if self.schedule:
            self.schedule = None
            self._save()
            log.info("Geplantes Trocknen gelöscht")

    def required_temp(self) -> Dict[str, Any]:
        """Hoechste Temperatur, die alle eingelegten Filamente vertragen, mit Begruendung."""
        hub = hub_state(self.moon.status)
        cap = ace_max_temp(hub["model"])
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
        return {"temp": None if limit is None else min(limit, cap), "ace_max": cap, "slots": parts,
                "limited_by": [p["slot"] for p in parts if limit is not None and p["temp"] == limit]}

    def state(self) -> Dict[str, Any]:
        sched = None
        if self.schedule:
            sched = {**self.schedule, "at_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.schedule["at"]))}
        return {**hub_state(self.moon.status), "required": self.required_temp(), "config": asdict(self.config),
                "schedule": sched,
                "auto_run": self.auto_run,
                "paused_until": self.pause_until if self.pause_until > self.clock() else None,
                "last_event": self.last_event}

    def _event(self, text: str) -> None:
        self.last_event = {"at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.clock())), "text": text}
        log.info("Trockner: %s", text)

    # ------------------------------------------------------------ Befehle
    async def start(self, temp: Optional[float] = None, hours: Optional[float] = None, source: str = "hand") -> Dict[str, Any]:
        req = self.required_temp()
        if req["temp"] is None and temp is None:
            raise ValueError("Keine Spule eingelegt - Temperatur angeben")
        t = int(round(temp if temp is not None else req["temp"]))
        cap = req["temp"] if req["temp"] is not None else req["ace_max"]
        if t > cap:
            t = cap   # nie heisser als das empfindlichste eingelegte Filament / die ACE
        h = float(hours if hours is not None else self.config.max_hours)
        if not 0.5 <= h <= 24:
            raise ValueError("Laufzeit 0,5 bis 24 Stunden")
        await self.moon.gcode(f"MMU_DRYER_START UNIT=0 DURATION={int(round(h * 60))} TEMP={t}")
        self._last_cmd_at = self.clock()
        self.auto_run = source == "auto"
        self._event(f"Start {t} °C für {h:g} h ({source})")
        return {"temp": t, "hours": h}

    async def stop(self, source: str = "hand") -> None:
        await self.moon.gcode("MMU_DRYER_STOP UNIT=0")
        self._last_cmd_at = self.clock()
        self.auto_run = False
        self.pause_until = self.clock() + self.config.pause_minutes * 60
        self._event(f"Stopp ({source})")

    # ------------------------------------------------------------ Automatik
    async def evaluate(self) -> None:
        """Bei jedem ACE-Update und im Ticker. Befehle nur bei Zustandswechseln."""
        if self._busy or not self.moon.klippy_ready:
            return
        hub = hub_state(self.moon.status)
        if not hub["present"]:
            return
        self._busy = True
        try:
            await self._evaluate(hub)
        except Exception as e:  # noqa: BLE001
            log.warning("Trockner-Automatik: %s", e)
        finally:
            self._busy = False

    async def _evaluate(self, hub: Dict[str, Any]) -> None:
        now = self.clock()
        if now - self._last_cmd_at < COMMAND_SETTLE_S:
            return          # ACE hat den letzten Befehl noch nicht zurueckgemeldet
        req = self.required_temp()
        c = self.config
        if hub["drying"]:
            if self.schedule and now >= self.schedule["at"]:
                self.schedule = None
                self._save()
                self._event("Geplantes Trocknen fällig – Trockner lief bereits")
            # Sicherheit, auch bei Start von Hand: empfindlicheres Filament eingelegt -> Temperatur senken
            if req["temp"] is not None and hub["target_temp"] and hub["target_temp"] > req["temp"]:
                left = (hub["remaining_min"] or c.max_hours * 60) / 60
                await self.start(req["temp"], max(0.5, min(24.0, left)), source="auto" if self.auto_run else "hand")
                self._event(f"Temperatur auf {req['temp']} °C gesenkt (Slot {', '.join(map(str, req['limited_by']))})")
                return
            if self.auto_run and hub["humidity"] is not None and hub["humidity"] <= c.stop_below:
                await self.stop(source="auto")
            return
        if self.schedule and now >= self.schedule["at"]:
            sched, self.schedule = self.schedule, None
            self._save()
            if req["temp"] is None and sched.get("temp") is None:
                self._event("Geplantes Trocknen übersprungen: keine Spule eingelegt")
                return
            await self.start(sched.get("temp"), sched.get("hours"), source="plan")
            return
        if self.auto_run:       # die ACE hat den Durchgang selbst beendet (Laufzeit um)
            self.auto_run = False
            self.pause_until = now + c.pause_minutes * 60
            self._event("Durchgang beendet (Laufzeit)")
        if not c.enabled or hub["humidity"] is None or now < self.pause_until or req["temp"] is None:
            return
        if not c.while_printing and self.slots.printing:
            return
        if hub["humidity"] >= c.start_above:
            await self.start(req["temp"], c.max_hours, source="auto")
