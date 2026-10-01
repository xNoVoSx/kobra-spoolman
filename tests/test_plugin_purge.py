"""Spuelen pro Farbwechsel in der Verbrauchsvorschau des Plugins (gleiche Rechnung wie die Bridge)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from acebridge import purge as bridge_purge

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent / "fake_orca"))

AREA = 3.141592653589793 * 0.875**2
LAV, MAG, BLACK, WHITE = "685BC7", "EC008C", "212721", "EFF0F1"
MODEL = {"model": "colour", "flush_multiplier": 1.0, "flush_volume_min": 107.0, "flush_volume_max": 800.0,
         "offset_mm": -3.0, "first_load_mm": 95.0, "learned_from": 1}


@pytest.fixture(scope="module")
def ks():
    spec = importlib.util.spec_from_file_location("kobra_spoolman_purge", ROOT / "orca-plugin" / "kobra_spoolman.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fil(index, model_mm, loads=None):
    f = {"index": index, "model_mm3": model_mm * AREA, "support_mm3": 0.0, "tower_mm3": 0.0, "flush_mm3": 0.0,
         "total_mm3": model_mm * AREA, "diameter": 1.75, "density": 1.27}
    if loads is not None:
        f["loads"] = loads
    return f


def slot(n, colour, ace_colour=None, rest=900):
    return {"slot": n, "spool_id": n, "name": f"Spule {n}", "remaining_weight": rest, "color": colour,
            "ace_color": ace_colour, "present": True, "ace_material": "PETG"}


def g(mm):
    return mm * AREA * 1.27 / 1000


def test_plugin_and_bridge_compute_the_same(ks):
    flush = {"flush_multiplier": 1.5, "flush_volume_min": 107.0, "flush_volume_max": 800.0}
    for a, b in ((LAV, MAG), (MAG, LAV), (BLACK, WHITE), (WHITE, BLACK), ("52D2BC", BLACK), (LAV, LAV)):
        assert ks.orca_colour_volume(a, b) == pytest.approx(bridge_purge.orca_colour_volume(a, b))
        assert ks.purge_change_mm(a, b, flush, -3.0) == pytest.approx(bridge_purge.change_mm(a, b, flush, -3.0))


def test_cube_test_a_per_colour_change(ks):
    """Test A (01.10.): erst Magenta (Slot 2), dann 6 x Magenta -> Lavendel, 6 x Lavendel -> Magenta."""
    stats = {"plate_index": 0, "filaments": [fil(0, 450), fil(1, 742)],
             "transitions": [{"from": None, "to": 1, "count": 1}, {"from": 1, "to": 0, "count": 6},
                             {"from": 0, "to": 1, "count": 6}]}
    fc = ks.build_forecast(stats, [slot(1, LAV), slot(2, MAG)], {"jobs": 1, "model": MODEL})
    assert fc["purge_method"] == "transitions" and fc["loads"] == 13 and fc["loads_exact"]
    lav_change = 381 / AREA - 3          # Magenta -> Lavendel
    mag_change = 312 / AREA - 3          # Lavendel -> Magenta
    rows = {r["slot"]: r for r in fc["rows"]}
    assert rows[1]["purge_g"] == pytest.approx(g(6 * lav_change), abs=0.1)
    assert rows[2]["purge_g"] == pytest.approx(g(95 + 6 * mag_change), abs=0.1)
    # gegen die Messung: 2946 mm gesamt bei 1192 mm echter G-Code-Extrusion
    predicted = 1192 + 95 + 6 * lav_change + 6 * mag_change
    assert predicted == pytest.approx(2946, rel=0.02)
    assert "pro Farbwechsel" in ks.forecast_html(fc)


def test_ace_colour_wins_over_spoolman_colour(ks):
    stats = {"filaments": [fil(0, 100), fil(1, 100)],
             "transitions": [{"from": None, "to": 0, "count": 1}, {"from": 0, "to": 1, "count": 1}]}
    # Spoolman sagt Magenta, die ACE meldet Weiss - die Firmware rechnet mit Weiss
    fc = ks.build_forecast(stats, [slot(1, BLACK), slot(2, MAG, ace_colour=WHITE + "FF")], {"model": MODEL})
    expected = ks.purge_change_mm(BLACK, WHITE, MODEL, -3.0)
    assert {r["slot"]: r for r in fc["rows"]}[2]["purge_g"] == pytest.approx(g(expected), abs=0.1)


def test_older_orca_build_uses_colours_without_order(ks):
    stats = {"filaments": [fil(0, 450, loads=6), fil(1, 742, loads=7)], "total_filament_changes": 12}
    fc = ks.build_forecast(stats, [slot(1, LAV), slot(2, MAG)], {"model": MODEL})
    assert fc["purge_method"] == "colours"
    rows = {r["slot"]: r for r in fc["rows"]}
    # erster Ladevorgang je zur Haelfte, Rest mit dem Wechsel von der anderen Farbe
    assert rows[1]["purge_g"] == pytest.approx(g(0.5 * 95 + 5.5 * (381 / AREA - 3)), abs=0.1)
    assert rows[2]["purge_g"] == pytest.approx(g(0.5 * 95 + 6.5 * (312 / AREA - 3)), abs=0.1)
    assert "neueren orca-kobra-Build" in ks.forecast_html(fc)


def test_unknown_colour_and_old_bridge_fall_back(ks):
    stats = {"filaments": [fil(0, 100), fil(1, 100)],
             "transitions": [{"from": None, "to": 0, "count": 1}, {"from": 0, "to": 1, "count": 2}]}
    # Farbe fehlt -> gemessener Mittelwert pro Laden
    fc = ks.build_forecast(stats, [slot(1, LAV), slot(2, None)], {"jobs": 2, "overhead_per_load_mm": 150, "model": MODEL})
    assert {r["slot"]: r for r in fc["rows"]}[2]["purge_g"] == pytest.approx(g(2 * 150), abs=0.1)
    # Bridge ohne Modell -> wie bisher
    fc = ks.build_forecast(stats, [slot(1, LAV), slot(2, MAG)], {"jobs": 2, "overhead_per_load_mm": 150})
    assert fc["purge_method"] == "average"
    assert {r["slot"]: r for r in fc["rows"]}[2]["purge_g"] == pytest.approx(g(2 * 150), abs=0.1)
