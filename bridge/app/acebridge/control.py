"""Drucksteuerung: Pause/Weiter/Abbrechen/Not-Aus und Nachjustieren (Tempo, Fluss, Luefter, Temperaturen).

Klipper am Pi (Tunnel): M220, M221, M106, SET_FAN_SPEED FAN=box_fan|air_filter_fan SPEED=0..1, M104, M140.
PAUSE/RESUME/CANCEL_PRINT sind die Makros der Konfiguration (kobra-klipper). Nach einem Not-Aus oder einer
Abschaltung laedt FIRMWARE_RESTART Klipper neu (Aktion "firmware_restart"). Alles geht ueber die eine
Moonraker-Verbindung und steht mit Absender in der Konsole.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

MAX_NOZZLE = 300
WARN_NOZZLE = 260             # darueber Rueckfrage (wie im Terminal)
MAX_BED = 110
SPEED = (10, 300)             # %
FLOW = (50, 150)              # %
FANS = {"part": None, "box": "box_fan", "filter": "air_filter_fan"}   # part = Bauteilluefter (M106)


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
        raise ControlError(400, f"{key} muss eine Zahl sein") from None


def _range(name: str, v: float, lo: float, hi: float) -> None:
    if not lo <= v <= hi:
        raise ControlError(400, f"{name}: erlaubt {lo:g} bis {hi:g}")


def tune_commands(body: Dict[str, Any]) -> Tuple[List[str], Optional[str]]:
    """G-Code fuer {speed, flow, fans: {part, box, filter}, nozzle, bed} (Prozent bzw. °C).
    Zweiter Wert: Grund fuer eine Rueckfrage (Duese ueber WARN_NOZZLE) oder None."""
    cmds: List[str] = []
    confirm = None
    v = _num(body, "speed")
    if v is not None:
        _range("Tempo", v, *SPEED)
        cmds.append(f"M220 S{round(v)}")
    v = _num(body, "flow")
    if v is not None:
        _range("Fluss", v, *FLOW)
        cmds.append(f"M221 S{round(v)}")
    fans = body.get("fans") or {}
    if not isinstance(fans, dict):
        raise ControlError(400, "fans: erwartet {\"part\": 50, \"box\": 0, \"filter\": 30}")
    for key in fans:
        if key not in FANS:
            raise ControlError(400, f"Unbekannter Lüfter {key}")
        v = _num(fans, key)
        if v is None:
            continue
        _range("Lüfter", v, 0, 100)
        cmds.append(f"M106 S{round(v * 2.55)}" if FANS[key] is None
                    else f"SET_FAN_SPEED FAN={FANS[key]} SPEED={round(v / 100, 2):g}")
    v = _num(body, "nozzle")
    if v is not None:
        _range("Düse", v, 0, MAX_NOZZLE)
        cmds.append(f"M104 S{round(v)}")
        if v > WARN_NOZZLE:
            confirm = f"Düse auf {round(v)} °C (mehr als {WARN_NOZZLE} °C)"
    v = _num(body, "bed")
    if v is not None:
        _range("Bett", v, 0, MAX_BED)
        cmds.append(f"M140 S{round(v)}")
    if not cmds:
        raise ControlError(400, "Nichts zu ändern")
    return cmds, confirm


# Aktionen: Moonraker-Methode, Text fuer die Konsole, nur in diesen Zustaenden, Rueckfrage noetig?
ACTIONS = {
    "pause": ("printer.print.pause", "PAUSE (Druck pausieren)", ("printing",), False),
    "resume": ("printer.print.resume", "RESUME (Druck fortsetzen)", ("paused",), False),
    "cancel": ("printer.print.cancel", "CANCEL_PRINT (Druck abbrechen)", ("printing", "paused"), True),
    "emergency_stop": ("printer.emergency_stop", "NOT-AUS", None, True),
    # nicht waehrend eines Drucks (bricht ihn ab); nach Not-Aus/Abschaltung ("shutdown", "error") der Weg zurueck
    "firmware_restart": ("printer.firmware_restart", "FIRMWARE_RESTART (Klipper neu laden)",
                         ("standby", "complete", "cancelled", "error", "shutdown", "offline", "", None), True),
}


def check_action(action: str, state: Optional[str], confirmed: bool) -> Tuple[str, str]:
    if action not in ACTIONS:
        raise ControlError(404, "Unbekannte Aktion")
    method, label, states, needs_confirm = ACTIONS[action]
    if states is not None and state not in states:
        raise ControlError(409, {"pause": "Es läuft kein Druck", "resume": "Der Druck ist nicht pausiert",
                                 "cancel": "Es läuft kein Druck",
                                 "firmware_restart": "Es läuft ein Druck – Neuladen würde ihn abbrechen"}[action])
    if needs_confirm and not confirmed:
        raise ControlError(409, {"emergency_stop": "Not-Aus: alles stoppt sofort, danach Klipper neu laden",
                                 "cancel": "Druck wirklich abbrechen?",
                                 "firmware_restart": "Klipper neu laden? (dauert einige Sekunden)"}[action],
                           confirm=True)
    return method, label
