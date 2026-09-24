"""Spoolman -> Orca-Filamentwerte (Etappe 3) und Ruecksync Orca -> Spoolman.

Die Bridge liefert pro Filament nur die Werte, die aus Spoolman kommen (Filament oder
Vorlage). Das Orca-Basisprofil selbst loest das Plugin in Orca auf: so gelten genau die
Werte der installierten Orca-Version, ohne Kopien von Orca-Profilen in der Bridge.

Reihenfolge (spaeter gewinnt):
  Orca-Basisprofil  <-  Vorlage  <-  Filament  <-  Orca-Overrides (Vorlage, dann Filament)
Hat das Filament ein eigenes Orca-Basisprofil, faellt die Vorlage komplett weg.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from .profiles import basic_info, color_hex, find_template
from .spoolman import extra_value

# (Quelle in Spoolman, Orca-Schluessel, Typ)
#   "native:<feld>"  = Spoolman-Standardfeld des Filaments
#   "extra:<schluessel>" = Zusatzfeld aus spoolman_setup.py
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

# Kennwerte, die immer vom Filament selbst kommen (nie aus der Vorlage)
IDENTITY_KEYS = ("filament_type", "filament_colour", "filament_density", "filament_diameter",
                 "filament_cost", "filament_vendor", "filament_id")

# Werte, die das Plugin nie zurueck nach Spoolman schreiben soll
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


def parse_overrides(text: Any) -> Dict[str, str]:
    """'schluessel = wert' je Zeile; Kommentare mit # am Zeilenanfang."""
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

    # Kennwerte des Filaments
    material = fil.get("material") or (tpl or {}).get("material") or ""
    ident = {
        "filament_type": base_type(material) or material,
        "filament_colour": f"#{color_hex(fil)}" if color_hex(fil) else None,
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

    # Freie Overrides: erst die der Vorlage, dann die des Filaments
    for origin, obj in (("vorlage", tpl), ("filament", fil)):
        for k, v in parse_overrides(extra_value(obj, "orca_overrides") if obj else None).items():
            values[k] = v
            sources[k] = f"override-{origin}"

    active = [s for s in spools if (s.get("filament") or {}).get("id") == fil["id"] and not s.get("archived")]
    body = {
        "filament_id": fil["id"],
        "orca_id": info["orca_filament_id"],
        "name": fil.get("name") or "",
        "vendor": info["vendor"],
        "display_name": info["display_name"],
        "material": material,
        "color": color_hex(fil),
        "base": info["orca_basis"],
        "template": (tpl or {}).get("name"),
        "values": values,
        "sources": sources,
        "spools": [{"id": s["id"], "remaining_weight": s.get("remaining_weight"),
                    "slot": slot_of(s.get("location"))} for s in active],
    }
    body["hash"] = hashlib.sha1(json.dumps({k: body[k] for k in ("orca_id", "name", "vendor", "base", "values")},
                                           sort_keys=True, default=str).encode()).hexdigest()[:12]
    return body


# ------------------------------------------------------------------ Ruecksync
def backsync_patch(fil: Dict[str, Any], changes: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    """Uebersetzt geaenderte Orca-Werte in ein Spoolman-PATCH fuer das Filament.

    Rueckgabe: (patch, uebernommen {orca_key: wert}, ignoriert [orca_key]).
    Werte ohne eigenes Spoolman-Feld landen in 'orca_overrides' des Filaments.
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
            val = _convert(raw, typ)
            kind, name = src.split(":", 1)
            if kind == "native":
                patch[name] = val
            else:
                extra[name] = None if val is None else json.dumps(val)
            applied[key] = val
            if key in overrides:  # eigenes Feld hat Vorrang vor einem alten Override
                overrides.pop(key)
                overrides_changed = True
            continue
        if key == "enable_pressure_advance":
            if _convert(raw, bool) is False:
                extra["pressure_advance"] = None
                applied[key] = False
            else:
                ignored.append(key)  # "an" ergibt sich aus einem gesetzten PA-Wert
            continue
        if key == "filament_colour":
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
        # alles andere: freier Override
        overrides[key] = str(raw)
        applied[key] = str(raw)
        overrides_changed = True

    if overrides_changed:
        extra["orca_overrides"] = None if not overrides else json.dumps(format_overrides(overrides))
    if extra:
        patch["extra"] = extra
    return patch, applied, ignored


def reset_patch(fil: Dict[str, Any], keys: List[str]) -> Tuple[Dict[str, Any], List[str]]:
    """Felder am Filament leeren, damit wieder Vorlage/Basisprofil gilt."""
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
    if extra:
        patch["extra"] = extra
    return patch, done
