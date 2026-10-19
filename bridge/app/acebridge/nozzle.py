"""Swappable hotends: PID, nozzle and Z correction per hotend (e.g. 0.2/0.4/0.6 ceramic hotends next to the original).

The Klipper module kobra_nozzle (kobra-klipper) holds the hotends and their values: it sets the PID of the hotend in use
at runtime, measures it per hotend (KOBRA_NOZZLE_PID, saved without SAVE_CONFIG), gives the nozzle to Auto PA and
stops a print sliced for another nozzle (G9111 NOZZLE=). This side:
- reads `kobra_nozzle` from the subscription,
- switches (POST /api/nozzle: hotend in use, print start check, on/off, Z correction) and starts a PID measurement
  (POST /api/nozzle/pid, runs a few minutes in the background, the result comes with the status),
- tells Auto PA the nozzle (pa.py: one table per nozzle), and the print start check (printcheck.py) compares files
  without NOZZLE= (e.g. from Anycubic's slicer) by Orca's "; nozzle_diameter" comment.
Without kobra_nozzle in Klipper (Rinkhals, older kobra-klipper) everything stays as before (nozzle 0.4).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any, Dict, Optional

from .i18n import msg_of, tr

if TYPE_CHECKING:
    from .moonraker import Moonraker

log = logging.getLogger("nozzle")

OBJ = "kobra_nozzle"
SUBSCRIBE = {OBJ: ["enabled", "check", "active", "default", "name", "diameter", "z", "pid", "pid_source", "measuring", "result",
                   "hotends"]}
PID_TEMP = (150, 320)        # °C, like kobra_nozzle
Z_MAX = 0.5                  # mm, like KOBRA_START
_ID = re.compile(r"^[a-z0-9_]{1,40}$")


class NozzleError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


class Hotends:
    def __init__(self, moon: "Moonraker"):
        self.moon = moon
        self.task: Optional[asyncio.Task] = None
        self.error: Optional[str] = None           # last failed PID measurement (G-code error)

    # ------------------------------------------------------------ state
    @property
    def raw(self) -> Dict[str, Any]:
        return self.moon.status.get(OBJ) or {}

    @property
    def available(self) -> bool:
        return bool(self.moon.klippy_ready and OBJ in self.moon.status)

    @property
    def active(self) -> bool:
        return self.available and bool(self.raw.get("enabled"))

    def diameter(self) -> Optional[float]:
        d = self.raw.get("diameter")
        return float(d) if self.active and isinstance(d, (int, float)) and d > 0 else None

    def view(self) -> Dict[str, Any]:
        """For web, app and display (/api/app/state "nozzle")."""
        r = self.raw
        hotends = [{"id": h.get("id"), "name": h.get("name"), "diameter": h.get("diameter"),
                    "pid": bool(h.get("pid")), "z": h.get("z") or 0.0,
                    "default": h.get("id") == r.get("default")}         # its PID is the one in [extruder]
                   for h in (r.get("hotends") or [])]
        cur = next((h for h in hotends if h["id"] == r.get("active")), None)
        measured = bool(cur and cur["pid"])
        res = r.get("result") if isinstance(r.get("result"), dict) else None
        return {
            "available": self.available,
            "enabled": bool(r.get("enabled")),
            "check": bool(r.get("check")),
            "active": r.get("active"),
            "name": r.get("name"),
            "diameter": r.get("diameter"),
            "z": r.get("z") or 0.0,
            "pid": r.get("pid") or [],                               # lists never null (app)
            "pid_measured": measured,
            "measuring": bool(r.get("measuring")) or (self.task is not None and not self.task.done()),
            "hotends": hotends,
            "last": ({"hotend": res.get("id"), "ok": "error" not in res, "time": res.get("time"),
                      "pid": [res.get(k) for k in ("kp", "ki", "kd")] if "error" not in res else [],
                      "error": res.get("error")} if res else None),
            "error": self.error,
            # an uncalibrated hotend heats with the PID of [extruder] (the original's) - say so
            "warning": (tr("PID of {name} not measured yet – it heats with the values of the original hotend. "
                           "Measure it once.", name=r.get("name") or "?")
                        if self.active and cur and not measured and cur["id"] != r.get("default") else None),
        }

    # ------------------------------------------------------------ switching
    def _ready(self) -> None:
        if not self.available:
            raise NozzleError(503, tr("Swappable hotends are not set up in Klipper (module kobra_nozzle) or Klipper "
                                      "is not ready"))

    def _idle(self) -> None:
        state = (self.moon.status.get("print_stats") or {}).get("state")
        if state in ("printing", "paused"):
            raise NozzleError(409, tr("Not during a print"))
        if self.view()["measuring"]:
            raise NozzleError(409, tr("A PID measurement is running"))

    async def set(self, hotend: Optional[str] = None, check: Optional[bool] = None, enabled: Optional[bool] = None,
                  z: Optional[float] = None) -> Dict[str, Any]:
        self._ready()
        parts = []
        if hotend is not None:
            ids = [h.get("id") for h in self.raw.get("hotends") or []]
            if not isinstance(hotend, str) or not _ID.match(hotend) or hotend not in ids:
                raise NozzleError(404, tr("Unknown hotend {id}", id=hotend))
            parts.append(f"SELECT={hotend}")
        if enabled is not None:
            parts.append(f"ENABLE={int(bool(enabled))}")
        if hotend is not None or enabled is not None:
            self._idle()
        if check is not None:
            parts.append(f"CHECK_PRINT={int(bool(check))}")
        if z is not None:
            if not -Z_MAX <= z <= Z_MAX:
                raise NozzleError(400, tr("Z correction between −{max} and +{max} mm", max=Z_MAX))
            parts.append(f"Z={z:.3f}")
        if not parts:
            raise NozzleError(400, tr("nothing to change (hotend, check, enabled, z)"))
        try:
            await self.moon.gcode("KOBRA_NOZZLE " + " ".join(parts), source=tr("Hotends"))
        except Exception as e:  # noqa: BLE001
            raise NozzleError(409, msg_of(e)) from e
        if hotend is not None:
            for _ in range(30):                     # answer with the new state (it comes with the next status)
                if self.raw.get("active") == hotend:
                    break
                await asyncio.sleep(0.1)
            log.info("Hotend: %s", hotend)
        return self.view()

    def measure_pid(self, temp: Optional[float] = None) -> Dict[str, Any]:
        """Start the PID measurement of the hotend in use (a few minutes, in the background)."""
        self._ready()
        if not self.raw.get("enabled"):
            raise NozzleError(409, tr("Swappable hotends are switched off in Klipper"))
        self._idle()
        if temp is not None and not PID_TEMP[0] <= temp <= PID_TEMP[1]:
            raise NozzleError(400, tr("Temperature {min}–{max} °C", min=PID_TEMP[0], max=PID_TEMP[1]))
        script = "KOBRA_NOZZLE_PID" + (f" TEMP={temp:g}" if temp is not None else "")
        self.error = None

        async def run() -> None:
            try:
                await self.moon.gcode(script, timeout=900, source=tr("Hotends"))
                log.info("Hotend %s: PID measured", self.raw.get("active"))
            except Exception as e:  # noqa: BLE001
                self.error = msg_of(e) or type(e).__name__
                log.warning("Hotend %s: PID measurement failed: %s", self.raw.get("active"), self.error)
        self.task = asyncio.get_running_loop().create_task(run())
        return self.view()
