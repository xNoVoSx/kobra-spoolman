"""Direct feed: filament inserted by hand straight into the toolhead (e.g. TPU), the ACE is passed by.

The Klipper module kobra_direct (kobra-klipper) holds the state - it stays on until switched off, across restarts, and
makes T0-T3, the print start and the runout sensor work without the ACE. The ACE stays connected (dryer, slots).
This side:
- reads `kobra_direct` from the subscription (enabled, spool, name, tool),
- switches it (POST /api/direct) with exactly KOBRA_DIRECT ENABLE=1 SPOOL=<id> NAME=<label> [UNLOAD=1] / ENABLE=0,
- tells the rest of the bridge which spool is printing: usage books the consumption on it (no open item), Auto PA and
  the Z offset take its filament for every tool, the print start check compares it with the file.
Without kobra_direct in Klipper (Rinkhals, older kobra-klipper) everything stays as before.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from .i18n import msg_of, tr

if TYPE_CHECKING:
    from .moonraker import Moonraker
    from .spoolman import Spoolman

log = logging.getLogger("direct")

OBJ = "kobra_direct"
SUBSCRIBE = {OBJ: ["enabled", "spool", "name", "tool"]}


class DirectError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


def _clean(text: str) -> str:
    """Spool label for the G-code parameter: no quotes (Klipper's parser), short."""
    return " ".join(str(text or "").replace('"', "").replace("'", "").split())[:60]


class DirectFeed:
    def __init__(self, moon: "Moonraker", sm: "Spoolman", wait_s: float = 3.0):
        self.moon, self.sm = moon, sm
        self.wait_s = wait_s

    # ------------------------------------------------------------ state
    @property
    def raw(self) -> Dict[str, Any]:
        return self.moon.status.get(OBJ) or {}

    @property
    def available(self) -> bool:
        return bool(self.moon.klippy_ready and OBJ in self.moon.status)

    @property
    def active(self) -> bool:
        return bool(self.raw.get("enabled"))

    @property
    def spool_id(self) -> Optional[int]:
        s = self.raw.get("spool")
        return s if self.active and isinstance(s, int) and s > 0 else None

    def spool(self) -> Optional[Dict[str, Any]]:
        sid = self.spool_id
        return self.sm.spool(sid) if sid else None

    @property
    def tool(self) -> Optional[int]:
        t = self.raw.get("tool")
        return t if self.active and isinstance(t, int) and t >= 0 else None

    def label(self) -> str:
        s = self.spool()
        if s:
            fil = s.get("filament") or {}
            vendor = (fil.get("vendor") or {}).get("name") or ""
            return f"{vendor} {fil.get('name') or ''}".strip() or f"#{s['id']}"
        name = self.raw.get("name") or ""
        return name or (f"#{self.raw.get('spool')}" if self.raw.get("spool") else tr("no spool"))

    def per_tool(self, assigned: Dict[int, Any]) -> Dict[int, Any]:
        """Slot -> spool as the printer uses it: in direct feed every tool prints the direct spool (Auto PA, Z offset)."""
        s = self.spool() if self.active else None
        return {slot: s for slot in range(1, 5)} if s else assigned

    def view(self) -> Dict[str, Any]:
        """For web, app and display (/api/app/state "direct")."""
        s = self.spool()
        fil = (s or {}).get("filament") or {}
        return {
            "available": self.available,
            "active": self.active,
            "spool_id": self.spool_id,
            "label": self.label() if self.active else None,
            "material": fil.get("material"),
            "color": fil.get("color_hex"),
            "tool": self.tool,
            "warning": tr("Direct feed is on – the ACE is passed by. Spool: {label}", label=self.label())
            if self.active else None,
        }

    # ------------------------------------------------------------ switching
    async def set(self, enable: bool, spool_id: Optional[int] = None, unload: bool = False) -> Dict[str, Any]:
        if not self.available:
            raise DirectError(503, tr("Direct feed is not set up in Klipper (module kobra_direct) or Klipper is not ready"))
        state = (self.moon.status.get("print_stats") or {}).get("state")
        if state in ("printing", "paused"):
            raise DirectError(409, tr("Not during a print"))
        if enable:
            if not isinstance(spool_id, int) or spool_id <= 0:
                raise DirectError(400, tr("Choose the spool you inserted"))
            spool = self.sm.spool(spool_id)
            if not spool:
                raise DirectError(404, tr("Spool #{id} not found in Spoolman", id=spool_id))
            fil = spool.get("filament") or {}
            vendor = (fil.get("vendor") or {}).get("name") or ""
            name = _clean(f"{vendor} {fil.get('name') or ''}") or f"Spool {spool_id}"
            script = f'KOBRA_DIRECT ENABLE=1 SPOOL={spool_id} NAME="{name}"' + (" UNLOAD=1" if unload else "")
        else:
            script = "KOBRA_DIRECT ENABLE=0"
        try:
            # unloading heats and moves the ACE first - give it time
            await self.moon.gcode(script, timeout=600 if unload else 15, source=tr("Direct feed"))
        except Exception as e:  # noqa: BLE001
            raise DirectError(409, msg_of(e)) from e
        for _ in range(int(self.wait_s / 0.1)):       # answer with the new state (it comes with the next status)
            if self.active == enable:
                break
            await asyncio.sleep(0.1)
        log.info("Direct feed %s%s", "on, spool #%s" % spool_id if enable else "off", " (unloaded the ACE)" if unload else "")
        return self.view()
