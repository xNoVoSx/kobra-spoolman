"""Fortsetzen nach Stromausfall: Sicht der Bridge auf das Klipper-Modul kobra_resume (kobra-klipper).

Klipper sichert im Druck laufend die zuletzt ausgefuehrte Stelle. Ist nach dem Einschalten ein unterbrochener Druck
gespeichert, zeigt die Bridge das als rote Meldung (Alarm in der App) und als Karte mit Kamerabild; fortgesetzt wird
nur auf Knopfdruck (KOBRA_RESUME CONFIRM=1 - Klipper tastet dabei Z auf das Teil an).
Abschaltbar in Klipper: KOBRA_POWERLOSS ENABLE=0 (POST /api/resume/switch).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

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
        self.running = False          # Fortsetzen laeuft (dauert einige Minuten: heizen, antasten, spuelen)
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
        return (f"Druck unterbrochen (Stromausfall?): {p.get('file')} bei Schicht {p.get('layer') or '?'} – "
                "Teil prüfen, dann fortsetzen oder verwerfen")

    def _check(self) -> Dict[str, Any]:
        kr = self.klipper
        if kr is None:
            raise ResumeError(503, "Fortsetzen ist in Klipper nicht eingerichtet (kobra_resume) oder Klipper nicht bereit")
        return kr

    def start(self) -> None:
        """KOBRA_RESUME CONFIRM=1 im Hintergrund (heizen, antasten, weiterdrucken - einige Minuten)."""
        kr = self._check()
        if not kr.get("pending"):
            raise ResumeError(409, "Kein unterbrochener Druck gespeichert")
        if self.running:
            raise ResumeError(409, "Fortsetzen läuft schon")
        if self.slots.printing:
            raise ResumeError(409, "Es läuft schon ein Druck")
        self.running, self.error = True, None

        async def run():
            try:
                await self.moon.gcode("KOBRA_RESUME CONFIRM=1", source="Fortsetzen", timeout=1800)
            except Exception as e:  # noqa: BLE001
                self.error = str(e)
                log.warning("Fortsetzen fehlgeschlagen: %s", e)
            finally:
                self.running = False
        asyncio.get_running_loop().create_task(run())

    async def discard(self) -> None:
        kr = self._check()
        if not kr.get("pending"):
            raise ResumeError(409, "Kein unterbrochener Druck gespeichert")
        await self.moon.gcode("KOBRA_RESUME_DISCARD", source="Fortsetzen")
        self.error = None

    async def switch(self, enabled: bool) -> None:
        self._check()
        await self.moon.gcode(f"KOBRA_POWERLOSS ENABLE={int(bool(enabled))}", source="Fortsetzen")
