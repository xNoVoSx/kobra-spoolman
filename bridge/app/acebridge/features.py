"""Every feature of the system in one list: what it does, what it needs, whether it is on, where its switch lives.

The switches themselves stay where they are - this module only gathers them, so web, app and display can show one
page ("Features") and switch any feature in one place:

- setting:  a runtime setting of the bridge (runtime_settings.py, DATA_DIR/settings.json)
- printer:  a switch of a Klipper module on the printer (switches.py) - present only when the module is installed
- install:  set by the installation (environment variables of the container / HA add-on options) - shown, never changed
            here: what the installation sets wins (the HA add-on keeps control over its options)
- client:   a client that is used once it is paired (app, display, Orca plugin) - set up there, shown here
- core:     always on

A setting whose environment variable is set explicitly counts as set by the installation as well and is not switched
from this page (the settings page still can, as before).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from .i18n import current_lang, tr

if TYPE_CHECKING:
    from .__main__ import Bridge

DOCS = "https://github.com/xNoVoSx/kobra-spoolman/blob/main/docs/"
GROUPS = [("core", tr("Core")), ("control", tr("Operation")), ("comfort", tr("Comfort")),
          ("integration", tr("Integrations")), ("printer", tr("Printer modules"))]


@dataclass(frozen=True)
class Feature:
    key: str
    group: str
    title: str
    text: str
    source: str                       # core | setting | printer | install | client
    keys: Tuple[str, ...] = ()        # setting keys / printer switch keys / config attribute / device kind
    needs: str = ""                   # what it needs, for the user
    klipper_only: bool = False


FEATURES: List[Feature] = [
    Feature("spools", "core", tr("Spools and slots"),
            tr("Assign spools to the ACE slots, book the consumption per spool, RFID tags, data for Orca's sync"),
            "core", needs=tr("Spoolman and the printer (Moonraker)")),
    Feature("web", "core", tr("Web UI"), tr("Overview, spools, filaments, slots, settings, logs, bug reports"), "core"),
    Feature("app", "control", tr("Android app"),
            tr("Writes the RFID tags and brings the printer's messages to the phone – without extra load on the printer"),
            "client", ("app",), tr("Android with NFC, paired with the bridge")),
    Feature("display", "control", tr("Printer display"),
            tr("The web UI made for the printer's touch screen: print, slots, dryer, control"),
            "client", ("display",), tr("Klipper setup: kiosk on the Klipper computer"), klipper_only=True),
    Feature("orca", "control", tr("Orca plugin"),
            tr("Spoolman profiles in Orca, usage preview after slicing, back sync of changed profiles"),
            "client", ("plugin",), tr("OrcaSlicer on the PC (orca-kobra build for the preview)")),
    Feature("camera", "core", tr("Camera"),
            tr("Printer camera through the bridge: one connection to the printer, any number of viewers"),
            "setting", ("camera",), tr("A camera at the printer")),
    Feature("preview", "core", tr("Print preview"),
            tr("Loads the print file: 3D model, remaining amount per spool, layer progress"), "setting", ("render",)),
    Feature("dryer_auto", "comfort", tr("Drying automatically"), tr("Damp spools are dried when they are inserted"),
            "setting", ("auto_dry_on_insert",), tr("ACE with dryer")),
    Feature("recording", "comfort", tr("Print recordings"),
            tr("Raw data of every print for checking the bookings later"), "setting", ("telemetry",)),
    Feature("mqtt", "integration", "Home Assistant / MQTT",
            tr("Printer, slots and spools as Home Assistant devices, messages and buttons"),
            "install", ("mqtt_host",), tr("An MQTT broker (MQTT_HOST and login)")),
    Feature("vision", "integration", tr("AI print-failure detection"),
            tr("Watches the camera for spaghetti and failed prints, warns or pauses"),
            "install", ("vision_url",), tr("The kobra-vision container and the camera")),
    Feature("auto_pa", "printer", tr("Auto PA"),
            tr("Pressure advance per speed from Spoolman, measured by the printer when missing"),
            "printer", ("pa",), tr("Klipper setup, module kobra_pa"), klipper_only=True),
    Feature("filament_z", "printer", tr("Z offset per filament"), tr("First-layer Z offset from the filament in Spoolman"),
            "printer", ("filament_z",), tr("Klipper setup, macro KOBRA_START"), klipper_only=True),
    Feature("powerloss", "printer", tr("Resume after a power loss"),
            tr("Continues an interrupted print at the right height after the power comes back"),
            "printer", ("powerloss",), tr("Klipper setup, module kobra_resume"), klipper_only=True),
    Feature("clog", "printer", tr("Clog detection"), tr("Compares the extruder with the filament encoder, warns or pauses"),
            "printer", ("clog",), tr("Klipper setup, module kobra_clog"), klipper_only=True),
    Feature("endless", "printer", tr("Endless spool"), tr("When a spool runs out, the ACE loads a matching other one"),
            "printer", ("endless",), tr("Klipper setup, ACEPRO"), klipper_only=True),
    Feature("io", "printer", tr("Light and sounds"), tr("Printer light and beeper on events (quiet at night)"),
            "printer", ("light_auto", "sound"), tr("Klipper setup, kobra-io app on the printer"), klipper_only=True),
]
BY_KEY = {f.key: f for f in FEATURES}

# Where each feature is explained: heading in docs/usage.md and in docs/de/usage.md (GitHub anchor from it)
DOC_HEADINGS = {
    "spools": ("Loading a spool into the ACE", "Spule in die ACE einlegen"),  # i18n: German doc heading
    "web": ("Web UI and app", "Weboberfläche und App"),  # i18n: German doc heading
    "app": ("Web UI and app", "Weboberfläche und App"),  # i18n: German doc heading
    "display": ("The printer's own display", "Das Display des Druckers"),  # i18n: German doc heading
    "orca": ("Slicing and printing", "Slicen und Drucken"),  # i18n: German doc heading
    "camera": ("Watching a print", "Einen Druck beobachten"),  # i18n: German doc heading
    "preview": ("Watching a print in 3D", "Einen Druck in 3D ansehen"),  # i18n: German doc heading
    "dryer_auto": ("Drying (ACE dryer)", "Trocknen (ACE-Trockner)"),  # i18n: German doc heading
    "recording": ("Terminal and logs", "Terminal und Logs"),  # i18n: German doc heading
    "mqtt": ("Home Assistant", "Home Assistant"),
    "vision": ("AI print-failure detection", "KI-Fehldruck-Erkennung"),  # i18n: German doc heading
    "auto_pa": ("Pressure advance (Auto-PA)", "Pressure Advance (Auto-PA)"),
    "filament_z": ("Z offset per filament", "Z-Versatz pro Filament"),  # i18n: German doc heading
    "powerloss": ("Resume after a power loss", "Fortsetzen nach Stromausfall"),  # i18n: German doc heading
    "clog": ("Clog detection", "Verstopfung erkennen"),  # i18n: German doc heading
    "endless": ("When a filament is used up", "Wenn ein Filament leer ist"),  # i18n: German doc heading
    "io": ("Settings", "Einstellungen"),  # i18n: German doc heading
}


class FeatureError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


def _slug(heading: str) -> str:
    """GitHub's anchor of a heading."""
    s = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return s.replace(" ", "-")


def doc_url(f: Feature, lang: Optional[str] = None) -> Optional[str]:
    en, de = DOC_HEADINGS.get(f.key, ("", ""))
    if not en:
        return None
    if (lang or current_lang()) == "de" and de:
        return f"{DOCS}de/usage.md#{_slug(de)}"
    return f"{DOCS}usage.md#{_slug(en)}"


def _env_set(key: str) -> bool:
    return os.environ.get(key.upper(), "").strip() != ""


def state(bridge: "Bridge", f: Feature, switches: List[Dict[str, Any]],
          devices: List[Dict[str, Any]]) -> Dict[str, Any]:
    """available (bool), on (bool | None), switchable (bool), source, why (text when not available/switchable)."""
    platform = getattr(bridge.moon, "platform", "klipper")
    out: Dict[str, Any] = {"available": True, "on": None, "switchable": False, "source": f.source, "why": None}
    if f.klipper_only and platform == "rinkhals":
        return dict(out, available=False, why=tr("Only with the Klipper setup"))
    if f.source == "core":
        return dict(out, on=True, why=tr("Always on"))
    if f.source == "setting":
        on = all(bool(getattr(bridge.cfg, k)) for k in f.keys)
        if any(_env_set(k) for k in f.keys):
            return dict(out, on=on, source="install",
                        why=tr("Set by the installation ({env})", env=", ".join(k.upper() for k in f.keys)))
        return dict(out, on=on, switchable=True)
    if f.source == "printer":
        by = {i["key"]: i for i in switches}
        present = [by[k] for k in f.keys if k in by]
        if not present:
            return dict(out, available=False, why=tr("Not installed on the printer"))
        return dict(out, on=all(i.get("on") for i in present), switchable=True)
    if f.source == "install":
        on = bool(str(getattr(bridge.cfg, f.keys[0], "") or "").strip())
        return dict(out, on=on, why=tr("Set by the installation ({env})", env=f.keys[0].upper()) if on
                    else tr("Not set up: {needs}", needs=f.needs))
    if f.source == "client":
        n = sum(1 for d in devices if d.get("kind") in f.keys)
        return dict(out, on=n > 0, paired=n,
                    why=tr("{n} paired", n=n) if n else tr("Not paired yet – set it up there"))
    return out


def view(bridge: "Bridge") -> Dict[str, Any]:
    switches = bridge.switches.view().get("items", []) if getattr(bridge, "switches", None) else []
    devices = list(getattr(bridge.devices, "devices", []) or [])
    items = []
    for f in FEATURES:
        st = state(bridge, f, switches, devices)
        items.append({"key": f.key, "group": f.group, "title": f.title, "text": f.text, "needs": f.needs or None,
                      "doc": doc_url(f), **st})
    used = {i["group"] for i in items}
    return {"groups": [{"key": k, "title": t} for k, t in GROUPS if k in used], "items": items,
            "platform": getattr(bridge.moon, "platform", "klipper")}


async def switch(bridge: "Bridge", key: str, on: Any) -> Dict[str, Any]:
    """Switch a feature where its switch lives. Errors: FeatureError (404 unknown, 409 not switchable here)."""
    f = BY_KEY.get(key)
    if f is None:
        raise FeatureError(404, tr("Unknown feature"))
    if not isinstance(on, bool):
        raise FeatureError(400, tr("Value: true or false"))
    switches = bridge.switches.view().get("items", []) if getattr(bridge, "switches", None) else []
    st = state(bridge, f, switches, list(getattr(bridge.devices, "devices", []) or []))
    if not st["available"] or not st["switchable"]:
        raise FeatureError(409, st["why"] or tr("Not switchable here"))
    if f.source == "setting":
        try:
            bridge.settings.update({k: on for k in f.keys})
        except ValueError as e:
            raise FeatureError(400, str(e)) from e
    else:
        from .switches import SwitchError
        present = {i["key"] for i in switches}
        try:
            for k in f.keys:
                if k in present:
                    await bridge.switches.set(k, on)
        except SwitchError as e:
            raise FeatureError(e.status, str(e)) from e
    return {"ok": True, "key": key, "on": on}
