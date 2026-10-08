"""Konsole: was der Drucker antwortet, welche Befehle gesendet wurden (von wem) - und ein Bridge-Log.

- Antworten des Druckers kommen als notify_gcode_response ueber die eine WebSocket-Verbindung der
  Bridge (kein zusaetzlicher Client, kein Abfragen). Beim Verbinden einmal server.gcode_store als Vorlauf.
- Befehle, die ueber die Bridge gehen (Weboberflaeche, Trockner, ACE, Slots), stehen mit Quelle drin.
  Befehle anderer Clients (Mainsail) zeigt Moonraker nur ueber ihre Antworten.
- Riskante Befehle brauchen eine Bestaetigung (check_command), Bewegungen auch waehrend eines Drucks.
- LogBuffer haelt die letzten Zeilen des Bridge-Logs fuer die Seite "Logs" und die App.
"""

from __future__ import annotations

import collections
import itertools
import logging
import re
import time
from typing import Any, Deque, Dict, List, Optional

KEEP_LINES = 500
KEEP_LOG = 2000
MAX_HOTEND = 260          # darueber: Rueckfrage

# Befehl (erstes Wort) -> Grund der Rueckfrage
RISKY = {
    "M112": "Not-Aus: alles stoppt sofort, danach Klipper neu laden (FIRMWARE_RESTART)",
    "EMERGENCY_STOP": "Not-Aus: alles stoppt sofort, danach Klipper neu laden (FIRMWARE_RESTART)",
    "FIRMWARE_RESTART": "Lädt Klipper neu – ein laufender Druck bricht ab",
    "RESTART": "Lädt Klipper neu – ein laufender Druck bricht ab",
    "SAVE_CONFIG": "Schreibt die Drucker-Konfiguration und startet neu",
    "CANCEL_PRINT": "Bricht den laufenden Druck ab",
    "SDCARD_RESET_FILE": "Setzt die laufende Druckdatei zurück",
    "PID_CALIBRATE": "Heizt stark auf (Kalibrierung)",
    "SET_KINEMATIC_POSITION": "Setzt die Position ohne Referenzfahrt – kann crashen",
    "FORCE_MOVE": "Bewegt einen Motor ohne Grenzen – kann crashen",
}
MOVES = re.compile(r"^(G0|G1|G2|G3|G28|G29|G92|M84|M18|BED_MESH_CALIBRATE|KOBRA_BED_MESH_ALL|G9111|PROBE\w*|"
                   r"MOVE_TO_\w+|WIPE_\w+|SHAPER_CALIBRATE|TEST_RESONANCES|T\d+|ACE_CHANGE_TOOL|CUT_TIP)$")
TEMP_CMD = re.compile(r"^(M104|M109)$")
TEMP_ARG = re.compile(r"\bS(\d+(?:\.\d+)?)", re.I)
SET_HEATER = re.compile(r"HEATER=extruder\b.*\bTARGET=(\d+(?:\.\d+)?)", re.I)


def check_command(script: str, printing: bool) -> Optional[str]:
    """Grund fuer eine Rueckfrage oder None. Prueft jede Zeile des Skripts."""
    for raw in script.splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        word = line.split()[0].upper()
        if word in RISKY:
            return f"{word}: {RISKY[word]}"
        temp = None
        if TEMP_CMD.match(word):
            m = TEMP_ARG.search(line)
            temp = float(m.group(1)) if m else None
        elif word == "SET_HEATER_TEMPERATURE":
            m = SET_HEATER.search(line)
            temp = float(m.group(1)) if m else None
        if temp is not None and temp > MAX_HOTEND:
            return f"{word}: Düse auf {temp:g} °C (mehr als {MAX_HOTEND} °C)"
        if printing and MOVES.match(word):
            return f"{word}: Bewegung während eines Drucks"
    return None


class Console:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.lines: Deque[Dict[str, Any]] = collections.deque(maxlen=KEEP_LINES)
        self._ids = itertools.count(1)
        self.commands: Dict[str, str] = {}      # aus printer/gcode/help, fuer die Vervollstaendigung

    def add(self, kind: str, text: str, source: Optional[str] = None, at: Optional[float] = None) -> None:
        """kind: command | response | error"""
        text = (text or "").rstrip()
        if not text:
            return
        self.lines.append({"id": next(self._ids), "time": round(at if at is not None else self.clock(), 3),
                           "kind": kind, "text": text, "source": source})

    def seed(self, store: List[Dict[str, Any]]) -> None:
        """Vorlauf aus server.gcode_store - nur, wenn noch nichts da ist (nach Reconnect nicht doppelt)."""
        if self.lines:
            return
        for e in store or []:
            kind = "command" if e.get("type") == "command" else "response"
            self.add(kind, e.get("message") or "", "Verlauf" if kind == "command" else None, e.get("time"))

    def since(self, after: int = 0, limit: int = KEEP_LINES) -> List[Dict[str, Any]]:
        out = [line for line in self.lines if line["id"] > after]
        return out[-limit:]


class LogBuffer(logging.Handler):
    """Letzte Zeilen des Bridge-Logs (Seite "Logs", App-Protokoll)."""

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
