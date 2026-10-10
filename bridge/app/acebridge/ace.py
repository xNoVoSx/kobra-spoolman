"""ACE-Karte: Einstellungen des ACE-Treibers (Klipper + ACEPRO), die das Druckerdisplay nicht zeigt.

Lesen: live aus dem Moonraker-Abo (Objekt `ace`, acemodel.endless_spool) - keine eigene Abfrage.
Schreiben (G-Code des Treibers, gilt sofort, auch waehrend eines Drucks):
- Endlosspule:   ACE_ENABLE_ENDLESS_SPOOL / ACE_DISABLE_ENDLESS_SPOOL
- Modus:         ACE_SET_ENDLESS_SPOOL_MODE MODE=exact|material|next

Die Spuelmengen kommen aus Orcas Matrix (der Filamentwechsel-G-Code gibt sie an den Treiber), Runout ueberwacht
der Treiber immer - beides ist hier kein Schalter.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Dict

from . import acemodel

if TYPE_CHECKING:
    from .moonraker import Moonraker
    from .slots import SlotManager

log = logging.getLogger("ace")

MODES = {"exact": "gleiche Farbe und gleiches Material", "material": "gleiches Material", "next": "nächste Spule"}
CONFIRM_WAIT_S = 2.0      # so lange auf die Rueckmeldung des Treibers warten (Antwort zeigt dann den neuen Stand)


class AceError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


class AceSettings:
    def __init__(self, moon: "Moonraker", slots: "SlotManager"):
        self.moon = moon
        self.slots = slots

    async def refresh(self, force: bool = False) -> None:
        """Nichts abzufragen - der Treiber meldet seine Einstellungen im Abo (fuer den Ticker der Bridge)."""

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
            raise AceError(503, "ACE nicht verbunden")

    async def set_options(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        """Endlosspule an/aus (endless_spool) und Modus (endless_mode) - unkritisch, auch im Druck, gilt beim naechsten
        Runout."""
        cmds, want = [], {}
        for k, v in changes.items():
            if k == "endless_spool":
                if not isinstance(v, bool):
                    raise AceError(400, f"{k}: true oder false")
                cmds.append("ACE_ENABLE_ENDLESS_SPOOL" if v else "ACE_DISABLE_ENDLESS_SPOOL")
                want["enabled"] = v
            elif k == "endless_mode":
                if v not in MODES:
                    raise AceError(400, "Modus: " + ", ".join(MODES))
                cmds.append(f"ACE_SET_ENDLESS_SPOOL_MODE MODE={v}")
                want["mode"] = v
            else:
                raise AceError(400, f"Unbekannte Einstellung {k}")
        if not cmds:
            raise AceError(400, "nichts zu ändern")
        self._check()
        await self.moon.gcode("\n".join(cmds), source="ACE-Karte")
        log.info("ACE-Einstellungen: %s", "; ".join(cmds))
        await self._wait_for(want)
        return self.state()

    async def _wait_for(self, want: Dict[str, Any]) -> None:
        """Bis der Treiber den neuen Stand im Abo meldet (hoechstens CONFIRM_WAIT_S)."""
        end = time.monotonic() + CONFIRM_WAIT_S
        while time.monotonic() < end:
            cur = acemodel.endless_spool(self.moon.status)
            if all(cur.get(k) == v for k, v in want.items()):
                return
            await asyncio.sleep(0.1)

