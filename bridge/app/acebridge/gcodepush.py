"""Abgleich per G-Code (Auto-PA-Werte, Z-Versatz je Slot): hoechstens eine Anfrage offen, nie nachschiessen.

Klipper fuehrt G-Code ueber die API erst aus, wenn kein anderer Befehl laeuft - im Startablauf (G9111 ist ein
einziges Makro) also erst nach Minuten. Bis 3.11.0 lief jede Anfrage nach 15 s in einen Timeout und wurde beim
naechsten Status neu geschickt; in Klipper stauten sich so dutzende Anfragen (und PAUSE dahinter). Jetzt: eine
Anfrage mit langer Frist, der Aufrufer wartet nur kurz und erfaehrt das Ergebnis ueber on_done."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from .moonraker import Moonraker

log = logging.getLogger("gcodepush")

WAIT_S = 2.0          # so lange wartet der Aufrufer (Statusverarbeitung) hoechstens
TIMEOUT_S = 3600.0    # so lange darf Klipper brauchen (laengster Startablauf mit Durchwaermen)


class GcodePush:
    def __init__(self, moon: "Moonraker", source: str, wait_s: float = WAIT_S, timeout_s: float = TIMEOUT_S):
        self.moon, self.source = moon, source
        self.wait_s, self.timeout_s = wait_s, timeout_s
        self._task: Optional[asyncio.Task] = None

    @property
    def busy(self) -> bool:
        """Eine Anfrage ist noch offen (Klipper beschaeftigt) - dann nichts Neues schicken."""
        return self._task is not None and not self._task.done()

    async def send(self, script: str, on_done: Callable[[bool, Optional[Exception]], None]) -> None:
        """script schicken (nicht, solange busy); on_done(ok, fehler) laeuft, sobald Klipper geantwortet hat."""
        if self.busy:
            return

        async def run():
            try:
                await self.moon.gcode(script, timeout=self.timeout_s, source=self.source)
            except Exception as e:  # noqa: BLE001
                on_done(False, e)
            else:
                on_done(True, None)
        self._task = asyncio.get_running_loop().create_task(run())
        await asyncio.wait({self._task}, timeout=self.wait_s)
