"""Spoolman -> Orca filament values and back-sync Orca -> Spoolman.

Per filament the bridge delivers only the values that come from Spoolman (filament or template). The plugin resolves
the Orca base profile itself inside Orca: so exactly the values of the installed Orca version apply, without copies of
Orca profiles in the bridge.

Order (later wins):
  Orca base profile  <-  template  <-  filament  <-  Orca overrides (template, then filament)
If the filament has its own Orca base profile, the template is dropped completely.
Source codes in "sources" (stable API): filament, vorlage (template), override-filament, override-vorlage.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from .profiles import basic_info, color_hex, find_template
from .spoolman import extra_value

# (source in Spoolman, Orca key, type)
#   "native:<field>"  = Spoolman standard field of the filament
#   "extra:<key>" = extra field from spoolman_setup.py
FIELD_MAP: List[Tuple[str, str, Callable[[Any], Any]]] = [
    ("native:settings_extruder_temp", "nozzle_temperature", int),
    ("extra:nozzle_temp_first_layer", "nozzle_temperature_initial_layer", int),
    ("native:settings_bed_temp", "textured_plate_temp", int),
    ("extra:bed_temp_first_layer", "textured_plate_temp_initial_layer", int),
    ("extra:bed_temp_smooth", "hot_plate_temp", int),
    ("extra:bed_temp_smooth_first_layer", "hot_plate_temp_initial_layer", int),
    ("extra:chamber_temp", "chamber_temperature", int),
    ("extra:fan_min", "fan_min_speed", int),
    ("extra:fan_max", "fan_max_speed", int),
    ("extra:fan_off_first_layers", "close_fan_the_first_x_layers", int),
    ("extra:overhang_fan", "overhang_fan_speed", int),
    ("extra:aux_fan", "additional_cooling_fan_speed", int),
    ("extra:air_filtration", "activate_air_filtration", bool),
    ("extra:exhaust_fan_print", "during_print_exhaust_fan_speed", int),
    ("extra:exhaust_fan_done", "complete_print_exhaust_fan_speed", int),
    ("extra:flow_ratio", "filament_flow_ratio", float),
    ("extra:pressure_advance", "pressure_advance", float),
    ("extra:max_volumetric_speed", "filament_max_volumetric_speed", float),
    ("extra:retraction_length", "filament_retraction_length", float),
    ("extra:retraction_speed", "filament_retraction_speed", int),
    ("extra:z_hop", "filament_z_hop", float),
]
ORCA_TO_SOURCE = {orca: (src, typ) for src, orca, typ in FIELD_MAP}

# colour: Orca drops filament_colour in filament presets ("incorrect keys ... removed") and uses
# default_filament_colour when selecting (PresetComboBoxes.cpp).
# Back-sync accepts both colour keys (filament_colour from older plugin versions)
COLOUR_KEYS = ("default_filament_colour", "filament_colour")

# values the plugin must never write back to Spoolman
BACKSYNC_IGNORE = {"filament_id", "filament_settings_id", "inherits", "name", "from", "instantiation",
                   "filament_type", "filament_vendor", "compatible_printers", "compatible_printers_condition",
                   "version", "setting_id", "filament_extruder_variant"}

OVERRIDE_LINE = re.compile(r"^\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$")


def _raw(obj: Optional[Dict[str, Any]], source: str) -> Any:
    if not obj:
        return None
    kind, key = source.split(":", 1)
    if kind == "native":
        return obj.get(key)
    return extra_value(obj, key)


def _convert(value: Any, typ: Callable[[Any], Any]) -> Any:
    if value is None or value == "":
        return None
    try:
        if typ is bool:
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "ja", "yes", "on")
            return bool(value)
        if typ is int:
            return int(round(float(value)))
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_of_list(value: Any) -> Any:
    """Orca 2.5 stores many filament values per extruder variant; an older plugin sent them as a JSON list in text.
    Spoolman has one value per field -> the first entry (Direct Drive Standard)."""
    if isinstance(value, list):
        return value[0] if value else None
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            parsed = json.loads(value)
        except ValueError:
            return value
        if isinstance(parsed, list):
            return parsed[0] if parsed else None
    return value


def parse_overrides(text: Any) -> Dict[str, str]:
    """'key = value' per line; comments with # at the start of a line."""
    out: Dict[str, str] = {}
    for line in str(text or "").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = OVERRIDE_LINE.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def format_overrides(values: Dict[str, str]) -> Optional[str]:
    if not values:
        return None
    return "\n".join(f"{k} = {v}" for k, v in sorted(values.items()))


def filament_price_per_kg(fil: Dict[str, Any]) -> Optional[float]:
    price, weight = fil.get("price"), fil.get("weight")
    if price and weight:
        return round(float(price) / float(weight) * 1000.0, 2)
    return None


def build_profile(fil: Dict[str, Any], templates: List[Dict[str, Any]], base_type: Callable[[str], str],
                  spools: List[Dict[str, Any]], slot_of: Callable[[Optional[str]], Optional[int]]) -> Dict[str, Any]:
    info = basic_info(fil, templates)
    own_basis = extra_value(fil, "orca_basis")
    tpl = None if own_basis else find_template(fil, templates)

    values: Dict[str, Any] = {}
    sources: Dict[str, str] = {}
    for src, orca_key, typ in FIELD_MAP:
        v = _convert(_raw(fil, src), typ)
        origin = "filament"
        if v is None and tpl is not None:
            v = _convert(_raw(tpl, src), typ)
            origin = "vorlage"
        if v is not None:
            values[orca_key] = v
            sources[orca_key] = origin
    if "pressure_advance" in values:
        values["enable_pressure_advance"] = True
        sources["enable_pressure_advance"] = sources["pressure_advance"]

    # characteristics of the filament
    material = fil.get("material") or (tpl or {}).get("material") or ""
    ident = {
        "filament_type": base_type(material) or material,
        "default_filament_colour": f"#{color_hex(fil)}" if color_hex(fil) else None,
        "filament_density": fil.get("density"),
        "filament_diameter": fil.get("diameter"),
        "filament_cost": filament_price_per_kg(fil),
        "filament_vendor": info["vendor"] or None,
        "filament_id": info["orca_filament_id"],
    }
    for k, v in ident.items():
        if v not in (None, ""):
            values[k] = v
            sources[k] = "filament"

    # free overrides: first the template's, then the filament's
    for origin, obj in (("vorlage", tpl), ("filament", fil)):
        for k, v in parse_overrides(extra_value(obj, "orca_overrides") if obj else None).items():
            values[k] = v
            sources[k] = f"override-{origin}"

    # Orca base profile: on the filament, else from the template, else the fallback "Generic <type> @System"
    # (issue #1 - before, the plugin then reported "–" not found)
    base, base_source = info["orca_basis"], ("filament" if own_basis else "template")
    if not base:
        btype = base_type(material) or material
        base, base_source = (f"Generic {btype} @System", "fallback") if btype else (None, None)
    active = [s for s in spools if (s.get("filament") or {}).get("id") == fil["id"] and not s.get("archived")]
    body = {
        "filament_id": fil["id"],
        "orca_id": info["orca_filament_id"],
        "name": fil.get("name") or "",
        "vendor": info["vendor"],
        "display_name": info["display_name"],
        "material": material,
        "color": color_hex(fil),
        "base": base,
        "base_source": base_source,               # filament | template | fallback | None
        "template": (tpl or {}).get("name"),
        "values": values,
        "sources": sources,
        "spools": [{"id": s["id"], "remaining_weight": s.get("remaining_weight"),
                    "slot": slot_of(s.get("location"))} for s in active],
    }
    body["hash"] = hashlib.sha1(json.dumps({k: body[k] for k in ("orca_id", "name", "vendor", "base", "values")},
                                           sort_keys=True, default=str).encode()).hexdigest()[:12]
    return body


# ------------------------------------------------------------------ back-sync
def backsync_patch(fil: Dict[str, Any], changes: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    """Translates changed Orca values into a Spoolman PATCH for the filament.

    Returns: (patch, applied {orca_key: value}, ignored [orca_key]).
    Values without their own Spoolman field go into the filament's 'orca_overrides'.
    """
    patch: Dict[str, Any] = {}
    extra: Dict[str, Optional[str]] = {}
    applied: Dict[str, Any] = {}
    ignored: List[str] = []
    overrides = parse_overrides(extra_value(fil, "orca_overrides"))
    overrides_changed = False

    for key, raw in changes.items():
        if key in BACKSYNC_IGNORE:
            ignored.append(key)
            continue
        if key in ORCA_TO_SOURCE:
            src, typ = ORCA_TO_SOURCE[key]
            raw = _first_of_list(raw)
            val = _convert(raw, typ)
            if val is None and raw not in (None, ""):
                ignored.append(key)  # unreadable: never clear a field just because the value looks unknown
                continue
            kind, name = src.split(":", 1)
            if kind == "native":
                patch[name] = val
            else:
                extra[name] = None if val is None else json.dumps(val)
            applied[key] = val
            if key in overrides:  # its own field takes precedence over an old override
                overrides.pop(key)
                overrides_changed = True
            continue
        if key == "enable_pressure_advance":
            if _convert(raw, bool) is False:
                extra["pressure_advance"] = None
                applied[key] = False
            else:
                ignored.append(key)  # "on" follows from a set PA value
            continue
        if key in COLOUR_KEYS:
            hexv = str(raw or "").strip().lstrip("#").upper()[:6]
            if re.fullmatch(r"[0-9A-F]{6}", hexv):
                patch["color_hex"] = hexv
                applied[key] = f"#{hexv}"
            else:
                ignored.append(key)
            continue
        if key in ("filament_density", "filament_diameter"):
            val = _convert(raw, float)
            if val:
                patch[key.split("_", 1)[1]] = val
                applied[key] = val
            else:
                ignored.append(key)
            continue
        if key == "filament_cost":
            val = _convert(raw, float)
            weight = fil.get("weight")
            if val is not None and weight:
                patch["price"] = round(val * float(weight) / 1000.0, 2)
                applied[key] = val
            else:
                ignored.append(key)
            continue
        # everything else: free override
        overrides[key] = str(raw)
        applied[key] = str(raw)
        overrides_changed = True

    if overrides_changed:
        extra["orca_overrides"] = None if not overrides else json.dumps(format_overrides(overrides))
    _drop_pa_table(fil, extra)
    if extra:
        patch["extra"] = extra
    return patch, applied, ignored


def _drop_pa_table(fil: Dict[str, Any], extra: Dict[str, Any]) -> None:
    """PA changed or reset by hand in Orca: the measured auto PA table no longer applies (it would overrule the new
    value). Without PA Klipper measures again at the next print (when switched on)."""
    if "pressure_advance" in extra and extra_value(fil, "pa_table") is not None:
        extra["pa_table"] = None


def reset_patch(fil: Dict[str, Any], keys: List[str]) -> Tuple[Dict[str, Any], List[str]]:
    """Clear fields on the filament so the template/base profile applies again."""
    patch: Dict[str, Any] = {}
    extra: Dict[str, Optional[str]] = {}
    done: List[str] = []
    overrides = parse_overrides(extra_value(fil, "orca_overrides"))
    overrides_changed = False
    for key in keys:
        if key in ORCA_TO_SOURCE:
            src, _ = ORCA_TO_SOURCE[key]
            kind, name = src.split(":", 1)
            if kind == "native":
                patch[name] = None
            else:
                extra[name] = None
            done.append(key)
        if key == "enable_pressure_advance":
            extra["pressure_advance"] = None
            done.append(key)
        if key in overrides:
            overrides.pop(key)
            overrides_changed = True
            if key not in done:
                done.append(key)
    if overrides_changed:
        extra["orca_overrides"] = None if not overrides else json.dumps(format_overrides(overrides))
    _drop_pa_table(fil, extra)
    if extra:
        patch["extra"] = extra
    return patch, done
