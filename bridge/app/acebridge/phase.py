"""Druckphase: was macht der Drucker gerade? Statt nur "Druckt" z. B. "Heizt Bett 63/100 °C", "Vorheizen 5/15 min",
"Wechsel auf Slot 2 · lädt", "Misst Pressure Advance", "Druckt · Schicht 34/120".

Quellen (alles aus dem bestehenden Abo, keine Abfrage am Drucker):
- Klipper-Modul kobra_phase (kobra-klipper): Schritt des Druckstarts (G9111), Vorheizen, Werkzeugwechsel, Fortsetzen
- kobra_pa.measuring: Auto-PA misst
- ace.target_index: Wechsel laeuft (auch ohne kobra_phase)
- Konsole (ACEPRO-Meldungen): Teilschritt beim Wechsel - heizt, entlaedt, laedt, spuelt
- print_stats.info: Schicht x/y
Ist kobra_phase am Drucker abgeschaltet oder fehlt, bleibt es bei Wechsel/PA/Schicht.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable, Dict, Optional, Tuple

OBJ = "kobra_phase"
SUBSCRIBE = {OBJ: ["phase", "slot", "done", "total", "since", "seq", "enabled"]}

# Schluessel wie PHASES in kobra-klipper/klipper-extras/kobra_phase.py (dort gleich halten, Test prueft es)
TEXT = {
    "heat_bed": "Heizt Bett",
    "soak": "Vorheizen",
    "wipe": "Wischt Düse",
    "cool": "Kühlt Düse zum Tasten",
    "home_z": "Tastet Z",
    "mesh": "Misst Bettnetz",
    "heat_nozzle": "Heizt Düse",
    "change": "Wechsel",
    "purge": "Spült",
    "pa": "Misst Pressure Advance",
    "prime": "Reinigungslinie",
    "resume": "Setzt Druck fort",
    "end": "Druckende",
}

# ACEPRO-Meldungen beim Werkzeugwechsel -> Teilschritt (ace_macros_generic.cfg, manager.py)
STEPS = (
    (re.compile(r"ACE\[M\]: Pre toolchange|ACE\[M\]: PRE - heating"), "heizt"),
    (re.compile(r"Smart unload tool|performing unload|triggered unload"), "entlädt"),
    (re.compile(r"Loading tool \d|Feeding slot \d"), "lädt"),
    (re.compile(r"ACE\[M\]: Post toolchange|ACE\[M\]: Purging|purging additional"), "spült"),
)
STEP_MAX_AGE = 600.0       # ein Teilschritt aelter als 10 min gehoert nicht mehr zum laufenden Wechsel


class ChangeSteps:
    """Merkt sich den letzten Teilschritt des Werkzeugwechsels aus der Konsole."""

    def __init__(self, clock: Callable[[], float] = time.time):
        self.clock = clock
        self.step: Optional[Tuple[str, float]] = None

    def on_console(self, entry: Dict[str, Any]) -> None:
        text = entry.get("text") or ""
        for rx, name in STEPS:
            if rx.search(text):
                self.step = (name, self.clock())
                return

    def current(self, since: Optional[float] = None) -> Optional[str]:
        """Teilschritt, wenn er nach `since` (Beginn des Wechsels) kam und nicht zu alt ist."""
        if not self.step:
            return None
        name, at = self.step
        if self.clock() - at > STEP_MAX_AGE or (since is not None and at < since - 2):
            return None
        return name


def _heater(status: Dict[str, Any], obj: str) -> str:
    h = status.get(obj) or {}
    if h.get("temperature") is None or not h.get("target"):
        return ""
    return f" {round(float(h['temperature']))}/{round(float(h['target']))} °C"


def describe(status: Dict[str, Any], steps: Optional[ChangeSteps] = None) -> Optional[Dict[str, str]]:
    """{"key", "text"} oder None (dann zeigt die Oberflaeche den Druckerstatus wie bisher)."""
    ps = status.get("print_stats") or {}
    state = ps.get("state") or "standby"
    kp = status.get("kobra_pa") or {}
    ph = status.get(OBJ) or {}
    key = (ph.get("phase") or "") if ph.get("enabled", True) else ""
    ace = status.get("ace") or {}
    target = ace.get("target_index")
    changing = isinstance(target, int) and target >= 0 and target != ace.get("current_index")

    if kp.get("measuring"):
        return {"key": "pa", "text": TEXT["pa"]}
    if key == "change" or changing:
        slot = ph.get("slot") if key == "change" and ph.get("slot") else (target + 1 if changing else None)
        step = steps.current(ph.get("since") if key == "change" else None) if steps else None
        text = f"Wechsel auf Slot {slot}" if slot else "Wechselt Filament"
        return {"key": "change", "text": text + (f" · {step}" if step else "")}
    if key == "resume":
        return {"key": key, "text": TEXT[key]}
    if state != "printing":
        return None                            # Pause, Fertig, Fehler ...: der Status sagt es schon
    if key in TEXT:
        text = TEXT[key]
        if key == "soak" and ph.get("total"):
            text += f" {int(ph.get('done') or 0)}/{int(ph['total'])} min"
        elif key == "heat_bed":
            text += _heater(status, "heater_bed")
        elif key in ("heat_nozzle", "wipe"):
            text += _heater(status, "extruder")
        elif key == "cool":
            ext = status.get("extruder") or {}
            if ext.get("temperature") is not None:
                text += f" ({round(float(ext['temperature']))} °C)"
        return {"key": key, "text": text}
    info = ps.get("info") or {}
    if info.get("total_layer"):
        return {"key": "printing", "text": f"Druckt · Schicht {info.get('current_layer') or 0}/{info['total_layer']}"}
    return {"key": "printing", "text": "Druckt"}
