"""Profilbau im Orca-Plugin: Vererbung aufloesen, Spoolman-Werte einsetzen, Aenderungen erkennen."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent / "fake_orca"))


@pytest.fixture(scope="module")
def ks():
    spec = importlib.util.spec_from_file_location("kobra_spoolman", ROOT / "orca-plugin" / "kobra_spoolman.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def system(tmp_path):
    """Kleine, erfundene Profilwelt im Orca-Format (zwei Hersteller mit gleich benannten Basen)."""
    v = tmp_path / "system" / "TestVendor" / "filament"
    write(v / "fdm_filament_common.json", {"name": "fdm_filament_common", "filament_start_gcode": ["; start\n"],
                                           "fan_max_speed": ["100"], "filament_notes": [""]})
    write(v / "fdm_filament_pla.json", {"name": "fdm_filament_pla", "inherits": "fdm_filament_common",
                                        "nozzle_temperature": ["210"], "filament_type": ["PLA"]})
    write(v / "fdm_filament_pet.json", {"name": "fdm_filament_pet", "inherits": "fdm_filament_common",
                                        "nozzle_temperature": ["999"]})   # darf NICHT fuer Generic PETG gelten
    write(v / "Test PLA @Printer.json", {"name": "Test PLA @Printer", "inherits": "fdm_filament_pla",
                                         "setting_id": "X1", "filament_id": "ORIG", "additional_cooling_fan_speed": ["60"],
                                         "compatible_printers": ["Printer"], "version": "2.5.0.0"})
    lib = tmp_path / "appdir" / "resources" / "profiles" / "OrcaFilamentLibrary" / "filament"
    write(lib / "base" / "fdm_filament_common.json", {"name": "fdm_filament_common", "fan_max_speed": ["90"]})
    write(lib / "base" / "fdm_filament_pet.json", {"name": "fdm_filament_pet", "inherits": "fdm_filament_common",
                                                   "nozzle_temperature": ["255"], "filament_type": ["PETG"]})
    write(lib / "Generic PETG @System.json", {"name": "Generic PETG @System", "inherits": "fdm_filament_pet"})
    return tmp_path


def test_resolve_prefers_parents_of_the_same_vendor(ks, system, monkeypatch):
    monkeypatch.setenv("APPDIR", str(system / "appdir"))
    sp = ks.SystemProfiles(system / "system")
    pla = sp.resolve("Test PLA @Printer")
    assert pla["nozzle_temperature"] == ["210"] and pla["fan_max_speed"] == ["100"]
    petg = sp.resolve("Generic PETG @System")          # nur im AppImage-Ordner vorhanden
    assert petg["nozzle_temperature"] == ["255"] and petg["fan_max_speed"] == ["90"]
    assert sp.resolve("Gibt es nicht") is None


def test_build_profile_json(ks, system):
    base = ks.SystemProfiles(system / "system").resolve("Test PLA @Printer")
    prof = {"orca_id": "SM000010", "filament_id": 10, "values": {
        "nozzle_temperature": 230, "activate_air_filtration": True, "filament_flow_ratio": 0.96,
        "filament_colour": "#52D2BC", "filament_id": "SM000010", "slow_down_layer_time": "8"}}
    name = ks.safe_name("Anycubic PLA Silk Grün", "SM000010", "PLA")
    out = ks.build_profile_json(base, prof, name)
    assert name == "Anycubic PLA Silk Grün (SM000010)"
    assert out["name"] == name and out["inherits"] == "" and out["from"] == "User"
    assert out["filament_id"] == "SM000010" and out["filament_settings_id"] == [name]
    assert out["nozzle_temperature"] == ["230"] and out["activate_air_filtration"] == ["1"]
    assert out["filament_flow_ratio"] == ["0.96"] and out["slow_down_layer_time"] == ["8"]
    assert out["additional_cooling_fan_speed"] == ["60"]          # aus dem Basisprofil
    assert out["compatible_printers"] == [] and "setting_id" not in out
    assert ks.MARKER in out["filament_notes"][0]


def test_diff_ignores_meta_and_formatting(ks):
    written = {"name": "A", "version": "1", "nozzle_temperature": ["230"], "filament_flow_ratio": ["0.960"]}
    saved = {"name": "A", "version": "2", "nozzle_temperature": ["235"], "filament_flow_ratio": ["0.96"],
             "fan_max_speed": ["80"]}
    assert ks.diff_profiles(written, saved) == {"nozzle_temperature": "235", "fan_max_speed": "80"}


def test_safe_name_avoids_sandbox_keywords(ks):
    assert ks.safe_name("Confetti PLA", "SM000001", "PLA") == "Spoolman PLA (SM000001)"
    assert ks.safe_name("A/B:C", "SM000002", "PLA") == "A B C (SM000002)"
