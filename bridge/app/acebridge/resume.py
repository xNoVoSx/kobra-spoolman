"""Resume after a power loss: the bridge's view of the Klipper module kobra_resume (kobra-klipper).

While printing Klipper keeps saving the last executed position. If an interrupted print is saved after switching on,
the bridge shows it as a red message (alarm in the app) and as a card with a camera image; it is resumed only on a
button press (KOBRA_RESUME CONFIRM=1 - Klipper then probes Z on the part).
Can be switched off in Klipper: KOBRA_POWERLOSS ENABLE=0 (POST /api/resume/switch).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from .i18n import msg_of, tr

if TYPE_CHECKING:
    from .moonraker import Moonraker
    from .slots import SlotManager

log = logging.getLogger("resume")

OBJ = "kobra_resume"
SUBSCRIBE = {OBJ: ["enabled", "pending", "result"]}


class ResumeError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


class Resume:
    def __init__(self, moon: "Moonraker", slots: "SlotManager"):
        self.moon, self.slots = moon, slots
        self.running = False          # resuming (takes a few minutes: heating, probing, purging)
        self.error: Optional[str] = None

    @property
    def klipper(self) -> Optional[Dict[str, Any]]:
        st = self.moon.status.get(OBJ)
        return st if st is not None and self.moon.klippy_ready else None

    def view(self) -> Dict[str, Any]:
        kr = self.klipper or {}
        p = kr.get("pending") if isinstance(kr.get("pending"), dict) else None
        return {"present": bool(kr), "enabled": kr.get("enabled"), "pending": p, "running": self.running,
                "error": self.error, "result": kr.get("result")}

    def message(self) -> Optional[str]:
        p = self.view()["pending"]
        if not p or self.running:
            return None
        return tr("Print interrupted (power loss?): {file} at layer {layer} – check the part, then resume or discard",
                  file=p.get("file"), layer=p.get("layer") or "?")

    def _check(self) -> Dict[str, Any]:
        kr = self.klipper
        if kr is None:
            raise ResumeError(503, tr("Resume is not set up in Klipper (kobra_resume) or Klipper is not ready"))
        return kr

    def start(self) -> None:
        """KOBRA_RESUME CONFIRM=1 in the background (heat, probe, continue printing - a few minutes)."""
        kr = self._check()
        if not kr.get("pending"):
            raise ResumeError(409, tr("No interrupted print saved"))
        if self.running:
            raise ResumeError(409, tr("Resume is already running"))
        if self.slots.printing:
            raise ResumeError(409, tr("A print is already running"))
        self.running, self.error = True, None

        async def run():
            try:
                await self.moon.gcode("KOBRA_RESUME CONFIRM=1", source=tr("Resume"), timeout=1800)
            except Exception as e:  # noqa: BLE001
                self.error = msg_of(e)
                log.warning("Resume failed: %s", e)
            finally:
                self.running = False
        asyncio.get_running_loop().create_task(run())

    async def discard(self) -> None:
        kr = self._check()
        if not kr.get("pending"):
            raise ResumeError(409, tr("No interrupted print saved"))
        await self.moon.gcode("KOBRA_RESUME_DISCARD", source=tr("Resume"))
        self.error = None

    async def switch(self, enabled: bool) -> None:
        self._check()
        await self.moon.gcode(f"KOBRA_POWERLOSS ENABLE={int(bool(enabled))}", source=tr("Resume"))
