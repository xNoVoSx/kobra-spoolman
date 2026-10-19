"""Switches of the Klipper modules in one place: state from the Moonraker subscription, switching through a fixed list.

The modules on the printer (kobra-klipper: kobra_pa, kobra_resume, kobra_clog, kobra_io, KOBRA_FILAMENT_Z, ACEPRO) store
their switches themselves - web, app, display, KlipperScreen and Mainsail see the same state. This bridge side only
reads the subscription and, for POST /api/switch, sends exactly the G-code command from the list below (nothing free).
If a module is missing, its switch is missing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from .i18n import msg_of, tr

if TYPE_CHECKING:
    from .moonraker import Moonraker
    from .usb import UsbTunnel

SUBSCRIBE = {
    "kobra_io": ["sound", "light_auto", "events", "light", "available", "error"],
    "save_variables": ["variables"],
    "gcode_macro KOBRA_START": ["use_filament_z"],
    "kobra_debug": ["enabled"],
}

GROUPS = [("print", tr("Printing")), ("watch", tr("Monitoring")), ("io", tr("Light & sounds")), ("system", tr("System"))]
CLOG_ACTIONS = [("log", tr("Log only")), ("warn", tr("Warn only")), ("pause", tr("Pause"))]
ENDLESS_MODES = [("exact", tr("Same colour")), ("material", tr("Same material")), ("next", tr("Next spool"))]
SOUND_EVENTS = [("done", tr("Sound: print finished")), ("error", tr("Sound: pause, error, cancel")),
                ("clog", tr("Sound: clog")), ("change", tr("Sound: colour change stuck")),
                ("prompt", tr("Sound: question after a power loss"))]

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
            raise SwitchError(400, tr("Value: true or false"))
        return fmt % int(v)
    return cmd


def _endless(v: Any) -> str:
    if not isinstance(v, bool):
        raise SwitchError(400, tr("Value: true or false"))
    return "ACE_ENABLE_ENDLESS_SPOOL" if v else "ACE_DISABLE_ENDLESS_SPOOL"


def _choice_cmd(fmt: str, options: List[Tuple[str, str]]) -> Callable[[Any], str]:
    def cmd(v: Any) -> str:
        if v not in [o for o, _ in options]:
            raise SwitchError(400, tr("Value: {options}", options=", ".join(o for o, _ in options)))
        return fmt % v
    return cmd


def items(st: St) -> List[Dict[str, Any]]:
    """All existing switches and choices with their state. Each entry: key, group, kind (switch|choice), title, hint,
    on or current/options, sensitive. The commands are in _commands (not in the result)."""
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
        sw("pa", "print", tr("Auto PA"), tr("PA per speed from Spoolman; off = PA from Orca"), pa.get("enabled"))
        sw("pa_auto", "print", tr("Measure PA automatically"), tr("If missing, the printer measures (~5 min)"), pa.get("auto"),
           pa.get("enabled"))
    kn = st.get("kobra_nozzle")
    if kn:
        sw("hotends", "print", tr("Swappable hotends"), tr("PID, nozzle and Z correction of the hotend in use"),
           kn.get("enabled"))
        sw("nozzle_check", "print", tr("Check the nozzle at print start"),
           tr("Stop a print sliced for another nozzle"), kn.get("check"), kn.get("enabled"))
    fz = _filament_z(st)
    if fz is not None:
        sw("filament_z", "print", tr("Z offset per filament"), tr("Field Z offset from Spoolman for the first layer"), fz)
    ace = st.get("ace")
    if ace and "endless_spool_enabled" in ace:
        sw("endless", "print", tr("Endless spool"), tr("Empty spool → load a matching other one"),
           ace.get("endless_spool_enabled"))
        if ace.get("endless_spool_enabled"):
            ch("endless_mode", "print", tr("Which spool matches?"), ENDLESS_MODES,
               ace.get("endless_spool_match_mode") or "exact")
    rs = st.get("kobra_resume")
    if rs:
        sw("powerloss", "watch", tr("Resume after power loss"),
           tr("Saves the position while printing, asks after switching on"), rs.get("enabled"))
    cl = st.get("kobra_clog")
    if cl:
        sw("clog", "watch", tr("Detect clogs"),
           tr("Extruder against the encoder at the filament inlet") if cl.get("available", True)
           else tr("No encoder found"),
           cl.get("enabled"))
        if cl.get("enabled"):
            ch("clog_action", "watch", tr("On suspicion"), CLOG_ACTIONS, cl.get("action") or "warn")
    dbg = st.get("kobra_debug")
    if dbg:
        sw("debug", "system", tr("Diagnostic log"), tr("Detailed Klipper log of our modules (development)"),
           dbg.get("enabled"))
    io = st.get("kobra_io")
    if io:
        ok = bool(io.get("available"))
        sw("light", "io", tr("Light"), tr("Light in the printer") if ok else tr("kobra-io without a key"), io.get("light"), ok)
        sw("light_auto", "io", tr("Light automatic"), tr("On at print start, off afterwards"), io.get("light_auto"), ok)
        sw("sound", "io", tr("Sounds"), tr("Beeper on events (alarms only at night)"), io.get("sound"), ok)
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
        "hotends": _bool_cmd("KOBRA_NOZZLE ENABLE=%d"),
        "nozzle_check": _bool_cmd("KOBRA_NOZZLE CHECK_PRINT=%d"),
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
    def __init__(self, moon: "Moonraker", usb: Optional["UsbTunnel"] = None):
        self.moon = moon
        self.usb = usb              # switches of the USB watchdog on the Klipper computer (Moonraker database, not Klipper)

    def view(self) -> Dict[str, Any]:
        st = self.moon.status if self.moon.klippy_ready else {}
        all_items = items(st) + (self.usb.items() if self.usb is not None else [])
        used = {i["group"] for i in all_items}
        # leave out groups without switches (e.g. "System" without debug module and USB watchdog) - display: no empty tab
        groups = [{"key": k, "title": t} for k, t in GROUPS if k in used or k in ("print", "watch")]
        return {"groups": groups, "items": all_items}

    async def set(self, key: str, value: Any) -> Dict[str, Any]:
        if key.startswith("usb_") and self.usb is not None:
            from .usb import UsbError
            try:
                return await self.usb.set(key, value)
            except UsbError as e:
                raise SwitchError(e.status, msg_of(e)) from e
        if not self.moon.klippy_ready:
            raise SwitchError(503, tr("Klipper is not ready"))
        cur = {i["key"]: i for i in items(self.moon.status)}
        cmd = _commands(key)
        if cmd is None or key not in cur:
            raise SwitchError(404, tr("There is no switch {key} (module missing?)", key=key))
        if not cur[key]["sensitive"]:
            raise SwitchError(409, tr("{title} is locked right now", title=cur[key]["title"]))
        script = cmd(value)
        await self.moon.gcode(script, source=tr("Switches"))
        return {"ok": True, "key": key, "sent": script}
