"""Settings that can be changed at runtime in the web UI / app.

The environment variables (config.py) are the start values. What is changed here is stored in DATA_DIR/settings.json
and overrides the start value at the next start. The values go straight into the Config object - the rest of the code
keeps reading cfg.<name> and sees the change at its next access (no restarts needed).
What would need a restart (addresses of printer, Spoolman, camera, AI service) is shown read-only.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .i18n import tr
from .storage import save_json

if TYPE_CHECKING:
    from .config import Config

log = logging.getLogger("settings")


@dataclass(frozen=True)
class Spec:
    key: str                 # name in the Config object
    group: str
    label: str
    kind: str                # bool | float | int | text | choice
    lo: Optional[float] = None
    hi: Optional[float] = None
    unit: str = ""
    help: str = ""
    options: tuple = ()      # choice: ((value, label), ...)


SPECS: List[Spec] = [
    # general
    Spec("language", tr("General"), tr("Language"), "choice",
         options=(("en", "English"), ("de", "Deutsch")),
         help=tr("For devices without their own language setting, and for Home Assistant (MQTT). Every browser and "
                 "the app can switch on their own")),
    # camera
    Spec("camera", tr("Camera"), tr("Camera through the bridge"), "bool",
         help=tr("Web, app and the Mainsail link fetch their images through the bridge")),
    Spec("camera_stream", tr("Camera"), tr("Continuous stream instead of snapshots"), "bool",
         help=tr("Full frame rate from the printer's MJPEG stream – only with Klipper on a separate computer. Under "
                 "Rinkhals it used the whole printer CPU, there the bridge always fetches snapshots by the printer CPU. "
                 "Takes effect at once. Default: off")),
    Spec("camera_fps_min", tr("Camera"), tr("Frame rate at least"), "float", 0.5, 15, "fps"),
    Spec("camera_fps_max", tr("Camera"), tr("Frame rate at most"), "float", 1, 15, "fps"),
    Spec("camera_cpu_low", tr("Camera"), tr("Faster below printer CPU (Rinkhals)"), "float", 30, 100, "%",
         tr("Below it 1 fps more every 5 s, up to the maximum")),
    Spec("camera_cpu_high", tr("Camera"), tr("Slower above printer CPU (Rinkhals)"), "float", 30, 100, "%",
         tr("Above it 1 fps less every 5 s")),
    # print preview
    Spec("render", tr("Print preview"), tr("Load the print file (model, remaining amount)"), "bool",
         help=tr("The bridge downloads the file once, throttled, at print start – for the 3D model and "
                 "“spool not enough”")),
    Spec("render_max_mb", tr("Print preview"), tr("Largest file"), "float", 10, 1000, "MB",
         tr("Larger files: thumbnail only")),
    Spec("render_interval_s", tr("Print preview"), tr("Recalculate the bridge image at most every"), "float", 5, 120,
         "s", tr("Only for devices with “image” instead of 3D")),
    Spec("geometry_max_segments", tr("Print preview"), tr("Detail of the 3D model (paths)"), "int", 100_000, 3_000_000,
         "", tr("More paths are thinned out. 1.5 million ≈ 20 MB transfer, maybe less for phones")),
    # slots and RFID
    Spec("auto_assign_by_tag", tr("Slots and RFID"), tr("Assign spools with our tag automatically"), "bool"),
    Spec("auto_assign_by_kind", tr("Slots and RFID"), tr("Assign spools with an Anycubic tag automatically"), "bool",
         help=tr("The Anycubic tag only names material and colour - if exactly one spool on the shelf fits, it is "
                 "assigned; with several the choice stays with you")),
    Spec("auto_unassign_on_empty", tr("Slots and RFID"), tr("Move an empty slot's spool to the shelf"), "bool",
         help=tr("When the ACE reports a slot empty, the spool goes to the shelf (during a print only afterwards)")),
    Spec("empty_debounce_s", tr("Slots and RFID"), tr("… when the slot is empty this long"), "float", 0, 600, "s"),
    Spec("set_ace_slot_info", tr("Slots and RFID"), tr("Write material and colour to the ACE"), "bool",
         help=tr("When assigning spools without a tag: material, colour and temperature to the ACE driver "
                 "(ACE_SET_SLOT)")),
    Spec("write_lane_data", tr("Slots and RFID"), tr("Write lane_data for Orca"), "bool",
         help=tr("So Orca's sync button puts the right profiles into the slots")),
    # moisture
    Spec("room_rh", tr("Spool moisture"), tr("Humidity in the storage room"), "float", 10, 95, "%",
         tr("For spools on the shelf, as long as no room sensor (ROOM_SENSOR_TOPIC) delivers fresh values")),
    Spec("dry_locations", tr("Spool moisture"), tr("Storage places with their own humidity"), "text",
         help=tr("Spoolman location=humidity, separated by ;  e.g.  Drybox=15; Vacuum bag=10")),
    Spec("pa_sync", tr("Pressure advance"), tr("Connect auto PA with Spoolman"), "bool",
         help=tr("Give the filaments' PA values to Klipper (if one is missing, Klipper measures during the print) and "
                 "write measurements back to the filament. Measuring itself is switched off on the ACE page "
                 "(pressure advance card)")),
    Spec("filament_z_sync", tr("First layer"), tr("Z offset per filament"), "bool",
         help=tr("Give the field “Z offset” of the filament (or its template) to the printer – the print start adds "
                 "the start filament's value to the first layer (+ = further from the bed)")),
    Spec("auto_dry_on_insert", tr("Spool moisture"), tr("Dry damp spools automatically when inserted"), "bool",
         help=tr("Temperature by the most sensitive loaded spool, duration by the dampest")),
    Spec("new_spools_dry", tr("Spool moisture"), tr("Dry new spools first"), "bool",
         help=tr("Spools without history count as needing drying when first inserted")),
    Spec("wet_print_action", tr("Spool moisture"), tr("Print start with a damp spool"), "choice",
         options=(("warn", tr("warn only")), ("pause", tr("pause the print at once")))),
    # messages
    Spec("low_spool_g", tr("Messages"), tr("“Spool almost empty” below"), "float", 0, 1000, "g"),
    Spec("reach_reserve_pct", tr("Messages"), tr("Reserve for “spool not enough”"), "float", 0, 50, "%"),
    # consumption
    Spec("book_usage", tr("Consumption"), tr("Book consumption in Spoolman"), "bool",
         help=tr("Off: only measure and show, change nothing in Spoolman")),
    Spec("book_interval_s", tr("Consumption"), tr("Interim booking while printing every"), "float", 30, 3600, "s"),
    Spec("book_min_mm", tr("Consumption"), tr("Smallest booking"), "float", 1, 1000, "mm"),
    # data
    Spec("telemetry", tr("Data"), tr("Print recordings (raw data)"), "bool"),
    Spec("telemetry_keep", tr("Data"), tr("Keep recordings"), "int", 1, 500, tr("prints")),
    Spec("job_history", tr("Data"), tr("Keep print history"), "int", 10, 2000, tr("prints")),
    Spec("humidity_days", tr("Data"), tr("Keep humidity history"), "int", 1, 365, tr("days")),
]
BY_KEY = {s.key: s for s in SPECS}

# read-only (need a restart of the bridge)
READONLY = [("moonraker_url", tr("Printer (Moonraker)")), ("spoolman_url", "Spoolman"),
            ("camera_snapshot_url", tr("Camera snapshot")), ("camera_stream_url", tr("Camera stream")),
            ("vision_url", tr("AI service")), ("mqtt_host", tr("MQTT broker")),
            ("room_sensor_topic", tr("Room sensor (MQTT topic)")), ("data_dir", tr("Data folder")),
            ("http_port", tr("HTTP port")), ("dry_run", tr("Test only (DRY_RUN)"))]


def _path(cfg: "Config") -> str:
    return os.path.join(cfg.data_dir, "settings.json")


def _coerce(spec: Spec, v: Any) -> Any:
    if spec.kind == "text":
        if not isinstance(v, str) or len(v) > 2000:
            raise ValueError(tr("{label}: text expected", label=spec.label))
        if spec.key == "dry_locations":
            from .moisture import parse_locations
            parse_locations(v)                 # raises ValueError with an explanation
        return v.strip()
    if spec.kind == "choice":
        allowed = [o[0] for o in spec.options]
        if v not in allowed:
            raise ValueError(tr("{label}: {options}", label=spec.label,
                                options=" | ".join(str(o[1]) for o in spec.options)))
        return v
    if spec.kind == "bool":
        if isinstance(v, bool):
            return v
        raise ValueError(tr("{label}: on or off expected", label=spec.label))
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(tr("{label}: number expected", label=spec.label)) from None
    if spec.kind == "int":
        if x != int(x):
            raise ValueError(tr("{label}: whole number expected", label=spec.label))
        x = int(x)
    if (spec.lo is not None and x < spec.lo) or (spec.hi is not None and x > spec.hi):
        raise ValueError(tr("{label}: allowed {lo:g}–{hi:g} {unit}", label=spec.label, lo=float(spec.lo),
                            hi=float(spec.hi), unit=spec.unit))
    return x


class RuntimeSettings:
    def __init__(self, cfg: "Config"):
        self.cfg = cfg
        self.defaults = {s.key: getattr(cfg, s.key) for s in SPECS}     # start values from the environment
        self.saved: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(_path(self.cfg), encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            log.warning("settings.json unreadable, using start values: %s", e)
            return
        for k, v in (data.items() if isinstance(data, dict) else []):
            spec = BY_KEY.get(k)
            if not spec:
                continue
            try:
                val = _coerce(spec, v)
            except ValueError as e:
                log.warning("Setting %s invalid, using the start value: %s", k, e)
                continue
            self.saved[k] = val
            setattr(self.cfg, k, val)
        self._check_pairs()

    def _save(self) -> None:
        os.makedirs(self.cfg.data_dir, exist_ok=True)
        save_json(_path(self.cfg), self.saved, indent=1)

    def _check_pairs(self) -> None:
        """Values that belong together: at least <= at most."""
        c = self.cfg
        if c.camera_fps_min > c.camera_fps_max:
            raise ValueError(tr("Frame rate: at least must not be above at most"))
        if c.camera_cpu_low >= c.camera_cpu_high:
            raise ValueError(tr("Printer CPU: “faster below” must be under “slower above”"))

    def update(self, changes: Dict[str, Any]) -> None:
        """Check, apply, save. On an error everything stays as it was (ValueError)."""
        unknown = [k for k in changes if k not in BY_KEY]
        if unknown:
            raise ValueError(tr("Not changeable: {keys}", keys=", ".join(unknown)))
        new = {k: _coerce(BY_KEY[k], v) for k, v in changes.items()}
        old = {k: getattr(self.cfg, k) for k in new}
        for k, v in new.items():
            setattr(self.cfg, k, v)
        try:
            self._check_pairs()
        except ValueError:
            for k, v in old.items():
                setattr(self.cfg, k, v)
            raise
        for k, v in new.items():
            if v == self.defaults[k]:
                self.saved.pop(k, None)
            else:
                self.saved[k] = v
        self._save()
        log.info("Settings changed: %s", ", ".join(f"{k}={v}" for k, v in new.items()))

    def reset(self, key: str) -> None:
        if key not in BY_KEY:
            raise ValueError(tr("Not changeable: {keys}", keys=key))
        self.update({key: self.defaults[key]})

    def view(self) -> Dict[str, Any]:
        groups: Dict[str, List[Dict[str, Any]]] = {}
        names: Dict[str, Any] = {}
        for s in SPECS:
            names.setdefault(str(s.group), s.group)
            groups.setdefault(str(s.group), []).append({
                "key": s.key, "label": s.label, "kind": s.kind, "min": s.lo, "max": s.hi, "unit": s.unit, "help": s.help,
                "options": [list(o) for o in s.options],
                "value": getattr(self.cfg, s.key), "default": self.defaults[s.key], "changed": s.key in self.saved})
        return {"groups": [{"name": names[g], "items": items} for g, items in groups.items()],
                "readonly": [{"key": k, "label": label, "value": getattr(self.cfg, k, None)} for k, label in READONLY]}
