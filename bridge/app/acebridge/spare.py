"""Another spool when one runs out: the printer asks instead of just pausing.

The Klipper module kobra_spare (kobra-klipper, with an ACEPRO patch) steps in when a spool runs empty and the endless
spool finds no match (same colour and material / same material): the print waits paused over the waste chute and
offers every ready slot. One choice = continue with that slot for the rest of the print (later calls of the empty tool
take it too), another material at its own temperature. This side:
- reads `kobra_spare` from the subscription and adds the Spoolman spool of each slot (name, colour, weight left),
- answers (POST /api/spare {"tool": 1}: KOBRA_SPARE T=1 in the background - unloading, loading and purging take a
  minute or two, the state comes with the subscription),
- reports the question as a red message (status.py: phone alarm), switches in switches.py.
Without kobra_spare in Klipper (Rinkhals, older kobra-klipper) nothing changes: ACEPRO only pauses.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .i18n import msg_of, tr

if TYPE_CHECKING:
    from .moonraker import Moonraker
    from .slots import SlotManager

log = logging.getLogger("spare")

OBJ = "kobra_spare"
SUBSCRIBE = {OBJ: ["enabled", "auto_after", "auto_order", "waiting", "candidates", "auto_in", "busy", "map", "last"]}
CHANGE_TIMEOUT_S = 600       # unload, load, purge and maybe Auto PA (~5 min)


class SpareError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


class Spare:
    def __init__(self, moon: "Moonraker", slots: Optional["SlotManager"] = None):
        self.moon = moon
        self.slots = slots
        self.task: Optional[asyncio.Task] = None
        self.error: Optional[str] = None           # last failed choice (G-code error)

    @property
    def raw(self) -> Dict[str, Any]:
        return self.moon.status.get(OBJ) or {}

    @property
    def available(self) -> bool:
        return bool(self.moon.klippy_ready and OBJ in self.moon.status)

    def _spools(self) -> Dict[int, Dict[str, Any]]:
        """Tool (0-based) -> the Spoolman spool in that slot, as the slot view shows it."""
        if self.slots is None:
            return {}
        try:
            assigned, _ = self.slots.assignments()
            return {slot - 1: self.slots.spool_info(s) for slot, s in assigned.items()}
        except Exception:  # noqa: BLE001 - Spoolman away: the question works without names
            log.debug("no spools for the question", exc_info=True)
            return {}

    @staticmethod
    def _spool(info: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not info:
            return None
        return {"spool_id": info.get("spool_id"), "name": info.get("display_name") or info.get("name") or "",
                "color": info.get("color"), "material": info.get("material"),
                "remaining_weight": info.get("remaining_weight")}

    @property
    def busy(self) -> bool:
        return bool(self.raw.get("busy")) or (self.task is not None and not self.task.done())

    def view(self) -> Dict[str, Any]:
        """For web, app and display (/api/app/state "spare")."""
        r = self.raw
        spools = self._spools() if r.get("waiting") else {}
        waiting = r.get("waiting") if isinstance(r.get("waiting"), dict) else None
        cands: List[Dict[str, Any]] = []
        for c in r.get("candidates") or []:
            if isinstance(c, dict) and isinstance(c.get("tool"), int):
                cands.append({"tool": c["tool"], "slot": c["tool"] + 1, "material": c.get("material") or "",
                              "color": c.get("color") or "", "same_material": bool(c.get("same_material")),
                              "same_color": bool(c.get("same_color")), "sticks": bool(c.get("sticks", True)),
                              "spool": self._spool(spools.get(c["tool"]))})
        last = r.get("last") if isinstance(r.get("last"), dict) else None
        return {
            "available": self.available,
            "enabled": bool(r.get("enabled")),
            "auto_after": r.get("auto_after") or 0,
            "auto_order": r.get("auto_order") or [],
            "waiting": ({"tool": waiting.get("tool"), "slot": (waiting.get("tool") or 0) + 1,
                         "material": waiting.get("material") or "", "color": waiting.get("color") or "",
                         "spool": self._spool(spools.get(waiting.get("tool")))} if waiting else None),
            "candidates": cands,                                        # lists never null (app)
            "auto_in": r.get("auto_in"),
            "busy": self.busy,
            "map": {str(k): v for k, v in (r.get("map") or {}).items()},
            "last": ({"from": last.get("from"), "to": last.get("to"), "auto": bool(last.get("auto")),
                      "error": last.get("error")} if last else None),
            "error": self.error,
        }

    def choose(self, tool: Any) -> Dict[str, Any]:
        """Continue the print with slot `tool` (0-based); the empty tool itself = refilled. Runs in the background."""
        if not self.available:
            raise SpareError(503, tr("The question for another spool is not set up in Klipper (module kobra_spare) "
                                     "or Klipper is not ready"))
        if not isinstance(tool, int) or isinstance(tool, bool) or not 0 <= tool <= 15:
            raise SpareError(400, tr("Expected JSON {\"tool\": 1}"))
        waiting = self.raw.get("waiting")
        if not waiting:
            raise SpareError(409, tr("No empty spool is waiting for a choice"))
        if self.busy:
            raise SpareError(409, tr("The change is already running"))
        allowed = {c.get("tool") for c in self.raw.get("candidates") or []} | {waiting.get("tool")}
        if tool not in allowed:
            raise SpareError(404, tr("Slot {slot} is not ready", slot=tool + 1))
        self.error = None

        async def run() -> None:
            try:
                await self.moon.gcode(f"KOBRA_SPARE T={tool}", timeout=CHANGE_TIMEOUT_S, source=tr("Empty spool"))
                log.info("Empty spool: continued with T%d", tool)
            except Exception as e:  # noqa: BLE001
                self.error = msg_of(e) or type(e).__name__
                log.warning("Empty spool: change to T%d failed: %s", tool, self.error)
        self.task = asyncio.get_running_loop().create_task(run())
        return self.view()
