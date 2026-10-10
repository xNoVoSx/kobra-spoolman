"""Steuerung am Drucker (Display, spaeter Web/App): homen, joggen, Motoren aus, extrudieren, Slot laden/entladen,
ausgewaehlte Makros. Temperaturen und Luefter laufen ueber /api/print/tune, Not-Aus und Klipper neu laden ueber
/api/print/{action} - dort gibt es schon Grenzen und Rueckfragen.

Grundsatz wie bei den Schaltern: kein freier G-Code. Jede Aktion baut ihren Befehl aus festen Bausteinen mit Grenzen
(Schrittweiten, Achsen, Slots, Makro-Liste). Bewegen und Laden sind gesperrt, solange gedruckt wird; Extrudieren geht
auch in der Pause (zum Freispuelen), Klipper verweigert es selbst bei kalter Duese.
Position und Homing-Stand werden nur abgefragt, wenn jemand die Steuerung offen hat (kein Dauer-Abo).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from .moonraker import Moonraker

STEPS = (0.1, 1.0, 10.0, 50.0)          # mm je Tipp
Z_MAX_STEP = 10.0                       # Z nie mehr als 10 mm auf einmal
FEED = {"x": 6000, "y": 6000, "z": 600}  # mm/min
EXTRUDE = (5.0, 10.0, 50.0)             # mm je Tipp
EXTRUDE_FEED = 300                      # mm/min (5 mm/s)
MIN_EXTRUDE_TEMP = 170.0                # wie Klippers min_extrude_temp - hier nur fuer eine klare Meldung
SLOTS = 4
HOME = {"all": "G28", "xy": "G28 X Y", "z": "G28 Z"}
# Makro-Knoepfe (feste Auswahl, Novos 10.10.): Schluessel -> (Beschriftung, Befehl, Rueckfrage oder None)
MACROS: Dict[str, tuple] = {
    "bed_mesh_all": ("Bettnetze messen", "KOBRA_BED_MESH_ALL",
                     "Misst die Bettnetze für alle Temperaturen (heizt jeweils, dauert lange). Bett frei?"),
}
LONG = ("home", "load", "unload", "macro")   # dauern Minuten: im Hintergrund, Antwort sofort
BUSY = ("printing",)                    # Bewegen, Laden, Makros gesperrt
EXTRUDE_BUSY = ("printing",)            # Extrudieren: in der Pause erlaubt


class MachineError(Exception):
    def __init__(self, status: int, msg: str, confirm: Optional[str] = None):
        super().__init__(msg)
        self.status = status
        self.confirm = confirm


log = logging.getLogger("machine")


class Machine:
    def __init__(self, moon: "Moonraker"):
        self.moon = moon
        self.running: Optional[str] = None      # laufende lange Aktion
        self.error: Optional[str] = None        # Fehler der letzten Aktion (Anzeige in der Steuerung)

    def _state(self) -> Optional[str]:
        return (self.moon.status.get("print_stats") or {}).get("state")

    async def view(self) -> Dict[str, Any]:
        """Stand fuer die Steuerung: Position, gehomte Achsen, was gerade erlaubt ist."""
        th: Dict[str, Any] = {}
        if self.moon.klippy_ready:
            try:
                th = (await self.moon.query({"toolhead": ["position", "homed_axes"]})).get("toolhead") or {}
            except Exception:  # noqa: BLE001 - Anzeige ohne Position ist besser als gar keine
                th = {}
        pos = th.get("position") or []
        state = self._state()
        return {
            "ready": bool(self.moon.klippy_ready),
            "position": [round(v, 2) for v in pos[:3]] if len(pos) >= 3 else None,
            "homed": th.get("homed_axes") or "",
            "move_allowed": bool(self.moon.klippy_ready) and state not in BUSY,
            "extrude_allowed": bool(self.moon.klippy_ready) and state not in EXTRUDE_BUSY,
            "steps": list(STEPS), "extrude_steps": list(EXTRUDE), "slots": SLOTS,
            "macros": [{"key": k, "label": v[0], "confirm": v[2]} for k, v in MACROS.items()],
            "running": self.running, "error": self.error,
        }

    def build(self, action: str, body: Dict[str, Any], homed: str = "xyz") -> List[str]:
        """G-Code fuer eine Aktion - nur aus festen Bausteinen; wirft MachineError bei allem anderen."""
        state = self._state()
        if not self.moon.klippy_ready:
            raise MachineError(503, "Klipper ist nicht bereit")
        if action == "extrude":
            if state in EXTRUDE_BUSY:
                raise MachineError(409, "Während des Drucks nicht – erst pausieren")
            mm = body.get("mm")
            if not isinstance(mm, (int, float)) or isinstance(mm, bool) or abs(mm) not in EXTRUDE:
                raise MachineError(400, "mm: ±" + ", ±".join(f"{v:g}" for v in EXTRUDE))
            temp = (self.moon.status.get("extruder") or {}).get("temperature")
            if temp is not None and temp < MIN_EXTRUDE_TEMP:
                raise MachineError(409, f"Düse zu kalt ({round(temp)} °C) – erst auf Drucktemperatur heizen")
            return ["M83", f"G1 E{mm:g} F{EXTRUDE_FEED}"]
        if state in BUSY:
            raise MachineError(409, "Während des Drucks gesperrt")
        if action == "home":
            axes = body.get("axes", "all")
            if axes not in HOME:
                raise MachineError(400, "axes: all, xy oder z")
            return [HOME[axes]]
        if action == "jog":
            axis, dist = str(body.get("axis", "")).lower(), body.get("dist")
            if axis not in FEED:
                raise MachineError(400, "axis: x, y oder z")
            if not isinstance(dist, (int, float)) or isinstance(dist, bool) or abs(dist) not in STEPS:
                raise MachineError(400, "dist: ±" + ", ±".join(f"{v:g}" for v in STEPS))
            if axis == "z" and abs(dist) > Z_MAX_STEP:
                raise MachineError(400, f"Z höchstens {Z_MAX_STEP:g} mm auf einmal")
            if axis not in homed:
                raise MachineError(409, f"{axis.upper()} ist nicht gehomt – erst homen")
            return ["G91", f"G1 {axis.upper()}{dist:g} F{FEED[axis]}", "G90"]
        if action == "motors_off":
            return ["M84"]
        if action == "load":
            slot = body.get("slot")
            if not isinstance(slot, int) or isinstance(slot, bool) or not 1 <= slot <= SLOTS:
                raise MachineError(400, f"slot: 1 bis {SLOTS}")
            return [f"T{slot - 1}"]
        if action == "unload":
            return ["ACE_SMART_UNLOAD"]
        if action == "macro":
            key = body.get("key")
            if key not in MACROS:
                raise MachineError(404, "Unbekanntes Makro")
            label, cmd, confirm = MACROS[key]
            if confirm and body.get("confirm") is not True:
                raise MachineError(409, confirm, confirm=confirm)
            return [cmd]
        raise MachineError(404, "Unbekannte Aktion")

    async def run(self, action: str, body: Dict[str, Any], source: str) -> Dict[str, Any]:
        homed = "xyz"
        if action == "jog":
            homed = (await self.view())["homed"]
        if self.running and action in LONG:
            raise MachineError(409, f"Läuft noch: {self.running}")
        cmds = self.build(action, body, homed)
        self.error = None
        if action not in LONG:
            try:
                await self.moon.gcode("\n".join(cmds), timeout=30, source=source)
            except Exception as e:  # noqa: BLE001
                self.error = str(e)
                raise MachineError(400 if isinstance(e, RuntimeError) else 503, str(e) or "Befehl fehlgeschlagen") from e
            return {"ok": True, "sent": cmds}
        self.running = cmds[0]

        async def bg():
            try:
                await self.moon.gcode("\n".join(cmds), timeout=4 * 3600, source=source)
            except Exception as e:  # noqa: BLE001
                self.error = str(e) or "Befehl fehlgeschlagen"
                log.warning("Steuerung %s: %s", cmds[0], e)
            finally:
                self.running = None
        asyncio.get_running_loop().create_task(bg())
        return {"ok": True, "sent": cmds, "started": True}
