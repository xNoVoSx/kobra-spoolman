"""Spuel-Modell der ACE (purge.py) gegen die Messungen aus docs/findings.md."""

from __future__ import annotations

import pytest

from acebridge.purge import (AREA_175, DEFAULT_FIRST_LOAD_MM, PurgeModel, change_mm, firmware_volume,
                             orca_colour_volume)

LAV, MAG = "685BC7", "EC008C"
BLACK, WHITE, GREEN = "212721", "EFF0F1", "52D2BC"
FW = {"flush_multiplier": 1.0, "flush_volume_min": 107.0, "flush_volume_max": 800.0}


def test_orca_formula_matches_anycubic_values():
    # AnycubicSlicer automatisch: Orca-Formel + 107 (gleiche Werte wie im project_info-Kopf)
    assert int(firmware_volume(LAV, MAG, FW)) == 312
    assert int(firmware_volume(MAG, LAV, FW)) == 381
    assert int(firmware_volume(BLACK, WHITE, FW)) == 587
    assert int(firmware_volume(WHITE, BLACK, FW)) == 173
    assert orca_colour_volume(WHITE, "#zzzzzz") is None
    assert orca_colour_volume(LAV, LAV) == 60.0          # gleiche Farbe: Orcas Untergrenze


def test_limits_apply_before_the_multiplier():
    # Schwarz -> Weiss bei 1,5: 882 mm3, gemessen 363,9 mm pro Laden - also nicht auf 800 gekappt
    fw = {**FW, "flush_multiplier": 1.5}
    assert change_mm(BLACK, WHITE, fw, 0.0) == pytest.approx(882 / AREA_175, abs=1)
    assert change_mm(BLACK, WHITE, fw, -3.0) == pytest.approx(363.9, abs=1)
    # Grenzen gelten fuer das Farbvolumen selbst
    assert firmware_volume(BLACK, WHITE, {**FW, "flush_volume_max": 500.0}) == 500.0


def test_cube_tests_fit_the_model():
    # Unterschied 1,5 -> 1,0 pro Schicht: gemessen 66 / 78 mm
    for src, dst, measured in ((LAV, MAG, 66), (MAG, LAV, 78)):
        diff = change_mm(src, dst, {**FW, "flush_multiplier": 1.5}, 0) - change_mm(src, dst, FW, 0)
        assert diff == pytest.approx(measured, abs=2)


def color_pla_job():
    """Der Orca-Druck vom 24.09. (color_PLA_0.2_2h55m), Multiplikator 1,5."""
    return {"state": "complete", "slicer": "OrcaSlicer",
            "flush": {**FW, "flush_multiplier": 1.5},
            "slots": [{"slot": 1, "overhead_mm": 94.6}, {"slot": 2, "overhead_mm": 6186.1},
                      {"slot": 4, "overhead_mm": 1907.0}],
            "transitions": [
                {"from_slot": None, "to_slot": 1, "from_color": None, "to_color": GREEN, "count": 1},
                {"from_slot": 1, "to_slot": 4, "from_color": GREEN, "to_color": BLACK, "count": 1},
                {"from_slot": 4, "to_slot": 2, "from_color": BLACK, "to_color": WHITE, "count": 17},
                {"from_slot": 2, "to_slot": 4, "from_color": WHITE, "to_color": BLACK, "count": 17}]}


def test_learns_offset_and_first_load_from_orca_prints():
    m = PurgeModel()
    m.learn([color_pla_job()])
    assert m.learned_from == 1
    assert m.offset_mm == pytest.approx(-3.4, abs=0.3)
    assert m.first_load_mm == pytest.approx(94.6, abs=0.5)
    # Vorhersage mit den gelernten Werten trifft die Messung
    m.flush = {**FW, "flush_multiplier": 1.5}
    pred = m.predict(color_pla_job()["transitions"])
    assert pred[2] == pytest.approx(6186, rel=0.01) and pred[4] == pytest.approx(1907, rel=0.03)


def test_learning_ignores_anycubic_files_and_unknown_settings():
    m = PurgeModel()
    anycubic = {**color_pla_job(), "slicer": "AnycubicSlicer"}
    no_flush = {**color_pla_job(), "flush": None}
    old = {k: v for k, v in color_pla_job().items() if k != "transitions"}
    m.learn([anycubic, no_flush, old, {**color_pla_job(), "state": "cancelled"}])
    assert m.learned_from == 0 and m.offset_mm == -3.0 and m.first_load_mm == DEFAULT_FIRST_LOAD_MM


def test_flush_config_from_printer():
    m = PurgeModel(clock=lambda: 1000.0)
    assert m.config_due() and m.state()["flush_source"] == "default"
    m.set_flush_config({"auto_refill": 1, "flush_multiplier": 1, "flush_volume_max": 800, "flush_volume_min": 107})
    assert not m.config_due() and m.state()["flush_multiplier"] == 1.0
    m.set_flush_config({"flush_multiplier": "kaputt"})          # bleibt beim letzten guten Stand
    assert m.flush["flush_multiplier"] == 1.0
