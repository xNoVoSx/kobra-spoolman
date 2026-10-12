#!/usr/bin/env python3
"""
Spoolman setup for kobra-spoolman (ace-lane-bridge / Orca plugin).

Creates via the Spoolman API:
  * extra fields for filaments (Orca settings) and spools (NFC ID)
  * the vendor "Template" with seven material templates
    (start values from Orca's generic profiles, OrcaSlicer main 2026-09)

The script only creates things. Existing fields, vendors and filaments are not changed and nothing is deleted.
Running it more than once is harmless. An install from before 3.12 with the German vendor "Vorlage" keeps it.

Usage:
  python3 spoolman_setup.py                 # shows the plan, asks
  python3 spoolman_setup.py --dry-run       # show only
  python3 spoolman_setup.py --yes           # without asking
  python3 spoolman_setup.py --url http://<spoolman-host>:7912
  python3 spoolman_setup.py --language de   # names in Spoolman in German (fields, vendor, templates)

Python standard library only, tested against Spoolman 0.26.1.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = os.environ.get("SPOOLMAN_URL", "http://localhost:7912")

# ---------------------------------------------------------------------------
# Extra fields. IMPORTANT: set no default_value, else every new filament gets the value and the inheritance
# (empty = from the template/Orca) would be broken. The keys are fixed (the bridge reads them); the names are what
# Spoolman shows.
# key -> ({language: name}, type, unit, order)  |  comment = Orca key
# ---------------------------------------------------------------------------
FILAMENT_FIELDS = [
    ("orca_basis",                  {"en": "Orca base profile", "de": "Orca-Basisprofil"},                    "text",    None,    1),   # name of the Orca system profile
    ("vorlage",                     {"en": "Template", "de": "Vorlage"},                                       "choice",  None,    2),   # empty = automatic by material
    ("nozzle_temp_first_layer",     {"en": "Nozzle first layer", "de": "Düse erste Schicht"},                 "integer", "°C",    10),  # nozzle_temperature_initial_layer
    ("bed_temp_first_layer",        {"en": "Bed first layer", "de": "Bett erste Schicht"},                    "integer", "°C",    11),  # textured_plate_temp_initial_layer
    ("bed_temp_smooth",             {"en": "Bed smooth PEI", "de": "Bett glatte PEI"},                        "integer", "°C",    12),  # hot_plate_temp
    ("bed_temp_smooth_first_layer", {"en": "Bed smooth PEI first layer", "de": "Bett glatte PEI erste Schicht"}, "integer", "°C", 13),  # hot_plate_temp_initial_layer
    ("chamber_temp",                {"en": "Chamber temperature", "de": "Kammertemperatur"},                  "integer", "°C",    14),  # chamber_temperature
    ("dry_temp",                    {"en": "Dry max.", "de": "Trocknen max."},                                "integer", "°C",    15),  # ACE dryer, no Orca value
    ("dry_hours",                   {"en": "Dry duration", "de": "Trocknen Dauer"},                           "float",   "h",     16),  # minimum duration at "Dry max." (bridge)
    ("open_days",                   {"en": "Open until drying", "de": "Offen bis Trocknen"},                  "float",   {"en": "days", "de": "Tage"}, 17),  # at 50 % RH until "drying recommended"
    ("fan_min",                     {"en": "Part fan min", "de": "Bauteillüfter min"},                        "integer", "%",     20),  # fan_min_speed
    ("fan_max",                     {"en": "Part fan max", "de": "Bauteillüfter max"},                        "integer", "%",     21),  # fan_max_speed
    ("fan_off_first_layers",        {"en": "Fan off first layers", "de": "Lüfter aus erste Schichten"},       "integer", {"en": "layers", "de": "Schichten"}, 22),  # close_fan_the_first_x_layers
    ("overhang_fan",                {"en": "Overhang fan", "de": "Überhang-Lüfter"},                          "integer", "%",     23),  # overhang_fan_speed
    ("aux_fan",                     {"en": "Auxiliary fan", "de": "Hilfslüfter"},                             "integer", "%",     24),  # additional_cooling_fan_speed
    ("air_filtration",              {"en": "Air filtration (exhaust)", "de": "Luftfilterung (Abluft)"},       "boolean", None,    30),  # activate_air_filtration
    ("exhaust_fan_print",           {"en": "Exhaust during print", "de": "Abluft während Druck"},            "integer", "%",     31),  # during_print_exhaust_fan_speed
    ("exhaust_fan_done",            {"en": "Exhaust after print", "de": "Abluft nach Druck"},                 "integer", "%",     32),  # complete_print_exhaust_fan_speed
    ("flow_ratio",                  {"en": "Flow ratio", "de": "Flow Ratio"},                                 "float",   None,    40),  # filament_flow_ratio
    ("pressure_advance",            {"en": "Pressure advance", "de": "Pressure Advance"},                     "float",   None,    41),  # pressure_advance (+enable)
    ("pa_table",                    {"en": "PA table (auto PA)", "de": "PA-Tabelle (Auto-PA)"},               "text",    None,    43),  # measured by kobra_pa (the bridge writes it)
    ("z_offset",                    {"en": "Z offset", "de": "Z-Versatz"},                                    "float",   "mm",    44),  # KOBRA_START, first layer (+ = further away)
    ("max_volumetric_speed",        {"en": "Max. volumetric speed", "de": "Max. Volumenstrom"},               "float",   "mm³/s", 42),  # filament_max_volumetric_speed
    ("retraction_length",           {"en": "Retraction length", "de": "Retraction Länge"},                    "float",   "mm",    50),  # filament_retraction_length
    ("retraction_speed",            {"en": "Retraction speed", "de": "Retraction Geschwindigkeit"},           "integer", "mm/s",  51),  # filament_retraction_speed
    ("z_hop",                       {"en": "Z hop", "de": "Z-Hop"},                                           "float",   "mm",    52),  # filament_z_hop
    ("orca_overrides",              {"en": "Orca overrides", "de": "Orca-Overrides"},                         "text",    None,    90),  # "key = value" per line
]

SPOOL_FIELDS = [
    ("nfc_uid",                     {"en": "NFC ID", "de": "NFC-Kennung"},                                    "text",    None,    10),  # tag UID (set by the bridge/app)
    ("tag_nr",                      {"en": "Tag number", "de": "Tag-Nummer"},                                 "integer", None,    11),  # number in the SKU of self-written tags
    ("moisture",                    {"en": "Moisture estimate", "de": "Feuchte-Schätzung"},                   "integer", "%",     20),  # 100 = drying recommended (set by the bridge)
    ("last_in_ace",                 {"en": "Last in the ACE", "de": "Zuletzt im ACE"},                        "datetime", None,   21),  # when it was taken out
    ("last_dried",                  {"en": "Last dried", "de": "Zuletzt getrocknet"},                         "datetime", None,   22),
    ("last_dried_info",             {"en": "Last dried with", "de": "Zuletzt getrocknet mit"},                "text",    None,    23),  # temperature
]

# template vendor per language; templates are named "<vendor> <name>" ("Template PETG")
VENDOR_NAMES = {"en": "Template", "de": "Vorlage"}
TEXTS = {
    "en": {"vendor_comment": "Material templates for the Orca plugin - do not use as real spools",
           "template_comment": "Material template. Empty fields inherit from the Orca base profile."},
    "de": {"vendor_comment": "Materialvorlagen für das Orca-Plugin - nicht als echte Spulen verwenden",
           "template_comment": "Materialvorlage. Leere Felder erben vom Orca-Basisprofil."},
}

# start values per template (name without the vendor prefix)
TEMPLATES = [
    {
        "name": "PLA",
        "material": "PLA",
        "density": 1.24,
        "diameter": 1.75,
        "settings_extruder_temp": 220,
        "settings_bed_temp": 55,
        "extra": {
            "dry_temp": 55,
            "orca_basis": "Generic PLA @System",
            "nozzle_temp_first_layer": 220,
            "bed_temp_first_layer": 55,
            "bed_temp_smooth": 55,
            "bed_temp_smooth_first_layer": 55,
            "fan_min": 100,
            "fan_max": 100,
            "fan_off_first_layers": 1,
            "overhang_fan": 100,
            "aux_fan": 70,
            "air_filtration": False,
            "exhaust_fan_print": 70,
            "exhaust_fan_done": 70,
            "flow_ratio": 0.98,
            "max_volumetric_speed": 12.0
        }
    },
    {
        "name": "PLA Silk",
        "material": "PLA",
        "density": 1.24,
        "diameter": 1.75,
        "settings_extruder_temp": 220,
        "settings_bed_temp": 55,
        "extra": {
            "dry_temp": 55,
            "orca_basis": "Generic PLA Silk @System",
            "nozzle_temp_first_layer": 220,
            "bed_temp_first_layer": 55,
            "bed_temp_smooth": 55,
            "bed_temp_smooth_first_layer": 55,
            "fan_min": 100,
            "fan_max": 100,
            "fan_off_first_layers": 1,
            "overhang_fan": 100,
            "aux_fan": 70,
            "air_filtration": False,
            "exhaust_fan_print": 70,
            "exhaust_fan_done": 70,
            "flow_ratio": 0.98,
            "max_volumetric_speed": 7.5,
            "retraction_length": 0.5
        }
    },
    {
        "name": "PETG",
        "material": "PETG",
        "density": 1.27,
        "diameter": 1.75,
        "settings_extruder_temp": 255,
        "settings_bed_temp": 80,
        "extra": {
            "dry_temp": 60,
            "orca_basis": "Generic PETG @System",
            "nozzle_temp_first_layer": 255,
            "bed_temp_first_layer": 80,
            "bed_temp_smooth": 80,
            "bed_temp_smooth_first_layer": 80,
            "fan_min": 20,
            "fan_max": 100,
            "fan_off_first_layers": 3,
            "overhang_fan": 100,
            "air_filtration": False,
            "exhaust_fan_print": 70,
            "exhaust_fan_done": 70,
            "flow_ratio": 1.0,
            "max_volumetric_speed": 10.0
        }
    },
    {
        "name": "ASA",
        "material": "ASA",
        "density": 1.04,
        "diameter": 1.75,
        "settings_extruder_temp": 260,
        "settings_bed_temp": 100,
        "extra": {
            "dry_temp": 65,
            "orca_basis": "Generic ASA @System",
            "nozzle_temp_first_layer": 260,
            "bed_temp_first_layer": 105,
            "bed_temp_smooth": 100,
            "bed_temp_smooth_first_layer": 105,
            "fan_min": 10,
            "fan_max": 80,
            "fan_off_first_layers": 3,
            "overhang_fan": 80,
            "air_filtration": False,
            "exhaust_fan_print": 70,
            "exhaust_fan_done": 70,
            "flow_ratio": 0.926,
            "max_volumetric_speed": 12.0
        }
    },
    {
        "name": "TPU",
        "material": "TPU",
        "density": 1.24,
        "diameter": 1.75,
        "settings_extruder_temp": 240,
        "settings_bed_temp": 35,
        "extra": {
            "dry_temp": 55,
            "orca_basis": "Generic TPU @System",
            "nozzle_temp_first_layer": 240,
            "bed_temp_first_layer": 35,
            "bed_temp_smooth": 35,
            "bed_temp_smooth_first_layer": 35,
            "fan_min": 100,
            "fan_max": 100,
            "fan_off_first_layers": 1,
            "overhang_fan": 100,
            "aux_fan": 70,
            "air_filtration": False,
            "exhaust_fan_print": 70,
            "exhaust_fan_done": 70,
            "flow_ratio": 1.0,
            "max_volumetric_speed": 3.2,
            "retraction_length": 0.4
        }
    },
    {
        "name": "PLA-CF",
        "material": "PLA-CF",
        "density": 1.24,
        "diameter": 1.75,
        "settings_extruder_temp": 220,
        "settings_bed_temp": 55,
        "extra": {
            "dry_temp": 55,
            "orca_basis": "Generic PLA-CF @System",
            "nozzle_temp_first_layer": 220,
            "bed_temp_first_layer": 55,
            "bed_temp_smooth": 55,
            "bed_temp_smooth_first_layer": 55,
            "fan_min": 100,
            "fan_max": 100,
            "fan_off_first_layers": 1,
            "overhang_fan": 100,
            "aux_fan": 70,
            "air_filtration": False,
            "exhaust_fan_print": 70,
            "exhaust_fan_done": 70,
            "flow_ratio": 0.95,
            "max_volumetric_speed": 12.0
        }
    },
    {
        "name": "PETG-CF",
        "material": "PETG-CF",
        "density": 1.27,
        "diameter": 1.75,
        "settings_extruder_temp": 255,
        "settings_bed_temp": 80,
        "extra": {
            "dry_temp": 65,
            "orca_basis": "Generic PETG-CF @System",
            "nozzle_temp_first_layer": 255,
            "bed_temp_first_layer": 80,
            "bed_temp_smooth": 80,
            "bed_temp_smooth_first_layer": 80,
            "fan_min": 5,
            "fan_max": 40,
            "fan_off_first_layers": 3,
            "overhang_fan": 100,
            "air_filtration": False,
            "exhaust_fan_print": 70,
            "exhaust_fan_done": 70,
            "flow_ratio": 1.0,
            "max_volumetric_speed": 11.5
        }
    }
]


# ---------------------------------------------------------------------------
class Api:
    def __init__(self, base: str, dry_run: bool):
        self.base = base.rstrip("/") + "/api/v1"
        self.dry_run = dry_run

    def _req(self, method: str, path: str, body=None, query=None):
        url = self.base + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            raise SystemExit(f"ERROR {method} {path}: HTTP {e.code}\n{detail}") from None
        except urllib.error.URLError as e:
            raise SystemExit(f"ERROR: Spoolman at {self.base} not reachable ({e.reason})") from None

    def get(self, path, query=None):
        return self._req("GET", path, query=query)

    def write(self, method, path, body):
        if self.dry_run:
            return None
        return self._req(method, path, body)


def field_body(name, ftype, unit, order, choices=None):
    body = {"name": name, "field_type": ftype, "order": order}
    if unit:
        body["unit"] = unit
    if ftype == "choice":
        body["choices"] = choices
        body["multi_choice"] = False
    return body


def pick(value, lang):
    """A name or unit in the chosen language (plain strings are the same in every language)."""
    return value.get(lang) if isinstance(value, dict) else value


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=DEFAULT_URL, help=f"Spoolman URL (default: {DEFAULT_URL})")
    ap.add_argument("--dry-run", action="store_true", help="show only, write nothing")
    ap.add_argument("--yes", "-y", action="store_true", help="run without asking")
    ap.add_argument("--language", choices=("en", "de"), default="en",
                    help="language of the names in Spoolman (fields, template vendor, templates); default en")
    args = ap.parse_args()
    lang = args.language

    api = Api(args.url, args.dry_run)
    info = api.get("/info")
    print(f"Spoolman {info.get('version')} at {args.url}  (automatic backups: {info.get('automatic_backups')})")

    # an existing template vendor (German "Vorlage" from before 3.12 or "Template") stays in use
    all_vendors = api.get("/vendor")
    vendor = next((v for n in (VENDOR_NAMES[lang], *VENDOR_NAMES.values()) for v in all_vendors if v.get("name") == n),
                  None)
    vendor_name = vendor["name"] if vendor else VENDOR_NAMES[lang]
    vendor_id = vendor["id"] if vendor else None
    templates = [dict(t, name=f"{vendor_name} {t['name']}") for t in TEMPLATES]
    template_names = [t["name"] for t in templates]
    plan = []  # (description, action)

    # --- extra fields -----------------------------------------------------------
    for entity, fields in (("filament", FILAMENT_FIELDS), ("spool", SPOOL_FIELDS)):
        existing = {f["key"]: f for f in api.get(f"/field/{entity}")}
        for key, names, ftype, unit, order in fields:
            name, unit = pick(names, lang), pick(unit, lang)
            choices = template_names if key == "vorlage" else None
            if key in existing:
                ex = existing[key]
                if ex["field_type"] != ftype:
                    print(f"  WARNING: field {entity}.{key} exists with type {ex['field_type']} (expected {ftype}) - left unchanged")
                    continue
                if key == "vorlage":
                    missing = [c for c in template_names if c not in (ex.get("choices") or [])]
                    if missing:
                        new_choices = list(ex.get("choices") or []) + missing
                        body = field_body(ex["name"], ftype, ex.get("unit"), ex.get("order", order), new_choices)
                        plan.append((f"field {entity}.{key}: add choices {missing}",
                                     lambda e=entity, k=key, b=body: api.write("POST", f"/field/{e}/{k}", b)))
                continue
            body = field_body(name, ftype, unit, order, choices)
            plan.append((f"create field {entity}.{key} ({name}, {ftype}{', ' + unit if unit else ''})",
                         lambda e=entity, k=key, b=body: api.write("POST", f"/field/{e}/{k}", b)))

    # --- vendor + templates ------------------------------------------------------
    existing_names = set()
    if vendor_id is not None:
        existing_names = {f.get("name") for f in api.get("/filament", {"vendor.id": vendor_id})}
    else:
        plan.append((f"create vendor '{vendor_name}'", None))  # handled separately below

    for t in templates:
        if t["name"] in existing_names:
            continue
        plan.append((f"create filament '{t['name']}' (base {t['extra']['orca_basis']})", t))

    if not plan:
        print("Everything is there already - nothing to do.")
        return 0

    print("\nPlanned changes:")
    for desc, _ in plan:
        print("  +", desc)
    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0
    if not args.yes:
        if input("\nRun? [y/N] ").strip().lower() not in ("y", "yes", "j", "ja"):
            print("Cancelled.")
            return 1

    for desc, action in plan:
        if callable(action):
            action()
        elif action is None:  # vendor
            vendor_id = api.write("POST", "/vendor", {"name": vendor_name,
                                                      "comment": TEXTS[lang]["vendor_comment"]})["id"]
        else:  # template
            t = action
            body = {k: v for k, v in t.items() if k != "extra"}
            body["vendor_id"] = vendor_id
            body["comment"] = TEXTS[lang]["template_comment"]
            body["extra"] = {k: json.dumps(v, ensure_ascii=False) for k, v in t["extra"].items()}
            api.write("POST", "/filament", body)
        print("  ok", desc)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
