"""Sync through G-code (auto PA values, Z offset per slot): at most one request in flight, never resent.

Klipper runs API G-code only when no other command is running - during the print start (G9111 is a single macro)
that can take minutes. Up to 3.11.0 every request timed out after 15 s and was resent with the next status; dozens of
requests piled up in Klipper (and a PAUSE behind them). Now: one request with a long deadline; the caller waits only
briefly and learns the result through on_done."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from .moonraker import Moonraker

log = logging.getLogger("gcodepush")

WAIT_S = 2.0          # the caller (status processing) waits at most this long
TIMEOUT_S = 3600.0    # Klipper may take this long (longest print start with heat soak)


class GcodePush:
    def __init__(self, moon: "Moonraker", source: str, wait_s: float = WAIT_S, timeout_s: float = TIMEOUT_S):
        self.moon, self.source = moon, source
        self.wait_s, self.timeout_s = wait_s, timeout_s
        self._task: Optional[asyncio.Task] = None

    @property
    def busy(self) -> bool:
        """A request is still open (Klipper busy) - send nothing new meanwhile."""
        return self._task is not None and not self._task.done()

    async def send(self, script: str, on_done: Callable[[bool, Optional[Exception]], None]) -> None:
        """Send script (not while busy); on_done(ok, error) runs as soon as Klipper has answered."""
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
