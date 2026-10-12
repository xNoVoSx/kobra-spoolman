"""Print control: pause/resume/cancel/emergency stop and tuning (speed, flow, fans, temperatures).

Klipper: M220, M221, M106, SET_FAN_SPEED FAN=box_fan|air_filter_fan SPEED=0..1, M104, M140. PAUSE/RESUME/CANCEL_PRINT
are the macros of the printer config. After an emergency stop or a shutdown FIRMWARE_RESTART reloads Klipper (action
"firmware_restart"). Rinkhals (GoKlipper, checked on a Kobra S1 on 01.10.2026): the same commands work, CANCEL_PRINT is
passed on to Anycubic's own stop; Rinkhals blocks FIRMWARE_RESTART (GoKlipper would hang) - after an emergency stop only
switching the printer off and on helps. Everything goes through the one Moonraker connection and appears with its
sender in the console.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .i18n import tr

MAX_NOZZLE = 300
WARN_NOZZLE = 260             # above: ask first (like the terminal)
MAX_BED = 110
SPEED = (10, 300)             # %
FLOW = (50, 150)              # %
FANS = {"part": None, "box": "box_fan", "filter": "air_filter_fan"}   # part = part cooling fan (M106)


class ControlError(Exception):
    def __init__(self, status: int, msg: str, confirm: bool = False):
        super().__init__(msg)
        self.status = status
        self.confirm = confirm


def _num(body: Dict[str, Any], key: str) -> Optional[float]:
    if body.get(key) is None:
        return None
    try:
        return float(body[key])
    except (TypeError, ValueError):
        raise ControlError(400, tr("{key} must be a number", key=key)) from None


def _range(name: Any, v: float, lo: float, hi: float) -> None:
    if not lo <= v <= hi:
        raise ControlError(400, tr("{name}: allowed {lo:g} to {hi:g}", name=name, lo=lo, hi=hi))


def tune_commands(body: Dict[str, Any]) -> Tuple[List[str], Optional[str]]:
    """G-code for {speed, flow, fans: {part, box, filter}, nozzle, bed} (percent or degC).
    Second value: reason to ask first (nozzle above WARN_NOZZLE) or None."""
    cmds: List[str] = []
    confirm = None
    v = _num(body, "speed")
    if v is not None:
        _range(tr("Speed"), v, *SPEED)
        cmds.append(f"M220 S{round(v)}")
    v = _num(body, "flow")
    if v is not None:
        _range(tr("Flow"), v, *FLOW)
        cmds.append(f"M221 S{round(v)}")
    fans = body.get("fans") or {}
    if not isinstance(fans, dict):
        raise ControlError(400, tr("fans: expected {\"part\": 50, \"box\": 0, \"filter\": 30}"))
    for key in fans:
        if key not in FANS:
            raise ControlError(400, tr("Unknown fan {key}", key=key))
        v = _num(fans, key)
        if v is None:
            continue
        _range(tr("Fan"), v, 0, 100)
        cmds.append(f"M106 S{round(v * 2.55)}" if FANS[key] is None
                    else f"SET_FAN_SPEED FAN={FANS[key]} SPEED={round(v / 100, 2):g}")
    v = _num(body, "nozzle")
    if v is not None:
        _range(tr("Nozzle"), v, 0, MAX_NOZZLE)
        cmds.append(f"M104 S{round(v)}")
        if v > WARN_NOZZLE:
            confirm = tr("Nozzle to {t} °C (more than {max} °C)", t=round(v), max=WARN_NOZZLE)
    v = _num(body, "bed")
    if v is not None:
        _range(tr("Bed"), v, 0, MAX_BED)
        cmds.append(f"M140 S{round(v)}")
    if not cmds:
        raise ControlError(400, tr("Nothing to change"))
    return cmds, confirm


# actions: Moonraker method, text for the console, only in these states, confirmation needed?
ACTIONS = {
    "pause": ("printer.print.pause", tr("PAUSE (pause the print)"), ("printing",), False),
    "resume": ("printer.print.resume", tr("RESUME (resume the print)"), ("paused",), False),
    "cancel": ("printer.print.cancel", tr("CANCEL_PRINT (cancel the print)"), ("printing", "paused"), True),
    "emergency_stop": ("printer.emergency_stop", tr("EMERGENCY STOP"), None, True),
    # not during a print (would cancel it); after an emergency stop/shutdown ("shutdown", "error") the way back
    "firmware_restart": ("printer.firmware_restart", tr("FIRMWARE_RESTART (reload Klipper)"),
                         ("standby", "complete", "cancelled", "error", "shutdown", "offline", "", None), True),
}


def check_action(action: str, state: Optional[str], confirmed: bool, platform: str = "klipper") -> Tuple[str, str]:
    if action not in ACTIONS:
        raise ControlError(404, tr("Unknown action"))
    if action == "firmware_restart" and platform == "rinkhals":
        raise ControlError(409, tr("Not possible with Rinkhals – switch the printer off and on"))
    method, label, states, needs_confirm = ACTIONS[action]
    if states is not None and state not in states:
        raise ControlError(409, {"pause": tr("No print is running"), "resume": tr("The print is not paused"),
                                 "cancel": tr("No print is running"),
                                 "firmware_restart": tr("A print is running – reloading would cancel it")}[action])
    if needs_confirm and not confirmed:
        raise ControlError(409, {"emergency_stop": tr("Emergency stop: everything stops at once, then switch the printer "
                                                      "off and on") if platform == "rinkhals"
                                 else tr("Emergency stop: everything stops at once, reload Klipper afterwards"),
                                 "cancel": tr("Really cancel the print?"),
                                 "firmware_restart": tr("Reload Klipper? (takes a few seconds)")}[action],
                           confirm=True)
    return method, label
