"""Verstopfung erkennen: Sicht der Bridge auf das Klipper-Modul kobra_clog (kobra-klipper).

Klipper vergleicht im Druck je Fenster (20 mm) die Extruder-Foerderung mit dem Encoder am Filament-Eingang. Faellt
das Verhaeltnis zweimal hintereinander unter die Grenze, meldet es einen Verdacht (`suspect`) - die Bridge zeigt
dann eine rote Meldung (Alarm in der App), bis wieder normal gefoerdert wird oder der Druck pausiert/endet.
Reaktion in Klipper: nur warnen (Standard) oder zusaetzlich pausieren.
Abschaltbar in Klipper: KOBRA_CLOG ENABLE=0 (POST /api/clog/switch), dort auch ACTION=warn|pause.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from .moonraker import Moonraker

OBJ = "kobra_clog"
SUBSCRIBE = {OBJ: ["enabled", "action", "available", "suspect", "alarm", "alarms", "last", "min_ratio"]}
ACTIONS = ("warn", "pause")


class ClogError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


class Clog:
    def __init__(self, moon: "Moonraker"):
        self.moon = moon

    @property
    def klipper(self) -> Optional[Dict[str, Any]]:
        st = self.moon.status.get(OBJ)
        return st if st is not None and self.moon.klippy_ready else None

    def view(self) -> Dict[str, Any]:
        kr = self.klipper or {}
        alarm = kr.get("alarm") if isinstance(kr.get("alarm"), dict) else None
        last = kr.get("last") if isinstance(kr.get("last"), list) and len(kr["last"]) >= 4 else None
        return {"present": bool(kr), "enabled": kr.get("enabled"), "action": kr.get("action"),
                "available": kr.get("available"), "suspect": bool(kr.get("suspect")), "alarm": alarm,
                "alarms": kr.get("alarms") or 0, "min_ratio": kr.get("min_ratio"),
                "last_ratio": last[3] if last else None}

    def message(self) -> Optional[str]:
        v = self.view()
        if not v["suspect"] or not v["alarm"]:
            return None
        a = v["alarm"]
        text = (f"Verstopfung? Extruder {a.get('extruder_mm', 0):.0f} mm gefördert, Encoder sah nur "
                f"{a.get('encoder_mm', 0):.0f} mm ({100 * (a.get('ratio') or 0):.0f} %)")
        return text + (" – Druck pausiert" if a.get("action") == "pause" else " – Düse und Filamentweg prüfen")

    async def switch(self, enabled: Optional[bool] = None, action: Optional[str] = None) -> None:
        if self.klipper is None:
            raise ClogError(503, "Verstopfungserkennung ist in Klipper nicht eingerichtet (kobra_clog) "
                                 "oder Klipper nicht bereit")
        if action is not None and action not in ACTIONS:
            raise ClogError(400, "action: warn oder pause")
        parts = ([f"ENABLE={int(bool(enabled))}"] if enabled is not None else []) + \
            ([f"ACTION={action}"] if action is not None else [])
        if not parts:
            raise ClogError(400, "Erwartet enabled und/oder action")
        await self.moon.gcode("KOBRA_CLOG " + " ".join(parts), source="Verstopfung")
