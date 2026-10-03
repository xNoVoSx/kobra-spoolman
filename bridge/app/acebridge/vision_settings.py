"""Einstellungen der KI-Fehldruck-Erkennung - im KI-Tab aenderbar, gespeichert in DATA_DIR/vision/settings.json.

Die Umgebungsvariablen (VISION_*) sind nur die Startwerte, solange noch nichts gespeichert ist.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field, fields
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from .config import Config

log = logging.getLogger("vision")

ACTIONS = ("warn", "pause")
NOTIFY = ("warn", "fail")
QUIET_MODES = ("fail_only", "pause")
MAX_ZONES = 10
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


@dataclass
class VisionSettings:
    enabled: bool = True
    sensitivity: float = 1.0          # 0.3 .. 3.0, multipliziert den Wert (Obico: 1.0)
    action: str = "warn"              # warn = nur melden, pause = bei Fehldruck pausieren
    heater_off: bool = False          # nach einer KI-Pause die Duese ausschalten
    notify: str = "warn"              # ab welcher Stufe ein Alarm aufs Handy geht: warn | fail
    interval_s: float = 10.0          # 2 .. 60 (die Bewertung ist auf ~10 s abgestimmt)
    safe_s: float = 300.0             # so lange nach Druckstart nie melden (erste Schicht, Spuelen)
    zones: List[Dict[str, float]] = field(default_factory=list)   # ignorierte Bereiche {x, y, w, h} 0..1
    quiet: Dict[str, Any] = field(default_factory=lambda: {"enabled": False, "start": "22:00", "end": "07:00",
                                                           "mode": "fail_only"})
    dataset_gb: float = 5.0           # 0 = nichts sammeln
    save_every_s: float = 60.0

    @classmethod
    def defaults(cls, cfg: "Config") -> "VisionSettings":
        return cls(sensitivity=cfg.vision_sensitivity, action=cfg.vision_action if cfg.vision_action in ACTIONS
                   else "warn", interval_s=cfg.vision_interval_s, dataset_gb=cfg.vision_dataset_gb,
                   save_every_s=cfg.vision_save_every_s)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _num(v: Any, name: str, lo: float, hi: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} muss eine Zahl sein") from None
    if not lo <= x <= hi:
        raise ValueError(f"{name} muss zwischen {lo:g} und {hi:g} liegen")
    return x


def _zones(v: Any) -> List[Dict[str, float]]:
    if not isinstance(v, list) or len(v) > MAX_ZONES:
        raise ValueError(f"zones: Liste mit höchstens {MAX_ZONES} Bereichen erwartet")
    out = []
    for z in v:
        try:
            x, y, w, h = (float(z[k]) for k in ("x", "y", "w", "h"))
        except (TypeError, KeyError, ValueError):
            raise ValueError("Bereich braucht x, y, w, h (0..1)") from None
        x, y = min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)
        w, h = min(max(w, 0.0), 1.0 - x), min(max(h, 0.0), 1.0 - y)
        if w >= 0.01 and h >= 0.01:
            out.append({"x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4)})
    return out


def _quiet(v: Any, old: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(v, dict):
        raise ValueError("quiet: Objekt erwartet")
    q = {**old, **v}
    for k in ("start", "end"):
        if not isinstance(q.get(k), str) or not _TIME.match(q[k]):
            raise ValueError(f"quiet.{k}: Uhrzeit wie 22:00 erwartet")
    if q.get("mode") not in QUIET_MODES:
        raise ValueError(f"quiet.mode: {' oder '.join(QUIET_MODES)}")
    return {"enabled": bool(q.get("enabled")), "start": q["start"], "end": q["end"], "mode": q["mode"]}


def apply(s: VisionSettings, changes: Dict[str, Any]) -> VisionSettings:
    """Aenderungen pruefen und uebernehmen (nur bekannte Felder). ValueError mit deutscher Meldung."""
    known = {f.name for f in fields(VisionSettings)}
    unknown = set(changes) - known
    if unknown:
        raise ValueError("Unbekannte Einstellung: " + ", ".join(sorted(unknown)))
    d = s.to_dict()
    for k, v in changes.items():
        if k in ("enabled", "heater_off"):
            d[k] = bool(v)
        elif k == "sensitivity":
            d[k] = round(_num(v, "Empfindlichkeit", 0.3, 3.0), 2)
        elif k == "action":
            if v not in ACTIONS:
                raise ValueError("action: warn oder pause")
            d[k] = v
        elif k == "notify":
            if v not in NOTIFY:
                raise ValueError("notify: warn oder fail")
            d[k] = v
        elif k == "interval_s":
            d[k] = _num(v, "Bildabstand", 2, 60)
        elif k == "safe_s":
            d[k] = _num(v, "Lernzeit", 0, 900)
        elif k == "zones":
            d[k] = _zones(v)
        elif k == "quiet":
            d[k] = _quiet(v, s.quiet)
        elif k == "dataset_gb":
            d[k] = _num(v, "Speichergrenze", 0, 100)
        elif k == "save_every_s":
            d[k] = _num(v, "Sammelabstand", 10, 600)
    return VisionSettings(**d)


def load(path: str, default: VisionSettings) -> VisionSettings:
    """Feld fuer Feld: ein ungueltiger Wert faellt allein auf den Startwert zurueck, nicht die ganze Datei."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as e:
        log.warning("vision/settings.json unlesbar, nehme Startwerte: %s", e)
        return default
    s = default
    known = {f.name for f in fields(VisionSettings)}
    for k, v in data.items() if isinstance(data, dict) else []:
        if k not in known:
            continue
        try:
            s = apply(s, {k: v})
        except ValueError as e:
            log.warning("KI-Einstellung %s ungültig, nehme Startwert: %s", k, e)
    return s


def save(path: str, s: VisionSettings) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s.to_dict(), f, indent=1)
    os.replace(tmp, path)


def in_quiet(s: VisionSettings, minutes_of_day: int) -> bool:
    """Liegt die Uhrzeit (Minuten seit Mitternacht) in den Ruhezeiten? Ueber Mitternacht moeglich."""
    q = s.quiet
    if not q.get("enabled"):
        return False

    def m(t: str) -> int:
        h, mm = t.split(":")
        return int(h) * 60 + int(mm)
    a, b = m(q["start"]), m(q["end"])
    return a <= minutes_of_day < b if a <= b else (minutes_of_day >= a or minutes_of_day < b)


def in_zone(zones: List[Dict[str, float]], xc: float, yc: float) -> Optional[int]:
    """Index des ignorierten Bereichs, in dem die Box-Mitte liegt (oder None)."""
    for i, z in enumerate(zones):
        if z["x"] <= xc <= z["x"] + z["w"] and z["y"] <= yc <= z["y"] + z["h"]:
            return i
    return None
