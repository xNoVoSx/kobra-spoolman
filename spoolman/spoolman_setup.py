#!/usr/bin/env python3
"""
Spoolman-Setup fuer das Kobra-S1-Projekt (ace-lane-bridge / Orca-Plugin).

Legt per Spoolman-API an:
  * Zusatzfelder fuer Filamente (Orca-Einstellungen) und Spulen (NFC-Kennung)
  * den Hersteller "Vorlage" mit sieben Materialvorlagen
    (Startwerte aus den Orca-Generic-Profilen, Stand OrcaSlicer main 2026-09)

Das Skript legt nur NEU an. Vorhandene Felder, Hersteller und Filamente
werden nicht veraendert und nichts wird geloescht. Mehrfaches Ausfuehren ist
unkritisch.

Aufruf:
  python3 spoolman_setup.py                 # zeigt Plan, fragt nach
  python3 spoolman_setup.py --dry-run       # nur anzeigen
  python3 spoolman_setup.py --yes           # ohne Rueckfrage
  python3 spoolman_setup.py --url http://<spoolman-host>:7912

Nur Python-Standardbibliothek, getestet gegen Spoolman 0.26.1.
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
# Zusatzfelder. WICHTIG: keine default_value setzen, sonst bekommt jedes neue
# Filament den Wert eingetragen und die Vererbung (leer = von Vorlage/Orca)
# waere kaputt.
# key -> (Name, Typ, Einheit, Reihenfolge)  |  Kommentar = Orca-Schluessel
# ---------------------------------------------------------------------------
FILAMENT_FIELDS = [
    ("orca_basis",                  "Orca-Basisprofil",               "text",    None,       1),   # Name des Orca-Systemprofils
    ("vorlage",                     "Vorlage",                        "choice",  None,       2),   # leer = automatisch nach Material
    ("nozzle_temp_first_layer",     "Düse erste Schicht",             "integer", "°C",       10),  # nozzle_temperature_initial_layer
    ("bed_temp_first_layer",        "Bett erste Schicht",             "integer", "°C",       11),  # textured_plate_temp_initial_layer
    ("bed_temp_smooth",             "Bett glatte PEI",                "integer", "°C",       12),  # hot_plate_temp
    ("bed_temp_smooth_first_layer", "Bett glatte PEI erste Schicht",  "integer", "°C",       13),  # hot_plate_temp_initial_layer
    ("chamber_temp",                "Kammertemperatur",               "integer", "°C",       14),  # chamber_temperature
    ("fan_min",                     "Bauteillüfter min",              "integer", "%",        20),  # fan_min_speed
    ("fan_max",                     "Bauteillüfter max",              "integer", "%",        21),  # fan_max_speed
    ("fan_off_first_layers",        "Lüfter aus erste Schichten",     "integer", "Schichten",22),  # close_fan_the_first_x_layers
    ("overhang_fan",                "Überhang-Lüfter",                "integer", "%",        23),  # overhang_fan_speed
    ("aux_fan",                     "Hilfslüfter",                    "integer", "%",        24),  # additional_cooling_fan_speed
    ("air_filtration",              "Luftfilterung (Abluft)",         "boolean", None,       30),  # activate_air_filtration
    ("exhaust_fan_print",           "Abluft während Druck",           "integer", "%",        31),  # during_print_exhaust_fan_speed
    ("exhaust_fan_done",            "Abluft nach Druck",              "integer", "%",        32),  # complete_print_exhaust_fan_speed
    ("flow_ratio",                  "Flow Ratio",                     "float",   None,       40),  # filament_flow_ratio
    ("pressure_advance",            "Pressure Advance",               "float",   None,       41),  # pressure_advance (+enable)
    ("max_volumetric_speed",        "Max. Volumenstrom",              "float",   "mm³/s",    42),  # filament_max_volumetric_speed
    ("retraction_length",           "Retraction Länge",               "float",   "mm",       50),  # filament_retraction_length
    ("retraction_speed",            "Retraction Geschwindigkeit",     "integer", "mm/s",     51),  # filament_retraction_speed
    ("z_hop",                       "Z-Hop",                          "float",   "mm",       52),  # filament_z_hop
    ("orca_overrides",              "Orca-Overrides",                 "text",    None,       90),  # "schluessel = wert" je Zeile
]

SPOOL_FIELDS = [
    ("nfc_uid",                     "NFC-Kennung",                    "text",    None,       10),  # setzt die Bridge beim Pairing
]

VENDOR_NAME = "Vorlage"

TEMPLATES = [
    {
        "name": "Vorlage PLA",
        "material": "PLA",
        "density": 1.24,
        "diameter": 1.75,
        "settings_extruder_temp": 220,
        "settings_bed_temp": 55,
        "extra": {
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
        "name": "Vorlage PLA Silk",
        "material": "PLA",
        "density": 1.24,
        "diameter": 1.75,
        "settings_extruder_temp": 220,
        "settings_bed_temp": 55,
        "extra": {
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
        "name": "Vorlage PETG",
        "material": "PETG",
        "density": 1.27,
        "diameter": 1.75,
        "settings_extruder_temp": 255,
        "settings_bed_temp": 80,
        "extra": {
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
        "name": "Vorlage ASA",
        "material": "ASA",
        "density": 1.04,
        "diameter": 1.75,
        "settings_extruder_temp": 260,
        "settings_bed_temp": 100,
        "extra": {
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
        "name": "Vorlage TPU",
        "material": "TPU",
        "density": 1.24,
        "diameter": 1.75,
        "settings_extruder_temp": 240,
        "settings_bed_temp": 35,
        "extra": {
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
        "name": "Vorlage PLA-CF",
        "material": "PLA-CF",
        "density": 1.24,
        "diameter": 1.75,
        "settings_extruder_temp": 220,
        "settings_bed_temp": 55,
        "extra": {
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
        "name": "Vorlage PETG-CF",
        "material": "PETG-CF",
        "density": 1.27,
        "diameter": 1.75,
        "settings_extruder_temp": 255,
        "settings_bed_temp": 80,
        "extra": {
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
            raise SystemExit(f"FEHLER {method} {path}: HTTP {e.code}\n{detail}") from None
        except urllib.error.URLError as e:
            raise SystemExit(f"FEHLER: Spoolman unter {self.base} nicht erreichbar ({e.reason})") from None

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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=DEFAULT_URL, help=f"Spoolman-URL (Standard: {DEFAULT_URL})")
    ap.add_argument("--dry-run", action="store_true", help="nur anzeigen, nichts schreiben")
    ap.add_argument("--yes", "-y", action="store_true", help="ohne Rueckfrage ausfuehren")
    args = ap.parse_args()

    api = Api(args.url, args.dry_run)
    info = api.get("/info")
    print(f"Spoolman {info.get('version')} unter {args.url}  (automatische Backups: {info.get('automatic_backups')})")

    template_names = [t["name"] for t in TEMPLATES]
    plan = []  # (beschreibung, callable)

    # --- Zusatzfelder -------------------------------------------------------
    for entity, fields in (("filament", FILAMENT_FIELDS), ("spool", SPOOL_FIELDS)):
        existing = {f["key"]: f for f in api.get(f"/field/{entity}")}
        for key, name, ftype, unit, order in fields:
            choices = template_names if key == "vorlage" else None
            if key in existing:
                ex = existing[key]
                if ex["field_type"] != ftype:
                    print(f"  WARNUNG: Feld {entity}.{key} existiert mit Typ {ex['field_type']} (erwartet {ftype}) - bleibt unveraendert")
                    continue
                if key == "vorlage":
                    missing = [c for c in template_names if c not in (ex.get("choices") or [])]
                    if missing:
                        new_choices = list(ex.get("choices") or []) + missing
                        body = field_body(ex["name"], ftype, ex.get("unit"), ex.get("order", order), new_choices)
                        plan.append((f"Feld {entity}.{key}: Auswahl ergaenzen um {missing}",
                                     lambda e=entity, k=key, b=body: api.write("POST", f"/field/{e}/{k}", b)))
                continue
            body = field_body(name, ftype, unit, order, choices)
            plan.append((f"Feld {entity}.{key} anlegen ({name}, {ftype}{', ' + unit if unit else ''})",
                         lambda e=entity, k=key, b=body: api.write("POST", f"/field/{e}/{k}", b)))

    # --- Hersteller + Vorlagen ----------------------------------------------
    vendors = [v for v in api.get("/vendor") if v.get("name") == VENDOR_NAME]
    vendor_id = vendors[0]["id"] if vendors else None
    existing_names = set()
    if vendor_id is not None:
        existing_names = {f.get("name") for f in api.get("/filament", {"vendor.id": vendor_id})}
    else:
        plan.append((f"Hersteller '{VENDOR_NAME}' anlegen", None))  # wird unten gesondert behandelt

    for t in TEMPLATES:
        if t["name"] in existing_names:
            continue
        plan.append((f"Filament '{t['name']}' anlegen (Basis {t['extra']['orca_basis']})", t))

    if not plan:
        print("Alles schon vorhanden - nichts zu tun.")
        return 0

    print("\nGeplante Aenderungen:")
    for desc, _ in plan:
        print("  +", desc)
    if args.dry_run:
        print("\n--dry-run: nichts geschrieben.")
        return 0
    if not args.yes:
        if input("\nAusfuehren? [j/N] ").strip().lower() not in ("j", "ja", "y", "yes"):
            print("Abgebrochen.")
            return 1

    for desc, action in plan:
        if callable(action):
            action()
        elif action is None:  # Hersteller
            vendor_id = api.write("POST", "/vendor", {"name": VENDOR_NAME,
                                  "comment": "Materialvorlagen fuer das Orca-Plugin - nicht als echte Spulen verwenden"})["id"]
        else:  # Vorlage
            t = action
            body = {k: v for k, v in t.items() if k != "extra"}
            body["vendor_id"] = vendor_id
            body["comment"] = "Materialvorlage. Leere Felder erben vom Orca-Basisprofil."
            body["extra"] = {k: json.dumps(v, ensure_ascii=False) for k, v in t["extra"].items()}
            api.write("POST", "/filament", body)
        print("  ok", desc)

    print("\nFertig.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
