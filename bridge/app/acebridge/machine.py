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
import json
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from . import __version__
from .filament_z import FIELD as Z_FIELD
from .filament_z import LIMIT as Z_LIMIT
from .filament_z import filament_z

if TYPE_CHECKING:
    from .moonraker import Moonraker
    from .slots import SlotManager
    from .spoolman import Spoolman

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
Z_STEPS = (0.01, 0.025, 0.05)          # mm je Tipp beim Feinjustieren (auch im Druck)
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
    def __init__(self, moon: "Moonraker", sm: Optional["Spoolman"] = None, slots: Optional["SlotManager"] = None):
        self.moon, self.sm, self.slots = moon, sm, slots
        self.running: Optional[str] = None      # laufende lange Aktion
        self.error: Optional[str] = None        # Fehler der letzten Aktion (Anzeige in der Steuerung)
        self.z_session = 0.0                    # Summe der Feinjustierung im laufenden Druck (zum Uebernehmen)
        self._was_printing = False

    def _track_job(self) -> None:
        """Neuer Druck -> Feinjustier-Summe auf 0 (sie gehoert zum Druck, in dem sie gemacht wurde)."""
        printing = self._state() in ("printing", "paused")
        if printing and not self._was_printing:
            self.z_session = 0.0
        self._was_printing = printing

    def _active_filament(self) -> Dict[str, Any]:
        """Filament der gerade geladenen Spule (ACEPRO current_index -> Slot) oder {}."""
        if self.slots is None:
            return {}
        idx = (self.moon.status.get("ace") or {}).get("current_index")
        if not isinstance(idx, int) or idx < 0:
            return {}
        assigned, _ = self.slots.assignments()
        return ((assigned.get(idx + 1) or {}).get("filament") or {})

    def _state(self) -> Optional[str]:
        return (self.moon.status.get("print_stats") or {}).get("state")

    async def view(self) -> Dict[str, Any]:
        """Stand fuer die Steuerung: Position, gehomte Achsen, was gerade erlaubt ist."""
        self._track_job()
        th: Dict[str, Any] = {}
        q: Dict[str, Any] = {}
        if self.moon.klippy_ready:
            try:
                q = await self.moon.query({"toolhead": ["position", "homed_axes"], "gcode_move": ["homing_origin"],
                                           "exclude_object": ["objects", "excluded_objects", "current_object"]})
                th = q.get("toolhead") or {}
            except Exception:  # noqa: BLE001 - Anzeige ohne Position ist besser als gar keine
                th, q = {}, {}
        origin = (q.get("gcode_move") or {}).get("homing_origin") or []
        ex = q.get("exclude_object") or {}
        excluded = set(ex.get("excluded_objects") or [])
        fil = self._active_filament()
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
            "z_offset": round(origin[2], 3) if len(origin) >= 3 else None, "z_steps": list(Z_STEPS),
            "z_session": round(self.z_session, 3),
            "z_filament": ({"id": fil.get("id"), "name": fil.get("name"),
                            "value": round(filament_z(fil, self.sm.templates()), 3)} if fil.get("id") and self.sm else None),
            "objects": [{"name": o.get("name"), "excluded": o.get("name") in excluded,
                         "current": o.get("name") == ex.get("current_object")}
                        for o in ex.get("objects") or [] if o.get("name")],
        }

    def build(self, action: str, body: Dict[str, Any], homed: str = "xyz") -> List[str]:
        """G-Code fuer eine Aktion - nur aus festen Bausteinen; wirft MachineError bei allem anderen."""
        state = self._state()
        if not self.moon.klippy_ready:
            raise MachineError(503, "Klipper ist nicht bereit")
        if action == "zadjust":
            d = body.get("delta")
            if not isinstance(d, (int, float)) or isinstance(d, bool) or abs(d) not in Z_STEPS:
                raise MachineError(400, "delta: ±" + ", ±".join(f"{v:g}" for v in Z_STEPS))
            return [f"SET_GCODE_OFFSET Z_ADJUST={d:+.3f} MOVE=1"]
        if action == "exclude":
            name = body.get("name")
            if state not in ("printing", "paused"):
                raise MachineError(409, "Es läuft kein Druck")
            if not isinstance(name, str) or not name or any(c in name for c in " \n\r;\"'"):
                raise MachineError(400, "name: Objektname")
            if body.get("confirm") is not True:
                raise MachineError(409, f"{name} überspringen? Der Rest wird weitergedruckt.", confirm="exclude")
            return [f"EXCLUDE_OBJECT NAME={name}"]
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

    async def save_z(self) -> Dict[str, Any]:
        """Feinjustierung dieses Drucks zum Z-Versatz des geladenen Filaments in Spoolman addieren."""
        self._track_job()
        if self.sm is None:
            raise MachineError(503, "Spoolman nicht verbunden")
        if abs(self.z_session) < 0.0005:
            raise MachineError(409, "Nichts nachgestellt")
        fil = self._active_filament()
        if not fil.get("id"):
            raise MachineError(409, "Kein Filament geladen (oder keine Spule zugeordnet)")
        old = filament_z(fil, self.sm.templates())
        new = round(max(-Z_LIMIT, min(Z_LIMIT, old + self.z_session)), 3)
        await self.sm.patch_filament(fil["id"], {"extra": {Z_FIELD: json.dumps(new)}})
        self.z_session = 0.0
        return {"ok": True, "filament": fil.get("name"), "old": round(old, 3), "new": new}

    async def system(self) -> Dict[str, Any]:
        """Infos fuers Display: Versionen, Netzwerk des Pi, Klipper-Zustand."""
        info: Dict[str, Any] = {"bridge": __version__}
        try:
            si = (await self.moon.get_json("/machine/system_info") or {}).get("system_info") or {}
            net = si.get("network") or {}
            info["ips"] = sorted({a.get("address") for n in net.values() for a in (n.get("ip_addresses") or [])
                                  if a.get("family") == "ipv4" and not a.get("is_link_local")} - {None})
            info["host"] = ((si.get("cpu_info") or {}).get("model") or "").strip() or None
            info["os"] = (si.get("distribution") or {}).get("name")
        except Exception:  # noqa: BLE001
            pass
        try:
            pi = await self.moon.get_json("/printer/info") or {}
            info["klipper"] = pi.get("software_version")
            info["klippy_state"] = pi.get("state")
            info["klippy_message"] = (pi.get("state_message") or "").strip() or None
        except Exception:  # noqa: BLE001
            info["klippy_state"] = "offline"
        return info

    async def power(self, what: str, confirm: bool, source: str) -> Dict[str, Any]:
        """Pi herunterfahren oder neu starten (Moonraker machine.shutdown/reboot) - nie im Druck, nur mit Rueckfrage."""
        if what not in ("shutdown", "reboot"):
            raise MachineError(404, "Unbekannt")
        if self._state() in ("printing", "paused"):
            raise MachineError(409, "Während eines Drucks nicht")
        if not confirm:
            raise MachineError(409, "Wirklich?", confirm=what)
        if self.moon.console is not None:
            self.moon.console.add("command", f"Pi {'herunterfahren' if what == 'shutdown' else 'neu starten'}", source)
        await self.moon.post_json(f"/machine/{what}", {})
        return {"ok": True}

    async def run(self, action: str, body: Dict[str, Any], source: str) -> Dict[str, Any]:
        self._track_job()
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
                if action == "zadjust":
                    self.z_session = round(self.z_session + float(body["delta"]), 3)
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
