"""Clog detection: the bridge's view of the Klipper module kobra_clog (kobra-klipper).

During a print Klipper compares, per window (20 mm), what the extruder pushed with the encoder at the filament inlet.
If the ratio drops below the limit twice in a row it reports a suspicion (`suspect`) - the bridge then shows a red
message (alarm in the app) until feeding is normal again or the print pauses/ends.
Reaction in Klipper: warn only (default) or also pause.
Can be switched off in Klipper: KOBRA_CLOG ENABLE=0 (POST /api/clog/switch), there also ACTION=warn|pause.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

from .i18n import tr

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
        vals = {"ext": a.get("extruder_mm", 0), "enc": a.get("encoder_mm", 0), "pct": 100 * (a.get("ratio") or 0)}
        if a.get("action") == "pause":
            return tr("Clog? Extruder pushed {ext:.0f} mm, the encoder saw only {enc:.0f} mm ({pct:.0f} %) – "
                      "print paused", **vals)
        return tr("Clog? Extruder pushed {ext:.0f} mm, the encoder saw only {enc:.0f} mm ({pct:.0f} %) – "
                  "check the nozzle and the filament path", **vals)

    async def switch(self, enabled: Optional[bool] = None, action: Optional[str] = None) -> None:
        if self.klipper is None:
            raise ClogError(503, tr("Clog detection is not set up in Klipper (kobra_clog) or Klipper is not ready"))
        if action is not None and action not in ACTIONS:
            raise ClogError(400, tr("action: warn or pause"))
        parts = ([f"ENABLE={int(bool(enabled))}"] if enabled is not None else []) + \
            ([f"ACTION={action}"] if action is not None else [])
        if not parts:
            raise ClogError(400, tr("Expected enabled and/or action"))
        await self.moon.gcode("KOBRA_CLOG " + " ".join(parts), source=tr("Clog detection"))
