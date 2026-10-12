"""ACE card: settings of the ACE driver (Klipper + ACEPRO) the printer display does not show.

Reading: live from the Moonraker subscription (object `ace`, acemodel.endless_spool) - no polling of its own.
Writing (driver G-code, applies at once, also during a print):
- endless spool: ACE_ENABLE_ENDLESS_SPOOL / ACE_DISABLE_ENDLESS_SPOOL
- mode:          ACE_SET_ENDLESS_SPOOL_MODE MODE=exact|material|next

Purge lengths come from Orca's matrix (the change-filament G-code passes them to the driver), runout is always
watched by the driver - neither is a switch here.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Dict

from . import acemodel
from .i18n import tr

if TYPE_CHECKING:
    from .moonraker import Moonraker
    from .slots import SlotManager

log = logging.getLogger("ace")

MODES = {"exact": tr("same colour and same material"), "material": tr("same material"), "next": tr("next spool")}
CONFIRM_WAIT_S = 2.0      # wait this long for the driver to confirm (the answer then shows the new state)


class AceError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


class AceSettings:
    def __init__(self, moon: "Moonraker", slots: "SlotManager"):
        self.moon = moon
        self.slots = slots

    async def refresh(self, force: bool = False) -> None:
        """Nothing to poll - the driver reports its settings in the subscription (for the bridge's ticker)."""

    def state(self) -> Dict[str, Any]:
        st = self.moon.status
        present = bool(self.moon.klippy_ready and acemodel.connected(st))
        endless = acemodel.endless_spool(st)
        dry = acemodel.dryer(st)
        return {
            "present": present,
            "endless_spool": endless["enabled"] if present else None,
            "endless_mode": endless["mode"] if present else None,
            "endless_modes": MODES,
            "firmware": dry.get("firmware"),
            "model": dry.get("model"),
            "printing": self.slots.printing,
            "read_at": time.strftime("%Y-%m-%dT%H:%M:%S") if present else None,
        }

    def _check(self) -> None:
        if not self.moon.klippy_ready or not acemodel.connected(self.moon.status):
            raise AceError(503, tr("ACE not connected"))

    async def set_options(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        """Endless spool on/off (endless_spool) and mode (endless_mode) - harmless, also during a print, applies at the
        next runout."""
        cmds, want = [], {}
        for k, v in changes.items():
            if k == "endless_spool":
                if not isinstance(v, bool):
                    raise AceError(400, tr("{key}: true or false", key=k))
                cmds.append("ACE_ENABLE_ENDLESS_SPOOL" if v else "ACE_DISABLE_ENDLESS_SPOOL")
                want["enabled"] = v
            elif k == "endless_mode":
                if v not in MODES:
                    raise AceError(400, tr("Mode: {modes}", modes=", ".join(MODES)))
                cmds.append(f"ACE_SET_ENDLESS_SPOOL_MODE MODE={v}")
                want["mode"] = v
            else:
                raise AceError(400, tr("Unknown setting {key}", key=k))
        if not cmds:
            raise AceError(400, tr("Nothing to change"))
        self._check()
        await self.moon.gcode("\n".join(cmds), source=tr("ACE card"))
        log.info("ACE settings: %s", "; ".join(cmds))
        await self._wait_for(want)
        return self.state()

    async def _wait_for(self, want: Dict[str, Any]) -> None:
        """Until the driver reports the new state in the subscription (at most CONFIRM_WAIT_S)."""
        end = time.monotonic() + CONFIRM_WAIT_S
        while time.monotonic() < end:
            cur = acemodel.endless_spool(self.moon.status)
            if all(cur.get(k) == v for k, v in want.items()):
                return
            await asyncio.sleep(0.1)

