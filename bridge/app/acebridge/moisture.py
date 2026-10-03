"""Feuchte-Schaetzung pro Spule - damit niemand mitdenken muss, welche Spule getrocknet werden sollte.

Messen laesst sich die Feuchte in einer Spule nicht. Geschaetzt wird aus dem Verlauf: wie lange lag sie wo, bei
welcher Luftfeuchte, wann wurde sie wie getrocknet. Modell (bewusst einfach, Werte je Material einstellbar):

- u = Feuchte-Last 0..1 (Anteil des Gleichgewichts bei 100 % rF). Die Spule naehert sich exponentiell der
  Luftfeuchte ihrer Umgebung: u_eq = rF/100, Zeitkonstante tau so, dass sie bei 50 % rF nach `open_days` die
  Warnschwelle U_WARN erreicht. Bei niedriger Luftfeuchte (Trockenbox, ACE) erreicht sie die Schwelle nie.
- Umgebung: in der ACE der Sensor der ACE; im Regal die Raumfeuchte (Einstellung), fuer eigene Lagerorte
  (z. B. "Trockenbox=15") deren Wert.
- Trocknen: u faellt exponentiell; nach `dry_hours` bei der empfohlenen Temperatur auf ~10 %. Ist die ACE
  kuehler (empfindliche Nachbarspule), dauert es laenger: Faktor 2 je 10 °C weniger.
- Neue Spulen ohne Verlauf: "unbekannt" - mit "neue Spulen zuerst trocknen" gelten sie als zu trocknen.

Schreibt (wenn die Felder in Spoolman angelegt sind) last_in_ace, last_dried, last_dried_info und moisture an die Spule.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from .dryer import DEFAULT_DRY_TEMP, filament_dry_temp, hub_state
from .profiles import find_template
from .slots import base_type
from .spoolman import extra_value

if TYPE_CHECKING:
    from .config import Config
    from .moonraker import Moonraker
    from .slots import SlotManager

log = logging.getLogger("moisture")

U_WARN = 0.30                    # ab hier "trocknen empfohlen" (Wert 100)
REF_RH = 50.0                    # open_days gilt bei dieser Luftfeuchte
ACE_RH_FALLBACK = 30.0           # ACE ohne Messwert
TICK_S = 300                     # Rechenschritt
SPOOLMAN_EVERY_S = 6 * 3600      # moisture-Feld in Spoolman hoechstens so oft (ausser bei Ereignissen)
HISTORY_KEPT = 40

# Startwerte je Material (vorsichtig; die Quellen widersprechen sich stark) - in Spoolman am Filament oder an
# der Vorlage aenderbar: open_days ("Offen bis Trocknen") und dry_hours ("Trocknen Dauer")
OPEN_DAYS = {"PLA": 14, "PLA-CF": 14, "PETG": 5, "PET": 5, "PCTG": 5, "PETG-CF": 5, "PET-CF": 5,
             "TPU": 2, "PEBA": 2, "ABS": 21, "ABS-GF": 21, "ASA": 21, "ASA-CF": 21, "HIPS": 21,
             "PA": 0.5, "PA-CF": 0.5, "PA6-CF": 0.5, "PC": 0.5, "PVA": 0.5, "BVOH": 0.5, "PPS": 2}
DRY_HOURS = {"PLA": 4, "PLA-CF": 4, "PETG": 6, "PET": 6, "PCTG": 6, "PETG-CF": 6, "PET-CF": 6,
             "TPU": 8, "PEBA": 8, "ABS": 4, "ABS-GF": 4, "ASA": 4, "ASA-CF": 4, "HIPS": 4,
             "PA": 12, "PA-CF": 12, "PA6-CF": 12, "PC": 12, "PVA": 8, "BVOH": 8, "PPS": 6}
FALLBACK_OPEN_DAYS, FALLBACK_DRY_HOURS = 5, 6


def material_params(fil: Dict[str, Any], templates: List[Dict[str, Any]]) -> Dict[str, float]:
    """open_days, dry_hours, dry_temp - am Filament, an der Vorlage, sonst Startwert je Material."""
    tpl = find_template(fil, templates)
    mat = base_type(fil.get("material") or (tpl or {}).get("material") or "").upper()

    def pick(key: str, table: Dict[str, float], fallback: float) -> float:
        for src in (fil, tpl or {}):
            v = extra_value(src, key)
            if v not in (None, ""):
                try:
                    return max(0.05, float(v))
                except (TypeError, ValueError):
                    pass
        return table.get(mat, fallback)
    return {"open_days": pick("open_days", OPEN_DAYS, FALLBACK_OPEN_DAYS),
            "dry_hours": pick("dry_hours", DRY_HOURS, FALLBACK_DRY_HOURS),
            "dry_temp": filament_dry_temp(fil, templates)[0], "material": mat}


def absorb(u: float, rh: float, hours: float, open_days: float) -> float:
    """Annaeherung an das Gleichgewicht der Umgebung."""
    tau = open_days * 24 / -math.log(1 - U_WARN / (REF_RH / 100))      # bei 50 % rF: Schwelle nach open_days
    u_eq = max(0.0, min(1.0, rh / 100))
    return u_eq + (u - u_eq) * math.exp(-hours / tau)


def dry(u: float, hours: float, dry_hours: float, temp: float, rec_temp: float) -> float:
    """Trocknen: nach dry_hours bei rec_temp auf ~10 %; je 10 °C kuehler doppelt so lange."""
    factor = 2 ** (max(0.0, rec_temp - temp) / 10)
    tau = dry_hours * factor / math.log(10)
    return u * math.exp(-hours / tau)


def hours_needed(u: Optional[float], dry_hours: float, temp: float, rec_temp: float) -> float:
    """So lange bei temp, bis die Spule wieder bei ~10 % des Ausgangs liegt (unbekannt: volle Dauer)."""
    factor = 2 ** (max(0.0, rec_temp - temp) / 10)
    if u is None:
        return dry_hours * factor
    target = 0.03
    if u <= target:
        return 0.0
    return max(0.5, dry_hours * factor / math.log(10) * math.log(u / target))


def parse_locations(text: str) -> Dict[str, float]:
    """"Trockenbox=15; Vakuumbeutel=10" -> {name: rF}. ValueError bei Unsinn."""
    out: Dict[str, float] = {}
    for part in (text or "").replace("\n", ";").split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"„{part}“: Ort=Feuchte erwartet, z. B. Trockenbox=15")
        name, val = (x.strip() for x in part.split("=", 1))
        try:
            rh = float(val.replace(",", ".").rstrip("%"))
        except ValueError:
            raise ValueError(f"„{part}“: Feuchte muss eine Zahl sein") from None
        if not name or not 0 <= rh <= 100:
            raise ValueError(f"„{part}“: Feuchte 0–100 %")
        out[name] = rh
    return out


class MoistureModel:
    def __init__(self, cfg: "Config", moon: "Moonraker", slots: "SlotManager", clock: Callable[[], float] = time.time):
        self.cfg = cfg
        self.moon = moon
        self.slots = slots
        self.sm = slots.sm
        self.clock = clock
        self.path = os.path.join(cfg.data_dir, "moisture.json")
        self.state: Dict[str, Dict[str, Any]] = {}
        self._last_tick = 0.0
        self._in_ace: Dict[int, int] = {}            # spool_id -> slot (letzter Stand)
        self._first = True
        self.on_insert: Callable[[Dict[str, Any], Dict[str, Any]], Any] = lambda spool, info: None
        self.room_rh_measured: Callable[[], Optional[float]] = lambda: None    # Raumsensor (mqtt.py), None = keiner
        self._load()

    # ------------------------------------------------------------ Speichern
    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                self.state = json.load(f).get("spools", {})
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            log.warning("moisture.json unlesbar, fange neu an: %s", e)

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"spools": self.state}, f)
        os.replace(tmp, self.path)

    # ------------------------------------------------------------ Hilfen
    def _templates(self) -> List[Dict[str, Any]]:
        try:
            return self.sm.templates()
        except Exception:  # noqa: BLE001
            return []

    def _locations(self) -> Dict[str, float]:
        try:
            return parse_locations(getattr(self.cfg, "dry_locations", ""))
        except ValueError:
            return {}

    def _env(self, spool: Dict[str, Any], slot: Optional[int], hub: Dict[str, Any]) -> Tuple[str, float, Optional[float]]:
        """(wo, rF, Trockentemperatur oder None)."""
        if slot is not None:
            rh = hub["humidity"] if hub.get("humidity") is not None else ACE_RH_FALLBACK
            return f"ACE Slot {slot}", float(rh), (float(hub["temp"] or hub["target_temp"] or 0) if hub.get("drying") else None)
        loc = spool.get("location") or ""
        room = self.room_rh_measured()
        rh = self._locations().get(loc, room if room is not None else getattr(self.cfg, "room_rh", 50.0))
        return loc or "Regal", float(rh), None

    def _entry(self, sid: int) -> Dict[str, Any]:
        return self.state.setdefault(str(sid), {"u": None, "t": None, "history": [], "known": False})

    def _hist(self, e: Dict[str, Any], kind: str, **data: Any) -> None:
        e["history"].append({"at": round(self.clock()), "kind": kind, **data})
        e["history"] = e["history"][-HISTORY_KEPT:]

    # ------------------------------------------------------------ Rechnen
    def score(self, u: Optional[float]) -> Optional[int]:
        return None if u is None else int(round(u / U_WARN * 100))

    def view(self, spool: Dict[str, Any]) -> Dict[str, Any]:
        """Fuer Spulenkarte, Regal und App."""
        sid = spool.get("id")
        e = self.state.get(str(sid)) or {"u": None, "history": [], "known": False}
        fil = spool.get("filament") or {}
        p = material_params(fil, self._templates())
        s = self.score(e.get("u"))
        new_dry = getattr(self.cfg, "new_spools_dry", True)
        wet = (s is not None and s >= 100) or (s is None and new_dry)
        last_dry = next((h for h in reversed(e["history"]) if h["kind"] == "dried"), None)
        return {"score": s, "state": "unknown" if s is None else "wet" if s >= 100 else "ok" if s < 70 else "soon",
                "needs_drying": wet, "where": e.get("where"), "out_since": e.get("out_since"),
                "last_dried": last_dry, "params": p,
                "hours_needed": round(hours_needed(e.get("u"), p["dry_hours"], p["dry_temp"], p["dry_temp"]), 1)}

    def history(self, spool_id: int) -> List[Dict[str, Any]]:
        return list((self.state.get(str(spool_id)) or {}).get("history", []))[::-1]

    async def tick(self) -> None:
        """Alle paar Sekunden aufrufen: Ein-/Auslegen sofort, Rechnen alle TICK_S."""
        if not self.sm.spools:
            return
        now = self.clock()
        assigned, _ = self.slots.assignments()
        in_ace = {s["id"]: slot for slot, s in assigned.items() if s and s.get("id") is not None}
        hub = hub_state(self.moon.status)
        if self._first:
            self._in_ace, self._first = in_ace, False
            for sid in in_ace:
                self._entry(sid)
        else:
            for sid, slot in in_ace.items():
                if self._in_ace.get(sid) != slot:
                    await self._inserted(sid, slot)
            for sid, slot in self._in_ace.items():
                if sid not in in_ace:
                    await self._removed(sid, slot)
            self._in_ace = in_ace
        if now - self._last_tick >= TICK_S:
            dt = (now - self._last_tick) / 3600 if self._last_tick else 0
            self._last_tick = now
            self._step(dt, in_ace, hub)
            self._save()
            await self._sync_spoolman(force=False)

    def _step(self, dt: float, in_ace: Dict[int, int], hub: Dict[str, Any]) -> None:
        templates = self._templates()
        for spool in self.sm.spools:
            sid = spool.get("id")
            if sid is None or spool.get("archived") or self.sm.is_template(spool.get("filament") or {}):
                continue
            e = self._entry(sid)
            where, rh, temp = self._env(spool, in_ace.get(sid), hub)
            e["where"] = where
            if dt <= 0:
                continue
            p = material_params(spool.get("filament") or {}, templates)
            if temp:                                   # in der ACE, die gerade trocknet
                if e["u"] is None:
                    e["u"] = REF_RH / 100              # unbekannt: wie eine offene Spule bei 50 % rF
                e["u"] = dry(e["u"], dt, p["dry_hours"], temp, p["dry_temp"])
                e.setdefault("drying_since", self.clock() - dt * 3600)
                e["drying_temp"] = hub.get("target_temp") or temp
            else:
                since = e.pop("drying_since", None)
                if since is not None:
                    self._hist(e, "dried", temp=e.pop("drying_temp", None), minutes=round((self.clock() - since) / 60),
                               score=self.score(e["u"]))
                    e["dried_at"], e["known"] = round(self.clock()), True
                if e["u"] is not None:
                    e["u"] = absorb(e["u"], rh, dt, p["open_days"])

    async def _inserted(self, sid: int, slot: int) -> None:
        e = self._entry(sid)
        spool = self.sm.spool(sid) if hasattr(self.sm, "spool") else None
        out = e.get("out_since")
        e.pop("out_since", None)
        self._hist(e, "in", slot=slot, score=self.score(e["u"]))
        self._save()
        if spool:
            info = self.view(spool)
            info["outside_h"] = round((self.clock() - out) / 3600, 1) if out else None
            info["slot"] = slot
            try:
                res = self.on_insert(spool, info)
                if hasattr(res, "__await__"):
                    await res
            except Exception as ex:  # noqa: BLE001
                log.warning("Feuchte beim Einlegen: %s", ex)

    async def _removed(self, sid: int, slot: int) -> None:
        e = self._entry(sid)
        e["out_since"] = round(self.clock())
        self._hist(e, "out", slot=slot, score=self.score(e["u"]))
        self._save()
        await self._write(sid, {"last_in_ace": self._iso(self.clock())})

    def note_dried(self, sid: int, temp: float, minutes: float) -> None:
        """Von aussen bekannte Trocknung (z. B. eigener Trockner) - setzt die Spule auf trocken."""
        e = self._entry(sid)
        e["u"], e["known"], e["dried_at"] = 0.03, True, round(self.clock())
        self._hist(e, "dried", temp=temp, minutes=minutes, manual=True, score=self.score(e["u"]))
        self._save()

    # ------------------------------------------------------------ Spoolman
    @staticmethod
    def _iso(t: float) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + "Z"

    async def _fields(self) -> set:
        try:
            return {f.get("key") for f in await self.sm.fields("spool")}
        except Exception:  # noqa: BLE001
            return set()

    async def _write(self, sid: int, values: Dict[str, Any]) -> None:
        if self.cfg.dry_run:
            return
        have = await self._fields()
        extra = {k: json.dumps(v) for k, v in values.items() if k in have}
        if not extra:
            return
        try:
            await self.sm.patch_spool(sid, {"extra": extra})
        except Exception as e:  # noqa: BLE001
            log.warning("Spule %s: Feuchte-Felder nicht geschrieben: %s", sid, e)

    async def _sync_spoolman(self, force: bool) -> None:
        now = self.clock()
        for sid_s, e in self.state.items():
            s = self.score(e.get("u"))
            if s is None:
                continue
            due = force or now - e.get("synced_at", 0) >= SPOOLMAN_EVERY_S or abs(s - e.get("synced_score", -999)) >= 25
            if not due:
                continue
            values: Dict[str, Any] = {"moisture": s}
            if e.get("dried_at") and e.get("dried_at") != e.get("synced_dried"):
                last = next((h for h in reversed(e["history"]) if h["kind"] == "dried"), {})
                values["last_dried"] = self._iso(e["dried_at"])
                values["last_dried_info"] = f"{last.get('temp') or '?'} °C"
                e["synced_dried"] = e["dried_at"]
            await self._write(int(sid_s), values)
            e["synced_at"], e["synced_score"] = now, s

    def fields_missing(self, have: set) -> List[str]:
        return [k for k in ("moisture", "last_in_ace", "last_dried") if k not in have]


__all__ = ["MoistureModel", "material_params", "absorb", "dry", "hours_needed", "parse_locations", "U_WARN",
           "DEFAULT_DRY_TEMP"]
