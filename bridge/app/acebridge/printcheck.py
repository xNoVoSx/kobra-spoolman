"""Pruefung beim Druckstart: passen die Slots zur Druckdatei?

Sobald die Bridge die Druckdatei gelesen hat (render.py), vergleicht sie fuer jedes Werkzeug, das die Datei
wirklich benutzt, den Slot (ACEPRO: Werkzeug T<n> = Slot n): Spule zugeordnet? Material wie im Slicer? Farbe ungefaehr gleich?
Spule nicht zu feucht (moisture.py)? Dass die Restmenge reicht, prueft status.spool_reach ohnehin.

Ergebnis sind Meldungen (rot = Alarm am Handy). Mit wet_print_action = pause pausiert die Bridge einen Druck,
der mit einer feuchten Spule startet - einmal je Druck, nur in den ersten Minuten.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .slots import base_type

if TYPE_CHECKING:
    from .__main__ import Bridge

log = logging.getLogger("printcheck")

COLOUR_LIMIT = 140          # RGB-Abstand, ab dem die Farbe "deutlich anders" ist
PAUSE_WINDOW_S = 10 * 60    # Pause wegen feuchter Spule nur so kurz nach dem Start


def _rgb(h: Optional[str]):
    h = (h or "").lstrip("#")[:6]
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) == 6 else None
    except ValueError:
        return None


def colour_distance(a: Optional[str], b: Optional[str]) -> Optional[float]:
    ra, rb = _rgb(a), _rgb(b)
    if not ra or not rb:
        return None
    return sum((x - y) ** 2 for x, y in zip(ra, rb, strict=True)) ** 0.5


def check(bridge: "Bridge") -> List[Dict[str, Any]]:
    """Probleme des laufenden Drucks: [{slot, tool, kind, level, text}]. Leer, solange die Datei nicht gelesen ist."""
    ps = bridge.moon.status.get("print_stats") or {}
    if ps.get("state") not in ("printing", "paused"):
        return []
    pv = bridge.preview
    m = pv.model
    if not m or pv.status != "ready" or not len(m):
        return []
    assigned, _ = bridge.slots.assignments()
    out: List[Dict[str, Any]] = []
    for tool in sorted(t for t, mm in m.e_total.items() if mm > 1):
        gate = tool                       # ACEPRO: Werkzeug T<n> = Slot n (keine Umleitung wie GoKlippers ttg_map)
        slot = gate + 1
        ace = bridge.slots.ace_gate(gate)
        spool = assigned.get(slot)
        want_type = base_type(m.types[tool]).upper() if tool < len(m.types) and m.types[tool] else ""
        want_col = m.colours[tool] if tool < len(m.colours) else None
        tag = f"T{tool} → Slot {slot}"
        if not ace["present"] and not spool:
            out.append({"slot": slot, "tool": tool, "kind": "empty", "level": "error",
                        "text": f"Druckstart-Prüfung: {tag} wird gebraucht, der Slot ist leer"})
            continue
        fil = (spool or {}).get("filament") or {}
        have_type = base_type(fil.get("material") or ace["material"] or "").upper()
        if want_type and have_type and want_type != have_type:
            out.append({"slot": slot, "tool": tool, "kind": "material", "level": "error",
                        "text": f"Druckstart-Prüfung: {tag} – die Datei will {want_type}, eingelegt ist {have_type}"})
        dist = colour_distance(want_col, ace["color"] or fil.get("color_hex"))
        if dist is not None and dist > COLOUR_LIMIT:
            out.append({"slot": slot, "tool": tool, "kind": "colour", "level": "warn",
                        "text": f"Druckstart-Prüfung: {tag} – Farbe weicht vom Slicer ab (#{want_col} statt "
                                f"#{(ace['color'] or fil.get('color_hex') or '')[:6]})"})
        if not spool:
            out.append({"slot": slot, "tool": tool, "kind": "nospool", "level": "warn",
                        "text": f"Druckstart-Prüfung: {tag} hat keine Spule zugeordnet – der Verbrauch landet bei den offenen Buchungen"})
            continue
        mv = bridge.moisture.view(spool)
        if mv["needs_drying"]:
            why = "neu, Verlauf unbekannt" if mv["score"] is None else f"Feuchte-Schätzung {mv['score']} %"
            out.append({"slot": slot, "tool": tool, "kind": "wet", "level": "error",
                        "text": f"Druckstart-Prüfung: {tag} – {fil.get('name') or 'Spule'} wahrscheinlich feucht ({why}), "
                                f"vorher ~{mv['hours_needed']:g} h trocknen"})
    return out


class PrintGuard:
    """Pausiert einmal je Druck, wenn eine feuchte Spule gebraucht wird und wet_print_action = pause."""

    def __init__(self, bridge: "Bridge", clock=time.time):
        self.bridge = bridge
        self.clock = clock
        self.acted_job: Optional[str] = None
        self.started_at: Optional[float] = None
        self._state = ""

    async def tick(self) -> None:
        b = self.bridge
        ps = b.moon.status.get("print_stats") or {}
        st = ps.get("state") or ""
        if st != self._state:
            if st == "printing" and self._state not in ("printing", "paused"):
                self.started_at = self.clock()
            self._state = st
        if st != "printing" or b.cfg.wet_print_action != "pause" or self.started_at is None:
            return
        job = f"{ps.get('filename')}:{self.started_at}"
        if job == self.acted_job or self.clock() - self.started_at > PAUSE_WINDOW_S:
            return
        wet = [i for i in check(b) if i["kind"] == "wet"]
        if not wet:
            return
        self.acted_job = job
        try:
            await b.moon.action("printer.print.pause", "PAUSE (feuchte Spule)", source="Druckstart-Prüfung")
            log.warning("Druck pausiert: %s", "; ".join(i["text"] for i in wet))
        except Exception as e:  # noqa: BLE001
            log.error("Pause wegen feuchter Spule fehlgeschlagen: %s", e)
