"""Print phase: what is the printer doing right now? Instead of just "Printing" e.g. "Heating bed 63/100 °C",
"Heat soak 5/15 min", "Change to slot 2 · loading", "Measuring pressure advance", "Printing · layer 34/120".

Sources (all from the existing subscription, no query to the printer):
- Klipper module kobra_phase (kobra-klipper): step of the print start (G9111), heat soak, tool change, resume
- kobra_pa.measuring: auto PA is measuring
- ace.target_index: a change is running (also without kobra_phase)
- console (ACEPRO messages): sub-step of the change - heating, unloading, loading, purging
- print_stats.info: layer x/y
If kobra_phase is switched off on the printer or missing, only change/PA/layer remain.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable, Dict, Optional, Tuple

from . import acemodel
from .i18n import tr

OBJ = "kobra_phase"
SUBSCRIBE = {OBJ: ["phase", "slot", "done", "total", "since", "seq", "enabled"]}

# keys like PHASES in kobra-klipper/klipper-extras/kobra_phase.py (keep them equal there, a test checks it)
TEXT = {
    "heat_bed": tr("Heating bed"),
    "soak": tr("Heat soak"),
    "wipe": tr("Wiping nozzle"),
    "cool": tr("Cooling nozzle for probing"),
    "home_z": tr("Probing Z"),
    "mesh": tr("Measuring bed mesh"),
    "heat_nozzle": tr("Heating nozzle"),
    "change": tr("Change"),
    "purge": tr("Purging"),
    "pa": tr("Measuring pressure advance"),
    "prime": tr("Prime line"),
    "resume": tr("Resuming print"),
    "end": tr("Print end"),
}

# ACEPRO messages during a tool change -> sub-step (ace_macros_generic.cfg, manager.py)
STEPS = (
    (re.compile(r"ACE\[M\]: Pre toolchange|ACE\[M\]: PRE - heating"), tr("heating")),
    (re.compile(r"Smart unload tool|performing unload|triggered unload"), tr("unloading")),
    (re.compile(r"Loading tool \d|Feeding slot \d"), tr("loading")),
    (re.compile(r"ACE\[M\]: Post toolchange|ACE\[M\]: Purging|purging additional"), tr("purging")),
)
STEP_MAX_AGE = 600.0       # a sub-step older than 10 min no longer belongs to the running change


class ChangeSteps:
    """Remembers the last sub-step of the tool change from the console."""

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
        """Sub-step, if it came after `since` (start of the change) and is not too old."""
        if not self.step:
            return None
        name, at = self.step
        if self.clock() - at > STEP_MAX_AGE or (since is not None and at < since - 2):
            return None
        return name


def _heater(status: Dict[str, Any], obj: str, label: Any) -> Any:
    h = status.get(obj) or {}
    if h.get("temperature") is None or not h.get("target"):
        return label
    return tr("{label} {t}/{target} °C", label=label, t=round(float(h["temperature"])), target=round(float(h["target"])))


def describe(status: Dict[str, Any], steps: Optional[ChangeSteps] = None) -> Optional[Dict[str, str]]:
    """{"key", "text"} or None (then the UI shows the printer state as before)."""
    ps = status.get("print_stats") or {}
    state = ps.get("state") or "standby"
    kp = status.get("kobra_pa") or {}
    ph = status.get(OBJ) or {}
    key = (ph.get("phase") or "") if ph.get("enabled", True) else ""
    target = acemodel.target_slot(status)
    changing = target is not None and target != acemodel.active_slot(status)
    # Rinkhals reports no target, only Rinkhals' own action text ("Loading", "Unloading" ...)
    action = acemodel.changing(status) if acemodel.variant(status) == acemodel.RINKHALS else None

    if kp.get("measuring"):
        return {"key": "pa", "text": TEXT["pa"]}
    if action and key != "change":
        return {"key": "change", "text": tr("{text} · {step}", text=tr("Changing filament"), step=action)}
    if key == "change" or changing:
        slot = ph.get("slot") if key == "change" and ph.get("slot") else (target + 1 if changing else None)
        step = steps.current(ph.get("since") if key == "change" else None) if steps else None
        text = tr("Change to slot {slot}", slot=slot) if slot else tr("Changing filament")
        return {"key": "change", "text": tr("{text} · {step}", text=text, step=step) if step else text}
    if key == "resume":
        return {"key": key, "text": TEXT[key]}
    if state != "printing":
        return None                            # paused, complete, error ...: the state says it already
    if key in TEXT:
        text = TEXT[key]
        if key == "soak" and ph.get("total"):
            text = tr("{label} {done}/{total} min", label=text, done=int(ph.get("done") or 0), total=int(ph["total"]))
        elif key == "heat_bed":
            text = _heater(status, "heater_bed", text)
        elif key in ("heat_nozzle", "wipe"):
            text = _heater(status, "extruder", text)
        elif key == "cool":
            ext = status.get("extruder") or {}
            if ext.get("temperature") is not None:
                text = tr("{label} ({t} °C)", label=text, t=round(float(ext["temperature"])))
        return {"key": key, "text": text}
    info = ps.get("info") or {}
    if info.get("total_layer"):
        return {"key": "printing", "text": tr("Printing · layer {layer}/{total}", layer=info.get("current_layer") or 0,
                                              total=info["total_layer"])}
    return {"key": "printing", "text": tr("Printing")}
