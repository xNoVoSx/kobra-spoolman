"""Einstellungen, die im laufenden Betrieb in der Weboberflaeche/App geaendert werden koennen.

Die Umgebungsvariablen (config.py) sind die Startwerte. Was hier geaendert wird, steht in DATA_DIR/settings.json
und ueberschreibt beim Start den Startwert. Die Werte landen direkt im Config-Objekt - der restliche Code liest
weiter cfg.<name> und merkt die Aenderung beim naechsten Zugriff (keine Neustarts noetig).
Was einen Neustart braeuchte (Adressen von Drucker, Spoolman, Kamera, KI-Dienst), ist nur zum Ansehen da.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from .config import Config

log = logging.getLogger("settings")


@dataclass(frozen=True)
class Spec:
    key: str                 # Name im Config-Objekt
    group: str
    label: str
    kind: str                # bool | float | int
    lo: Optional[float] = None
    hi: Optional[float] = None
    unit: str = ""
    help: str = ""


SPECS: List[Spec] = [
    # Kamera
    Spec("camera", "Kamera", "Kamera über die Bridge", "bool", help="Web, App und Mainsail-Link holen ihre Bilder über die Bridge"),
    Spec("camera_stream", "Kamera", "Dauerstream statt Einzelbildern", "bool",
         help="Achtung: der MJPEG-Stream des Druckers kostet am Kobra S1 allein 100 % CPU. Standard: aus"),
    Spec("camera_fps_min", "Kamera", "Bildrate mindestens", "float", 0.5, 15, "fps"),
    Spec("camera_fps_max", "Kamera", "Bildrate höchstens", "float", 1, 15, "fps"),
    Spec("camera_cpu_low", "Kamera", "Schneller ab Drucker-CPU unter", "float", 30, 100, "%",
         "Darunter alle 5 s 1 fps mehr. Im Druck liegt der S1 allein durch GoKlipper bei 75–89 %"),
    Spec("camera_cpu_high", "Kamera", "Langsamer ab Drucker-CPU über", "float", 30, 100, "%", "Darüber alle 5 s 1 fps weniger"),
    # Druckvorschau
    Spec("render", "Druckvorschau", "Druckdatei laden (Modell, Restmenge)", "bool",
         help="Die Bridge lädt die Datei beim Druckstart einmal gedrosselt – für 3D-Modell und „Spule reicht nicht“"),
    Spec("render_max_mb", "Druckvorschau", "Größte Datei", "float", 10, 1000, "MB", "Größere Dateien: nur das Vorschaubild"),
    Spec("render_interval_s", "Druckvorschau", "Bild der Bridge neu rechnen höchstens alle", "float", 5, 120, "s",
         "Nur für Geräte mit „Bild“ statt 3D"),
    Spec("geometry_max_segments", "Druckvorschau", "Detailgrad 3D-Modell (Bahnen)", "int", 100_000, 3_000_000, "",
         "Mehr Bahnen werden ausgedünnt. 1,5 Mio. ≈ 20 MB Übertragung, für Handys ggf. weniger"),
    # Slots und RFID
    Spec("auto_assign_by_tag", "Slots und RFID", "Spulen mit unserem Tag automatisch zuordnen", "bool"),
    Spec("auto_unassign_on_empty", "Slots und RFID", "Leeren Slot ins Regal räumen", "bool",
         help="Meldet die ACE einen Slot leer, kommt die Spule ins Regal (im Druck erst danach)"),
    Spec("empty_debounce_s", "Slots und RFID", "… wenn der Slot so lange leer ist", "float", 0, 600, "s"),
    Spec("set_ace_slot_info", "Slots und RFID", "Material und Farbe an die ACE schreiben", "bool",
         help="Beim Zuordnen von Spulen ohne Anycubic-Tag (sonst bricht der Druck mit „index out of range“ ab)"),
    Spec("write_lane_data", "Slots und RFID", "lane_data für Orca schreiben", "bool",
         help="Damit Orcas Sync-Knopf die richtigen Profile in die Slots setzt"),
    # Meldungen
    Spec("low_spool_g", "Meldungen", "„Spule fast leer“ unter", "float", 0, 1000, "g"),
    Spec("reach_reserve_pct", "Meldungen", "Reserve bei „Spule reicht nicht“", "float", 0, 50, "%"),
    # Verbrauch
    Spec("book_usage", "Verbrauch", "Verbrauch in Spoolman buchen", "bool",
         help="Aus: nur messen und anzeigen, nichts in Spoolman ändern"),
    Spec("book_interval_s", "Verbrauch", "Zwischenbuchung im Druck alle", "float", 30, 3600, "s"),
    Spec("book_min_mm", "Verbrauch", "Kleinste Buchung", "float", 1, 1000, "mm"),
    # Daten
    Spec("telemetry", "Daten", "Druck-Aufzeichnungen (Rohdaten)", "bool"),
    Spec("telemetry_keep", "Daten", "Aufzeichnungen behalten", "int", 1, 500, "Drucke"),
    Spec("job_history", "Daten", "Druckhistorie behalten", "int", 10, 2000, "Drucke"),
    Spec("humidity_days", "Daten", "Feuchte-Verlauf behalten", "int", 1, 365, "Tage"),
]
BY_KEY = {s.key: s for s in SPECS}

# nur zum Ansehen (brauchen einen Neustart der Bridge)
READONLY = [("moonraker_url", "Drucker (Moonraker)"), ("spoolman_url", "Spoolman"),
            ("camera_snapshot_url", "Kamera-Einzelbild"), ("camera_stream_url", "Kamera-Stream"),
            ("vision_url", "KI-Dienst"), ("data_dir", "Datenordner"), ("http_port", "HTTP-Port"), ("dry_run", "Nur Probe (DRY_RUN)")]


def _path(cfg: "Config") -> str:
    return os.path.join(cfg.data_dir, "settings.json")


def _coerce(spec: Spec, v: Any) -> Any:
    if spec.kind == "bool":
        if isinstance(v, bool):
            return v
        raise ValueError(f"{spec.label}: an oder aus erwartet")
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{spec.label}: Zahl erwartet") from None
    if spec.kind == "int":
        if x != int(x):
            raise ValueError(f"{spec.label}: ganze Zahl erwartet")
        x = int(x)
    if (spec.lo is not None and x < spec.lo) or (spec.hi is not None and x > spec.hi):
        raise ValueError(f"{spec.label}: erlaubt {spec.lo:g}–{spec.hi:g} {spec.unit}".strip())
    return x


class RuntimeSettings:
    def __init__(self, cfg: "Config"):
        self.cfg = cfg
        self.defaults = {s.key: getattr(cfg, s.key) for s in SPECS}     # Startwerte aus der Umgebung
        self.saved: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(_path(self.cfg), encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            log.warning("settings.json unlesbar, nehme Startwerte: %s", e)
            return
        for k, v in (data.items() if isinstance(data, dict) else []):
            spec = BY_KEY.get(k)
            if not spec:
                continue
            try:
                val = _coerce(spec, v)
            except ValueError as e:
                log.warning("Einstellung %s ungültig, nehme Startwert: %s", k, e)
                continue
            self.saved[k] = val
            setattr(self.cfg, k, val)
        self._check_pairs()

    def _save(self) -> None:
        os.makedirs(self.cfg.data_dir, exist_ok=True)
        tmp = _path(self.cfg) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.saved, f, indent=1)
        os.replace(tmp, _path(self.cfg))

    def _check_pairs(self) -> None:
        """Zusammengehoerige Werte: mindestens <= hoechstens."""
        c = self.cfg
        if c.camera_fps_min > c.camera_fps_max:
            raise ValueError("Bildrate: mindestens darf nicht über höchstens liegen")
        if c.camera_cpu_low >= c.camera_cpu_high:
            raise ValueError("Kamera: „schneller unter“ muss kleiner als „langsamer über“ sein")

    def update(self, changes: Dict[str, Any]) -> None:
        """Pruefen, uebernehmen, speichern. Bei einem Fehler bleibt alles beim Alten (ValueError)."""
        unknown = [k for k in changes if k not in BY_KEY]
        if unknown:
            raise ValueError("Nicht änderbar: " + ", ".join(unknown))
        new = {k: _coerce(BY_KEY[k], v) for k, v in changes.items()}
        old = {k: getattr(self.cfg, k) for k in new}
        for k, v in new.items():
            setattr(self.cfg, k, v)
        try:
            self._check_pairs()
        except ValueError:
            for k, v in old.items():
                setattr(self.cfg, k, v)
            raise
        for k, v in new.items():
            if v == self.defaults[k]:
                self.saved.pop(k, None)
            else:
                self.saved[k] = v
        self._save()
        log.info("Einstellungen geändert: %s", ", ".join(f"{k}={v}" for k, v in new.items()))

    def reset(self, key: str) -> None:
        if key not in BY_KEY:
            raise ValueError("Nicht änderbar: " + key)
        self.update({key: self.defaults[key]})

    def view(self) -> Dict[str, Any]:
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for s in SPECS:
            groups.setdefault(s.group, []).append({
                "key": s.key, "label": s.label, "kind": s.kind, "min": s.lo, "max": s.hi, "unit": s.unit, "help": s.help,
                "value": getattr(self.cfg, s.key), "default": self.defaults[s.key], "changed": s.key in self.saved})
        return {"groups": [{"name": g, "items": items} for g, items in groups.items()],
                "readonly": [{"key": k, "label": label, "value": getattr(self.cfg, k, None)} for k, label in READONLY]}
