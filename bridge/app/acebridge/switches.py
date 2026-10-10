"""Schalter der Klipper-Module an einer Stelle: Stand aus dem Moonraker-Abo, Schalten ueber eine feste Liste.

Die Module am Drucker (kobra-klipper: kobra_pa, kobra_resume, kobra_clog, kobra_io, KOBRA_FILAMENT_Z, ACEPRO) speichern
ihre Schalter selbst - Web, App, Display, KlipperScreen und Mainsail sehen denselben Stand. Diese Bridge-Seite liest nur
das Abo und schickt bei POST /api/switch genau den G-Code-Befehl aus der Liste unten (nichts Freies).
Fehlt ein Modul, fehlt sein Schalter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from .moonraker import Moonraker

SUBSCRIBE = {
    "kobra_io": ["sound", "light_auto", "events", "light", "available", "error"],
    "save_variables": ["variables"],
    "gcode_macro KOBRA_START": ["use_filament_z"],
    "kobra_debug": ["enabled"],
}

GROUPS = [("print", "Drucken"), ("watch", "Überwachung"), ("io", "Licht & Töne")]
CLOG_ACTIONS = [("warn", "Nur warnen"), ("pause", "Pausieren")]
ENDLESS_MODES = [("exact", "Gleiche Farbe"), ("material", "Gleiches Material"), ("next", "Nächste Spule")]
SOUND_EVENTS = [("done", "Ton: Druck fertig"), ("error", "Ton: Pause, Fehler, Abbruch"), ("clog", "Ton: Verstopfung"),
                ("change", "Ton: Farbwechsel hängt"), ("prompt", "Ton: Frage nach Stromausfall")]

St = Dict[str, Any]


class SwitchError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


def _filament_z(st: St) -> Optional[bool]:
    sv = (st.get("save_variables") or {}).get("variables") or {}
    if "kobra_use_filament_z" in sv:
        return bool(sv["kobra_use_filament_z"])
    macro = st.get("gcode_macro KOBRA_START")
    return None if not macro or macro.get("use_filament_z") is None else bool(macro["use_filament_z"])


def _bool_cmd(fmt: str) -> Callable[[Any], str]:
    def cmd(v: Any) -> str:
        if not isinstance(v, bool):
            raise SwitchError(400, "Wert: true oder false")
        return fmt % int(v)
    return cmd


def _endless(v: Any) -> str:
    if not isinstance(v, bool):
        raise SwitchError(400, "Wert: true oder false")
    return "ACE_ENABLE_ENDLESS_SPOOL" if v else "ACE_DISABLE_ENDLESS_SPOOL"


def _choice_cmd(fmt: str, options: List[Tuple[str, str]]) -> Callable[[Any], str]:
    def cmd(v: Any) -> str:
        if v not in [o for o, _ in options]:
            raise SwitchError(400, "Wert: " + ", ".join(o for o, _ in options))
        return fmt % v
    return cmd


def items(st: St) -> List[Dict[str, Any]]:
    """Alle vorhandenen Schalter und Auswahlen mit Stand. Jeder Eintrag: key, group, kind (switch|choice), title,
    hint, on bzw. current/options, sensitive. Die Befehle stehen in _commands (nicht im Ergebnis)."""
    out: List[Dict[str, Any]] = []

    def sw(key, group, title, hint, on, sensitive=True):
        out.append({"key": key, "group": group, "kind": "switch", "title": title, "hint": hint, "on": bool(on),
                    "sensitive": bool(sensitive)})

    def ch(key, group, title, options, current, sensitive=True):
        out.append({"key": key, "group": group, "kind": "choice", "title": title,
                    "options": [{"value": v, "label": lbl} for v, lbl in options], "current": current,
                    "sensitive": bool(sensitive)})

    pa = st.get("kobra_pa")
    if pa:
        sw("pa", "print", "Auto-PA", "PA je Geschwindigkeit aus Spoolman; aus = PA aus Orca", pa.get("enabled"))
        sw("pa_auto", "print", "PA automatisch messen", "Fehlt es, misst der Drucker (~2 min)", pa.get("auto"),
           pa.get("enabled"))
    fz = _filament_z(st)
    if fz is not None:
        sw("filament_z", "print", "Z-Versatz pro Filament", "Feld Z-Versatz aus Spoolman für die erste Schicht", fz)
    ace = st.get("ace")
    if ace and "endless_spool_enabled" in ace:
        sw("endless", "print", "Endlosspule", "Leere Spule → passende andere laden", ace.get("endless_spool_enabled"))
        if ace.get("endless_spool_enabled"):
            ch("endless_mode", "print", "Welche Spule passt?", ENDLESS_MODES,
               ace.get("endless_spool_match_mode") or "exact")
    rs = st.get("kobra_resume")
    if rs:
        sw("powerloss", "watch", "Fortsetzen nach Stromausfall", "Sichert im Druck die Stelle, fragt nach dem Einschalten",
           rs.get("enabled"))
    cl = st.get("kobra_clog")
    if cl:
        sw("clog", "watch", "Verstopfung erkennen",
           "Extruder gegen Encoder am Filament-Eingang" if cl.get("available", True) else "Kein Encoder gefunden",
           cl.get("enabled"))
        if cl.get("enabled"):
            ch("clog_action", "watch", "Bei Verdacht", CLOG_ACTIONS, cl.get("action") or "warn")
    dbg = st.get("kobra_debug")
    if dbg:
        sw("debug", "watch", "Diagnose-Protokoll", "Ausführliches Klipper-Log unserer Module (Entwicklung)",
           dbg.get("enabled"))
    io = st.get("kobra_io")
    if io:
        ok = bool(io.get("available"))
        sw("light", "io", "Licht", "Licht im Drucker" if ok else "kobra-io ohne Schlüssel", io.get("light"), ok)
        sw("light_auto", "io", "Licht automatisch", "An beim Druckstart, danach aus", io.get("light_auto"), ok)
        sw("sound", "io", "Töne", "Piepser bei Ereignissen (nachts nur Alarme)", io.get("sound"), ok)
        events = io.get("events") or {}
        for ev, title in SOUND_EVENTS:
            if ev in events:
                sw("sound_" + ev, "io", title, "", events[ev], ok and bool(io.get("sound")))
    return out


def _commands(key: str) -> Optional[Callable[[Any], str]]:
    fixed = {
        "pa": _bool_cmd("KOBRA_PA ENABLE=%d"),
        "pa_auto": _bool_cmd("KOBRA_PA AUTO=%d"),
        "filament_z": _bool_cmd("KOBRA_FILAMENT_Z ENABLE=%d"),
        "endless": _endless,
        "endless_mode": _choice_cmd("ACE_SET_ENDLESS_SPOOL_MODE MODE=%s", ENDLESS_MODES),
        "powerloss": _bool_cmd("KOBRA_POWERLOSS ENABLE=%d"),
        "clog": _bool_cmd("KOBRA_CLOG ENABLE=%d"),
        "clog_action": _choice_cmd("KOBRA_CLOG ACTION=%s", CLOG_ACTIONS),
        "light": _bool_cmd("KOBRA_IO LIGHT=%d"),
        "light_auto": _bool_cmd("KOBRA_IO LIGHT_AUTO=%d"),
        "sound": _bool_cmd("KOBRA_IO SOUND=%d"),
        "debug": _bool_cmd("KOBRA_DEBUG ENABLE=%d"),
    }
    for ev, _ in SOUND_EVENTS:
        fixed["sound_" + ev] = _bool_cmd("KOBRA_IO EVENT=" + ev + " ON=%d")
    return fixed.get(key)


class Switches:
    def __init__(self, moon: "Moonraker"):
        self.moon = moon

    def view(self) -> Dict[str, Any]:
        st = self.moon.status if self.moon.klippy_ready else {}
        return {"groups": [{"key": k, "title": t} for k, t in GROUPS], "items": items(st)}

    async def set(self, key: str, value: Any) -> Dict[str, Any]:
        if not self.moon.klippy_ready:
            raise SwitchError(503, "Klipper ist nicht bereit")
        cur = {i["key"]: i for i in items(self.moon.status)}
        cmd = _commands(key)
        if cmd is None or key not in cur:
            raise SwitchError(404, f"Schalter {key} gibt es nicht (Modul fehlt?)")
        if not cur[key]["sensitive"]:
            raise SwitchError(409, f"{cur[key]['title']} ist gerade gesperrt")
        script = cmd(value)
        await self.moon.gcode(script, source="Schalter")
        return {"ok": True, "key": key, "sent": script}
