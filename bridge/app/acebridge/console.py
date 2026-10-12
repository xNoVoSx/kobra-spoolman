"""Console: what the printer answers, which commands were sent (by whom) - and a bridge log.

- Printer answers arrive as notify_gcode_response over the bridge's one WebSocket connection (no extra client, no
  polling). On connecting, server.gcode_store once as a backlog.
- Commands that go through the bridge (web UI, dryer, ACE, slots) appear with their source. Commands of other clients
  (Mainsail) Moonraker only shows through their answers.
- Risky commands need a confirmation (check_command), moves during a print too.
- LogBuffer keeps the last lines of the bridge log for the "Logs" page and the app.
"""

from __future__ import annotations

import collections
import itertools
import logging
import re
import time
from typing import Any, Callable, Deque, Dict, List, Optional

from .i18n import Text, tr

log = logging.getLogger("console")

KEEP_LINES = 500
KEEP_LOG = 2000
MAX_HOTEND = 260          # above: ask first

# command (first word) -> reason to ask first
RISKY = {
    "M112": tr("Emergency stop: everything stops at once, reload Klipper afterwards (FIRMWARE_RESTART)"),
    "EMERGENCY_STOP": tr("Emergency stop: everything stops at once, reload Klipper afterwards (FIRMWARE_RESTART)"),
    "FIRMWARE_RESTART": tr("Reloads Klipper – a running print is cancelled"),
    "RESTART": tr("Reloads Klipper – a running print is cancelled"),
    "SAVE_CONFIG": tr("Writes the printer config and restarts"),
    "CANCEL_PRINT": tr("Cancels the running print"),
    "SDCARD_RESET_FILE": tr("Resets the running print file"),
    "PID_CALIBRATE": tr("Heats up a lot (calibration)"),
    "SET_KINEMATIC_POSITION": tr("Sets the position without homing – can crash"),
    "FORCE_MOVE": tr("Moves a motor without limits – can crash"),
}
MOVES = re.compile(r"^(G0|G1|G2|G3|G28|G29|G92|M84|M18|BED_MESH_CALIBRATE|KOBRA_BED_MESH_ALL|G9111|PROBE\w*|"
                   r"MOVE_TO_\w+|WIPE_\w+|SHAPER_CALIBRATE|TEST_RESONANCES|T\d+|ACE_CHANGE_TOOL|CUT_TIP)$")
TEMP_CMD = re.compile(r"^(M104|M109)$")
TEMP_ARG = re.compile(r"\bS(\d+(?:\.\d+)?)", re.I)
SET_HEATER = re.compile(r"HEATER=extruder\b.*\bTARGET=(\d+(?:\.\d+)?)", re.I)


def check_command(script: str, printing: bool) -> Optional[str]:
    """Reason to ask first, or None. Checks every line of the script."""
    for raw in script.splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        word = line.split()[0].upper()
        if word in RISKY:
            return tr("{cmd}: {reason}", cmd=word, reason=RISKY[word])
        temp = None
        if TEMP_CMD.match(word):
            m = TEMP_ARG.search(line)
            temp = float(m.group(1)) if m else None
        elif word == "SET_HEATER_TEMPERATURE":
            m = SET_HEATER.search(line)
            temp = float(m.group(1)) if m else None
        if temp is not None and temp > MAX_HOTEND:
            return tr("{cmd}: nozzle to {t:g} °C (more than {max} °C)", cmd=word, t=temp, max=MAX_HOTEND)
        if printing and MOVES.match(word):
            return tr("{cmd}: move during a print", cmd=word)
    return None


class Console:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.lines: Deque[Dict[str, Any]] = collections.deque(maxlen=KEEP_LINES)
        self._ids = itertools.count(1)
        self.listeners: List[Callable[[Dict[str, Any]], None]] = []   # e.g. print recording (telemetry)

    def add(self, kind: str, text: str, source: Optional[str] = None, at: Optional[float] = None) -> None:
        """kind: command | response | error"""
        if not isinstance(text, Text):                # a translatable label stays translatable
            text = (text or "").rstrip()
        if not text:
            return
        entry = {"id": next(self._ids), "time": round(at if at is not None else self.clock(), 3),
                 "kind": kind, "text": text, "source": source}
        self.lines.append(entry)
        for listener in self.listeners:
            try:
                listener(entry)
            except Exception:  # noqa: BLE001 - a recording must never disturb the console
                log.exception("Console listener")

    def seed(self, store: List[Dict[str, Any]]) -> None:
        """Backlog from server.gcode_store - only while empty (not twice after a reconnect)."""
        if self.lines:
            return
        for e in store or []:
            kind = "command" if e.get("type") == "command" else "response"
            self.add(kind, e.get("message") or "", tr("History") if kind == "command" else None, e.get("time"))

    def since(self, after: int = 0, limit: int = KEEP_LINES) -> List[Dict[str, Any]]:
        out = [line for line in self.lines if line["id"] > after]
        return out[-limit:]


class LogBuffer(logging.Handler):
    """Last lines of the bridge log ("Logs" page, app log)."""

    def __init__(self, keep: int = KEEP_LOG):
        super().__init__(level=logging.DEBUG)
        self.records: Deque[Dict[str, Any]] = collections.deque(maxlen=keep)
        self._ids = itertools.count(1)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
            if record.exc_info:
                msg += "\n" + logging.Formatter().formatException(record.exc_info)
            self.records.append({"id": next(self._ids), "time": round(record.created, 3),
                                 "level": record.levelname, "name": record.name, "text": msg})
        except Exception:  # noqa: BLE001
            self.handleError(record)

    def since(self, after: int = 0, level: str = "DEBUG", limit: int = KEEP_LOG) -> List[Dict[str, Any]]:
        minimum = logging.getLevelName(level.upper()) if isinstance(logging.getLevelName(level.upper()), int) else 0
        out = [r for r in self.records if r["id"] > after and logging.getLevelName(r["level"]) >= minimum]
        return out[-limit:]

    def text(self) -> str:
        return "\n".join(f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r['time']))} {r['level']:<7} "
                         f"{r['name']:<10} {r['text']}" for r in self.records) + "\n"


LOG_BUFFER = LogBuffer()
