"""Verbrauchsvorschau im Orca-Plugin: Slice-Statistik + gemessenes Spuelen gegen das Restgewicht."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent / "fake_orca"))

AREA = 3.141592653589793 * 0.875**2   # mm2 bei 1,75 mm


@pytest.fixture(scope="module")
def ks():
    spec = importlib.util.spec_from_file_location("kobra_spoolman_fc", ROOT / "orca-plugin" / "kobra_spoolman.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fil(index, model_mm, flush_mm=0.0, tower_mm=0.0, density=1.24):
    """Ein Eintrag wie von orca.host.slice_statistics(), Laengen in mm Filament."""
    total = model_mm + flush_mm + tower_mm
    return {"index": index, "model_mm3": model_mm * AREA, "support_mm3": 0.0, "tower_mm3": tower_mm * AREA,
            "flush_mm3": flush_mm * AREA, "total_mm3": total * AREA, "diameter": 1.75, "density": density}


def slots(*remaining):
    return [{"slot": i + 1, "spool_id": 10 + i if r is not False else None, "name": f"Spule {i + 1}",
             "remaining_weight": None if r is False else r} for i, r in enumerate(remaining)]


def grams(mm, density=1.24):
    return mm * AREA * density / 1000


def test_two_colour_print_uses_measured_purge(ks):
    # Klingen-Druck: Griff gruen (Slot 1), Klingen weiss (Slot 2), ein Wechsel
    stats = {"plate_index": 0, "total_filament_changes": 1, "filaments": [fil(0, 4830), fil(1, 2660)]}
    fc = ks.build_forecast(stats, slots(500, 800), {"jobs": 1, "overhead_per_load_mm": 323.0})
    assert fc["loads"] == 2 and fc["purge_measured"]
    r1, r2 = fc["rows"]
    assert r1["slot"] == 1 and r2["slot"] == 2
    assert r1["orca_g"] == pytest.approx(grams(4830), abs=0.05)
    assert r1["purge_g"] == pytest.approx(grams(323), abs=0.05)
    assert r1["need_g"] == pytest.approx(grams(4830 + 323), abs=0.1)
    assert r2["need_g"] == pytest.approx(grams(2660 + 323), abs=0.1)
    assert {r1["status"], r2["status"]} == {"ok"}
    assert fc["short"] == [] and fc["tight"] == []


def test_short_and_tight(ks):
    stats = {"total_filament_changes": 0, "filaments": [fil(0, 10000), fil(2, 3000)]}
    need0 = grams(10000 + ks.DEFAULT_PURGE_PER_LOAD_MM)
    need2 = grams(3000 + ks.DEFAULT_PURGE_PER_LOAD_MM)
    fc = ks.build_forecast(stats, slots(need0 - 1, 999, need2 + 2), {"jobs": 0}, reserve_g=5)
    assert not fc["purge_measured"]
    assert fc["loads"] == 2                    # jedes benutzte Filament wird mindestens einmal geladen
    by = {r["slot"]: r for r in fc["rows"]}
    assert by[1]["status"] == "short" and by[3]["status"] == "tight"
    assert fc["short"] == [1] and fc["tight"] == [3]
    w = ks.forecast_warnings(fc)
    assert w[0].startswith("Slot 1: braucht ca.") and "knapp" in w[1]


def test_many_changes_are_spread_evenly(ks):
    # 2 Farben, abwechselnd pro Schicht: 9 Wechsel = 10 Ladevorgaenge, je 5
    stats = {"total_filament_changes": 9, "filaments": [fil(0, 1000), fil(1, 1000)]}
    fc = ks.build_forecast(stats, slots(900, 900), {"jobs": 3, "overhead_per_load_mm": 200})
    assert fc["loads"] == 10
    assert [r["loads"] for r in fc["rows"]] == [5, 5]
    assert fc["rows"][0]["purge_g"] == pytest.approx(grams(1000), abs=0.05)


def test_orca_flush_and_tower_are_included(ks):
    stats = {"total_filament_changes": 1, "filaments": [fil(0, 1000, flush_mm=150, tower_mm=50), fil(1, 500)]}
    fc = ks.build_forecast(stats, slots(900, 900), {"jobs": 1, "overhead_per_load_mm": 0})
    r = fc["rows"][0]
    assert r["flush_g"] == pytest.approx(grams(150), abs=0.05)
    assert r["tower_g"] == pytest.approx(grams(50), abs=0.05)
    assert r["need_g"] == pytest.approx(grams(1200), abs=0.05)


def test_unused_slots_missing_spool_and_extra_filament(ks):
    stats = {"total_filament_changes": 2, "filaments": [fil(0, 0), fil(1, 100), fil(4, 100)]}
    fc = ks.build_forecast(stats, slots(100, False, 100, 100), None)
    by = {r["slot"]: r for r in fc["rows"]}
    assert 1 not in by                           # Filament 1 nicht benutzt
    assert by[2]["status"] == "nospool"
    assert by[5]["status"] == "noslot"
    assert len(ks.forecast_warnings(fc)) == 2


def test_density_from_orca_profile(ks):
    stats = {"total_filament_changes": 0, "filaments": [fil(0, 1000, density=1.04)]}
    fc = ks.build_forecast(stats, slots(900), {"jobs": 1, "overhead_per_load_mm": 100})
    assert fc["rows"][0]["need_g"] == pytest.approx(grams(1100, 1.04), abs=0.05)


def test_without_patch_there_is_no_preview(ks):
    assert not hasattr(ks.orca.host, "slice_statistics")
    assert ks.read_slice_statistics() is None
