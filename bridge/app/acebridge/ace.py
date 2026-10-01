"""Einstellungen der ACE, die das Druckerdisplay versteckt (GoKlipper filament_hub).

Lesen: GET /printer/filament_hub/get_config ueber Moonraker, z.B.
    {"auto_refill": 1, "flush_multiplier": 1, "flush_multiplier_editable": 1,
     "flush_volume_max": 800, "flush_volume_min": 107, "runout_detect": 1}
Schreiben:
- Spuel-Multiplikator ueber Rinkhals' SET_ACE_FLUSH_MULTIPLIER VALUE=<0.0-3.0> (der offizielle Weg; Rinkhals
  ruft dafuer filament_hub/set_config auf)
- auto_refill / runout_detect ueber filament_hub/set_config, genauso wie Rinkhals es fuer den Multiplikator tut
Danach wird sofort neu gelesen, damit die Anzeige den Stand am Drucker zeigt.

Waehrend eines Drucks gilt eine Aenderung ab dem naechsten Farbwechsel bzw. Leerlauf; die API verlangt dann
ausdruecklich "confirm_printing": true (die Oberflaeche schaltet das Feld erst nach einem Extra-Knopf frei).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from .purge import AREA_175, CONFIG_REFRESH_S, change_mm, firmware_volume

if TYPE_CHECKING:
    from .moonraker import Moonraker
    from .purge import PurgeModel
    from .slots import SlotManager
    from .spoolman import Spoolman

log = logging.getLogger("ace")

FLUSH_MIN, FLUSH_MAX = 0.1, 3.0          # Rinkhals erlaubt 0-3; 0 hiesse gar nicht spuelen
PRESETS = {"minimal": 0.1, "normal": 1.0, "maximum": 3.0}    # wie Rinkhals' ACE_FLUSH_MINIMAL/NORMAL/MAXIMUM
OPTIONS = ("auto_refill", "runout_detect")


class AceError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


class AceSettings:
    def __init__(self, moon: "Moonraker", purge: "PurgeModel", slots: "SlotManager", sm: "Spoolman",
                 clock: Callable[[], float] = time.monotonic):
        self.moon = moon
        self.purge = purge
        self.slots = slots
        self.sm = sm
        self.clock = clock
        self.config: Dict[str, Any] = {}
        self.read_at: Optional[float] = None
        self._tried = 0.0

    # ------------------------------------------------------------ Lesen
    async def refresh(self, force: bool = False) -> None:
        """Alle 10 Minuten (nach einer Aenderung sofort); nach Fehlschlag ebenfalls erst nach 10 Minuten."""
        if not self.moon.klippy_ready:
            return
        now = self.clock()
        if not force and self._tried and now - self._tried < CONFIG_REFRESH_S:
            return
        self._tried = now
        try:
            cfg = await self.moon.get_json("/printer/filament_hub/get_config")
        except Exception as e:  # noqa: BLE001
            log.info("ACE-Einstellungen nicht lesbar: %s", e)
            return
        if isinstance(cfg, dict) and cfg:
            self.config = dict(cfg)
            self.read_at = time.time()
            self.purge.set_flush_config(cfg)

    def state(self) -> Dict[str, Any]:
        c = self.config
        return {
            "present": bool(c),
            "flush_multiplier": c.get("flush_multiplier"),
            "flush_multiplier_editable": bool(c.get("flush_multiplier_editable", 1)),
            "flush_volume_min": c.get("flush_volume_min"),
            "flush_volume_max": c.get("flush_volume_max"),
            "auto_refill": None if "auto_refill" not in c else bool(c["auto_refill"]),
            "runout_detect": None if "runout_detect" not in c else bool(c["runout_detect"]),
            "read_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.read_at)) if self.read_at else None,
            "printing": self.slots.printing,
            "limits": {"flush_multiplier": [FLUSH_MIN, FLUSH_MAX]},
            "presets": PRESETS,
        }

    # ------------------------------------------------------------ Schreiben
    def _check(self, confirm_printing: bool) -> None:
        if not self.moon.klippy_ready:
            raise AceError(503, "Drucker nicht bereit")
        if self.slots.printing and not confirm_printing:
            raise AceError(409, "Es läuft ein Druck – Änderung erst nach dem Freischalten (gilt ab dem nächsten Farbwechsel)")

    async def set_flush_multiplier(self, value: Any, confirm_printing: bool = False) -> Dict[str, Any]:
        try:
            v = round(float(value), 2)
        except (TypeError, ValueError):
            raise AceError(400, "Multiplikator als Zahl angeben") from None
        if not FLUSH_MIN <= v <= FLUSH_MAX:
            raise AceError(400, f"Multiplikator {FLUSH_MIN:g} bis {FLUSH_MAX:g}")
        if self.config and not self.config.get("flush_multiplier_editable", 1):
            raise AceError(409, "Die Firmware erlaubt gerade keine Änderung des Multiplikators")
        self._check(confirm_printing)
        await self.moon.gcode(f"SET_ACE_FLUSH_MULTIPLIER VALUE={v:g}")
        log.info("Spuel-Multiplikator auf %g gesetzt%s", v, " (waehrend des Drucks)" if self.slots.printing else "")
        await self.refresh(force=True)
        return self.state()

    async def set_options(self, changes: Dict[str, Any], confirm_printing: bool = False) -> Dict[str, Any]:
        body = {}
        for k, v in changes.items():
            if k not in OPTIONS:
                raise AceError(400, f"Unbekannte Einstellung {k}")
            if not isinstance(v, bool):
                raise AceError(400, f"{k}: true oder false")
            body[k] = 1 if v else 0
        if not body:
            raise AceError(400, "nichts zu ändern")
        self._check(confirm_printing)
        await self.moon.post_json("/printer/filament_hub/set_config", body)
        log.info("ACE-Einstellungen: %s", body)
        await self.refresh(force=True)
        return self.state()

    # ------------------------------------------------------------ Vorschau
    def purge_preview(self, multiplier: Optional[float] = None) -> Dict[str, Any]:
        """Spuelen fuer jeden Wechsel zwischen den eingelegten Spulen - mit dem aktuellen oder einem
        gewuenschten Multiplikator. Farben wie die ACE sie meldet; Gramm mit der Dichte des Filaments."""
        flush = dict(self.purge.flush)
        if multiplier is not None:
            flush["flush_multiplier"] = float(multiplier)
        assigned, _ = self.slots.assignments()
        gates: List[Dict[str, Any]] = []
        for gate in range(self.slots.num_gates()):
            ace = self.slots.ace_gate(gate)
            spool = assigned.get(gate + 1)
            color = ace.get("color") or ((spool or {}).get("filament") or {}).get("color_hex")
            if not color or not (ace.get("present") or spool):
                continue
            fil = (spool or {}).get("filament") or {}
            gates.append({"slot": gate + 1, "color": color, "density": fil.get("density") or 1.24,
                          "name": f"{(fil.get('vendor') or {}).get('name', '')} {fil.get('name') or ''}".strip()
                          or ace.get("material") or f"Slot {gate + 1}"})
        pairs = []
        for a in gates:
            for b in gates:
                if a is b:
                    continue
                mm = change_mm(a["color"], b["color"], flush, self.purge.offset_mm)
                if mm is None:
                    continue
                pairs.append({"from_slot": a["slot"], "to_slot": b["slot"], "from_name": a["name"],
                              "to_name": b["name"], "from_color": a["color"], "to_color": b["color"],
                              "volume_mm3": int(firmware_volume(a["color"], b["color"], flush) or 0),
                              "mm": round(mm, 1), "g": round(mm * AREA_175 * b["density"] / 1000, 2)})
        return {"flush_multiplier": flush["flush_multiplier"], "first_load_mm": round(self.purge.first_load_mm, 1),
                "slots": gates, "pairs": pairs}
