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
    assert sp.resolve("Does not exist") is None


def test_build_profile_json(ks, system):
    base = ks.SystemProfiles(system / "system").resolve("Test PLA @Printer")
    prof = {"orca_id": "SM000010", "filament_id": 10, "values": {
        "nozzle_temperature": 230, "activate_air_filtration": True, "filament_flow_ratio": 0.96,
        "default_filament_colour": "#52D2BC", "filament_id": "SM000010", "slow_down_layer_time": "8"}}
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
    assert out["default_filament_colour"] == ["#52D2BC"] and "filament_colour" not in out


def test_colour_from_older_bridge_becomes_default_filament_colour(ks, system):
    base = ks.SystemProfiles(system / "system").resolve("Test PLA @Printer")
    base = dict(base, filament_colour=["#000000"], default_filament_colour=[""])
    prof = {"orca_id": "SM000010", "filament_id": 10, "values": {"filament_colour": "#52D2BC"}}
    out = ks.build_profile_json(base, prof, "X (SM000010)")
    assert out["default_filament_colour"] == ["#52D2BC"] and "filament_colour" not in out
    # neue Bridge gewinnt, falls beide Schluessel kommen
    prof["values"]["default_filament_colour"] = "#112233"
    assert ks.build_profile_json(base, prof, "X (SM000010)")["default_filament_colour"] == ["#112233"]


def test_diff_ignores_meta_and_formatting(ks):
    written = {"name": "A", "version": "1", "nozzle_temperature": ["230"], "filament_flow_ratio": ["0.960"],
               "fan_max_speed": ["100"]}
    saved = {"name": "A", "version": "2", "nozzle_temperature": ["235"], "filament_flow_ratio": ["0.96"],
             "fan_max_speed": ["80"]}
    assert ks.diff_profiles(written, saved) == {"nozzle_temperature": "235", "fan_max_speed": "80"}


def test_diff_ignores_orca_defaults_and_variant_expansion(ks):
    """Orca 2.5 fuegt beim Speichern eigene Standardwerte hinzu und fuellt Werte je Extruder-Variante (6x) auf -
    beides ist keine Aenderung des Nutzers (Fehler 05.10.: ~97 Werte landeten als Text in orca_overrides)."""
    written = {"name": "A", "nozzle_temperature": ["260"], "activate_air_filtration": ["1"],
               "filament_extruder_variant": ["Direct Drive Standard"]}
    saved = {"name": "A", "nozzle_temperature": ["260", "260", "260", "260", "260", "260"],
             "activate_air_filtration": ["1"] * 6,
             "filament_extruder_variant": ["Direct Drive Standard", "Direct Drive High Flow"],
             "activate_chamber_temp_control": ["0"], "filament_cooling_moves": ["4"],
             "adaptive_pressure_advance": ["0"] * 6}
    assert ks.diff_profiles(written, saved) == {}
    saved["nozzle_temperature"] = ["265"] * 6                       # echte Aenderung, je Variante gleich
    assert ks.diff_profiles(written, saved) == {"nozzle_temperature": "265"}
    # Orca aendert in der Oberflaeche nur die aktive Variante -> deren Wert zaehlt (Fehler 06.10.: Liste als Text
    # kam bei der Bridge als "kein Wert" an und loeschte die Duesentemperatur in Spoolman)
    saved["filament_extruder_variant"] = ["Direct Drive Standard", "Direct Drive High Flow", "Bowden Standard"]
    saved["nozzle_temperature"] = ["255", "260", "260"]
    assert ks.diff_profiles(written, saved) == {"nozzle_temperature": "255"}
    saved["filament_extruder_variant"] = ["Bowden Standard", "Direct Drive Standard", "Direct Drive High Flow"]
    saved["nozzle_temperature"] = ["260", "250", "260"]
    assert ks.diff_profiles(written, saved) == {"nozzle_temperature": "250"}
    saved["nozzle_temperature"] = ["250", "260", "260"]        # nur eine andere Variante geaendert -> nichts
    assert ks.diff_profiles(written, saved) == {}


def test_build_profile_json_turns_list_text_back_into_list(ks, system):
    """Alter, kaputter Stand in Spoolman: Listen als Text -> im Profil muss eine echte Liste stehen,
    sonst verwirft Orca das ganze Profil (\"Invalid value provided for parameter ...\")."""
    base = ks.SystemProfiles(system / "system").resolve("Test PLA @Printer")
    prof = {"orca_id": "SM000014", "filament_id": 14, "values": {
        "activate_air_filtration_during_print": '["1", "1", "1", "1", "1", "1"]',
        "adaptive_pressure_advance_model": '["0,0,0\\n0,0,0", "0,0,0\\n0,0,0"]',
        "nozzle_temperature": 260}}
    out = ks.build_profile_json(base, prof, "eSUN ASA+ Grau (SM000014)")
    assert out["activate_air_filtration_during_print"] == ["1"] * 6
    assert out["adaptive_pressure_advance_model"] == ["0,0,0\n0,0,0", "0,0,0\n0,0,0"]
    assert out["nozzle_temperature"] == ["260"]
    json.dumps(out)                                                  # als Datei schreibbar


def test_safe_name_avoids_sandbox_keywords(ks):
    assert ks.safe_name("Confetti PLA", "SM000001", "PLA") == "Spoolman PLA (SM000001)"
    assert ks.safe_name("A/B:C", "SM000002", "PLA") == "A B C (SM000002)"


def test_base_profile_names_skip_abstract_parents(ks, system, monkeypatch):
    monkeypatch.setenv("APPDIR", str(system / "appdir"))
    names = ks.SystemProfiles(system / "system").names()
    assert "Test PLA @Printer" in names and "Generic PETG @System" in names
    assert not any(n.startswith("fdm_") for n in names)


def test_diff_self_compare_with_differing_variant_lists(ks):
    """Issue #2 (MineTech13): Listen mit verschiedenen Werten je Variante - beide Seiten auf die aktive Variante
    reduzieren, sonst meldet sogar der Vergleich einer Datei mit sich selbst Aenderungen (Sync schreibt jedes Mal)."""
    prof = {"name": "Bambu PLA Basic", "filament_extruder_variant": ["Direct Drive Standard", "Direct Drive High Flow",
                                                                    "Bowden Standard"],
            "filament_max_volumetric_speed": ["12", "21", "40"], "filament_flow_ratio": ["0.98", "0.985", "0.985"]}
    assert ks.diff_profiles(prof, prof) == {}
    edited = dict(prof, filament_flow_ratio=["0.95", "0.985", "0.985"])       # aktive Variante geaendert
    assert ks.diff_profiles(prof, edited) == {"filament_flow_ratio": "0.95"}
    other = dict(prof, filament_flow_ratio=["0.98", "0.9", "0.985"])          # andere Variante: zaehlt nicht
    assert ks.diff_profiles(prof, other) == {}


def test_resolve_ignores_case_and_optional_system_suffix(ks, system, monkeypatch):
    """Issue #1: "eSun PLA+" / "generic petg" finden "eSUN PLA+ @System" / "Generic PETG @System"."""
    monkeypatch.setenv("APPDIR", str(system / "appdir"))
    lib = system / "appdir" / "resources" / "profiles" / "OrcaFilamentLibrary" / "filament"
    write(lib / "eSUN PLA+ @System.json", {"name": "eSUN PLA+ @System", "inherits": "fdm_filament_pet"})
    sp = ks.SystemProfiles(system / "system")
    for name in ("Generic PETG", "generic petg @system", "Generic  PETG @System"):
        assert sp.resolve(name)["name"] == "Generic PETG @System", name
    assert sp.resolve("eSun PLA+")["name"] == "eSUN PLA+ @System"
    assert sp.resolve("Generic PETG @base") is None


def test_fallback_base(ks):
    assert ks.fallback_base({"values": {"filament_type": "PETG"}, "material": "PETG+"}) == "Generic PETG @System"
    assert ks.fallback_base({"values": {}, "material": "PLA"}) == "Generic PLA @System"
    assert ks.fallback_base({"values": {}, "material": ""}) is None


@pytest.fixture
def core(ks, system, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDIR", str(system / "appdir"))
    monkeypatch.setattr(ks, "DEVICE_FILE", tmp_path / "kobra_device.json")
    monkeypatch.setattr(ks, "STATE_FILE", tmp_path / "kobra_state.json")
    monkeypatch.setattr(ks, "WRITTEN_DIR", tmp_path / "written")
    c = ks.Core(lambda: json.dumps({"bridge_url": "http://bridge.invalid/"}))
    c.system = ks.SystemProfiles(system / "system")
    monkeypatch.setattr(c, "user_filament_dir", lambda: tmp_path / "user" / "filament")
    monkeypatch.setattr(c, "_report_bases", lambda: None)
    return c


def profile(oid, base, material, ftype=None):
    return {"orca_id": oid, "filament_id": int(oid[-1]), "display_name": f"Test {material or '?'}", "name": "x",
            "material": material, "base": base, "hash": oid,
            "values": {"filament_type": ftype} if ftype else {}}


def test_sync_falls_back_to_generic_and_explains_missing_base(ks, core, monkeypatch):
    """Issue #1: ohne Basisprofil in Spoolman (alte Bridge 2.x liefert base leer) -> Generic <Typ> @System; ohne
    Material eine klare Meldung statt „–“ nicht gefunden."""
    profs = [profile("SM000001", None, "PETG", "PETG"), profile("SM000002", None, ""),
             profile("SM000003", "Does not exist", "PLA")]
    monkeypatch.setattr(core, "http", lambda *a, **k: {"profiles": profs, "hash": "h"})
    res = core.sync_profiles()
    assert len(res["written"]) == 1
    errs = " | ".join(res["errors"])
    assert "no Orca base profile in Spoolman" in errs and "“Does not exist” not found in Orca" in errs
    assert "„–“" not in errs
    assert core.missing_bases == {"Does not exist"}
    # zweiter Sync: nichts neu geschrieben (Issue #2: kein Neuschreiben bei jedem Start)
    assert core.sync_profiles()["written"] == []
