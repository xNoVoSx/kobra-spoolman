"""Z-Versatz pro Filament: Spoolman-Feld `z_offset` (mm) -> Klipper-Makro KOBRA_START (Variable slot_z, je Slot T0-T3).

KOBRA_START (kobra-klipper) rechnet den Wert des Startfilaments beim Druckstart zur ersten Schicht dazu (+ = weiter
weg vom Bett). Anders als beim PA erbt das Filament hier von seiner Vorlage (z. B. alle PETG +0,02 mm).
Ohne Bridge stehen alle Slots auf 0. Abschaltbar: Einstellung `filament_z_sync`; in Klipper `use_filament_z`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional

from .profiles import find_template
from .spoolman import extra_value

if TYPE_CHECKING:
    from .config import Config
    from .moonraker import Moonraker
    from .slots import SlotManager
    from .spoolman import Spoolman

log = logging.getLogger("filament_z")

FIELD = "z_offset"
LIMIT = 0.5          # mm; groessere Werte sind sicher ein Tippfehler (KOBRA_START begrenzt ebenso)


def filament_z(fil: dict, templates: list) -> float:
    """Z-Versatz eines Filaments in mm: eigener Wert, sonst der der Vorlage, sonst 0. Unplausibles zaehlt als 0."""
    for src in (fil, find_template(fil, templates)):
        v = extra_value(src, FIELD) if src else None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v) if abs(v) <= LIMIT else 0.0
    return 0.0


class FilamentZSync:
    def __init__(self, cfg: "Config", moon: "Moonraker", sm: "Spoolman", slots: "SlotManager"):
        self.cfg, self.moon, self.sm, self.slots = cfg, moon, sm, slots
        self.pushed: Optional[List[float]] = None

    def desired(self) -> List[float]:
        assigned, _ = self.slots.assignments()
        templates = self.sm.templates()
        out = []
        for slot in range(1, 5):
            fil = ((assigned.get(slot) or {}).get("filament") or {})
            out.append(round(filament_z(fil, templates), 3) if fil.get("id") else 0.0)
        return out

    async def tick(self, full: bool = False) -> None:
        if full or not self.moon.klippy_ready:
            self.pushed = None       # Klipper neu gestartet: Makro-Variable steht wieder auf 0
        if not getattr(self.cfg, "filament_z_sync", True) or not self.moon.klippy_ready:
            return
        want = self.desired()
        if self.pushed == want:
            return
        self.pushed = want           # auch bei Fehler merken: kein KOBRA_START im Drucker -> nicht alle 2 s versuchen
        try:
            await self.moon.gcode(f'SET_GCODE_VARIABLE MACRO=KOBRA_START VARIABLE=slot_z VALUE="{want}"',
                                  source="Z-Versatz")
            log.info("Z-Versatz je Slot an Klipper: %s", want)
        except Exception as e:  # noqa: BLE001
            log.warning("Z-Versatz an Klipper fehlgeschlagen (KOBRA_START vorhanden?): %s", e)
