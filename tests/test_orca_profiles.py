"""Spoolman -> Orca-Werte und Ruecksync Orca -> Spoolman."""

from __future__ import annotations

import json

from acebridge.orca_profiles import backsync_patch, build_profile, parse_overrides, reset_patch
from acebridge.slots import base_type


def ext(**kw):
    return {k: json.dumps(v) for k, v in kw.items()}


TEMPLATE = {"id": 1, "name": "Vorlage PETG", "material": "PETG", "vendor": {"name": "Vorlage"},
            "settings_extruder_temp": 255, "settings_bed_temp": 80,
            "extra": ext(orca_basis="Generic PETG @System", fan_min=20, fan_max=100, air_filtration=False,
                         orca_overrides="slow_down_layer_time = 8")}
FILAMENT = {"id": 8, "name": "PETG 2.0 Lavendel", "material": "PETG", "vendor": {"name": "Sunlu"},
            "color_hex": "685BC7", "density": 1.22, "diameter": 1.75, "weight": 1000, "price": 11.99,
            "settings_extruder_temp": 250, "settings_bed_temp": 75,
            "extra": ext(vorlage="Vorlage PETG", pressure_advance=0.05)}
SPOOLS = [{"id": 1, "location": "ACE Slot 2", "filament": {"id": 8}}]


def slot_of(loc):
    return int(loc.split()[-1]) if loc and loc.startswith("ACE Slot ") else None


def test_values_come_from_filament_then_template():
    p = build_profile(FILAMENT, [TEMPLATE], base_type, SPOOLS, slot_of)
    v, src = p["values"], p["sources"]
    assert p["orca_id"] == "SM000008" and p["base"] == "Generic PETG @System"
    assert v["nozzle_temperature"] == 250 and src["nozzle_temperature"] == "filament"
    assert v["fan_min_speed"] == 20 and src["fan_min_speed"] == "vorlage"
    assert v["activate_air_filtration"] is False
    assert v["pressure_advance"] == 0.05 and v["enable_pressure_advance"] is True
    assert v["filament_colour"] == "#685BC7" and v["filament_cost"] == 11.99
    assert v["slow_down_layer_time"] == "8" and src["slow_down_layer_time"] == "override-vorlage"
    assert p["spools"] == [{"id": 1, "remaining_weight": None, "slot": 2}]


def test_own_base_profile_replaces_template():
    fil = dict(FILAMENT, extra=ext(vorlage="Vorlage PETG", orca_basis="Sunlu PETG @System"))
    p = build_profile(fil, [TEMPLATE], base_type, SPOOLS, slot_of)
    assert p["base"] == "Sunlu PETG @System" and p["template"] is None
    assert "fan_min_speed" not in p["values"]


def test_backsync_maps_known_fields_and_keeps_the_rest_as_overrides():
    patch, applied, ignored = backsync_patch(FILAMENT, {
        "nozzle_temperature": "245", "fan_max_speed": "90", "activate_air_filtration": "1",
        "filament_colour": "#112233", "filament_cost": "24", "slow_down_layer_time": "6",
        "filament_id": "XYZ", "enable_pressure_advance": "0"})
    assert patch["settings_extruder_temp"] == 245
    assert patch["color_hex"] == "112233" and patch["price"] == 24.0
    assert patch["extra"]["fan_max"] == "90" and patch["extra"]["air_filtration"] == "true"
    assert patch["extra"]["pressure_advance"] is None
    assert parse_overrides(json.loads(patch["extra"]["orca_overrides"])) == {"slow_down_layer_time": "6"}
    assert "filament_id" in ignored and applied["nozzle_temperature"] == 245


def test_reset_clears_fields_so_template_applies_again():
    fil = dict(FILAMENT, extra=ext(fan_max=90, orca_overrides="a = 1\nb = 2"))
    patch, done = reset_patch(fil, ["fan_max_speed", "nozzle_temperature", "a"])
    assert patch["settings_extruder_temp"] is None and patch["extra"]["fan_max"] is None
    assert parse_overrides(json.loads(patch["extra"]["orca_overrides"])) == {"b": "2"}
    assert set(done) == {"fan_max_speed", "nozzle_temperature", "a"}
