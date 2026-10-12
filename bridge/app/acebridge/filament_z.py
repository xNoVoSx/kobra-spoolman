"""Z offset per filament: Spoolman field `z_offset` (mm) -> Klipper macro KOBRA_START (variable slot_z, per slot T0-T3).

KOBRA_START (kobra-klipper) adds the start filament's value to the first layer at print start (+ = further from the
bed). Unlike PA the filament inherits it from its template here (e.g. all PETG +0.02 mm).
Without the bridge all slots stay at 0. Can be switched off: setting `filament_z_sync`; in Klipper `use_filament_z`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional

from .gcodepush import GcodePush
from .i18n import tr
from .profiles import find_template
from .spoolman import extra_value

if TYPE_CHECKING:
    from .config import Config
    from .moonraker import Moonraker
    from .slots import SlotManager
    from .spoolman import Spoolman

log = logging.getLogger("filament_z")

FIELD = "z_offset"
LIMIT = 0.5          # mm; larger values are surely a typo (KOBRA_START limits the same way)


def filament_z(fil: dict, templates: list) -> float:
    """Z offset of a filament in mm: its own value, else the template's, else 0. Implausible values count as 0."""
    for src in (fil, find_template(fil, templates)):
        v = extra_value(src, FIELD) if src else None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v) if abs(v) <= LIMIT else 0.0
    return 0.0


class FilamentZSync:
    def __init__(self, cfg: "Config", moon: "Moonraker", sm: "Spoolman", slots: "SlotManager"):
        self.cfg, self.moon, self.sm, self.slots = cfg, moon, sm, slots
        self.pushed: Optional[List[float]] = None
        self.push = GcodePush(moon, tr("Z offset"))  # at most one request in flight (the print start holds Klipper)

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
            self.pushed = None       # Klipper restarted: the macro variable is back at 0
        if not getattr(self.cfg, "filament_z_sync", True) or not self.moon.klippy_ready:
            return
        if getattr(self.moon, "platform", "klipper") == "rinkhals":
            return                       # GoKlipper has no KOBRA_START (the Z offset needs kobra-klipper)
        if not getattr(self.sm, "connected", True):
            return                       # send nothing without Spoolman data
        want = self.desired()
        if self.pushed == want or self.push.busy:
            return
        self.pushed = want           # remember even on error: no KOBRA_START in the printer -> do not retry every 2 s

        def done(ok, err):
            if ok:
                log.info("Z offset per slot to Klipper: %s", want)
            else:
                log.warning("Z offset to Klipper failed (KOBRA_START present?): %s", str(err) or type(err).__name__)
        await self.push.send(f'SET_GCODE_VARIABLE MACRO=KOBRA_START VARIABLE=slot_z VALUE="{want}"', done)
