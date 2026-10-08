"""Verbrauchsvorschau im Orca-Plugin: Orcas Slice-Statistik (inkl. Spuelen der ACE als "Gereinigt") gegen das
Restgewicht in Spoolman."""

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


def fil(index, model_mm, flush_mm=0.0, tower_mm=0.0, density=1.24, loads=None, total_mm=None):
    """Ein Eintrag wie von orca.host.slice_statistics(), Laengen in mm Filament."""
    total = model_mm + flush_mm + tower_mm if total_mm is None else total_mm
    f = {"index": index, "model_mm3": model_mm * AREA, "support_mm3": 0.0, "tower_mm3": tower_mm * AREA,
         "flush_mm3": flush_mm * AREA, "total_mm3": total * AREA, "diameter": 1.75, "density": density}
    if loads is not None:
        f["loads"] = loads
    return f


def slots(*remaining):
    return [{"slot": i + 1, "spool_id": 10 + i if r is not False else None, "name": f"Spule {i + 1}",
             "remaining_weight": None if r is False else r} for i, r in enumerate(remaining)]


def grams(mm, density=1.24):
    return mm * AREA * density / 1000


def test_purge_of_the_ace_comes_from_orca(ks):
    # Klingen-Druck: Griff gruen (Slot 1), Klingen weiss (Slot 2), ein Wechsel. Das Spuelen der ACE
    # (85 mm Laden + Matrix) meldet der Wechsel-G-Code Orca per EXTERNAL_PURGE -> steht unter flush_mm3
    stats = {"plate_index": 0, "filaments": [fil(0, 4830), fil(1, 2660, flush_mm=85 + 210)],
             "transitions": [{"from": None, "to": 0, "count": 1}, {"from": 0, "to": 1, "count": 1}]}
    fc = ks.build_forecast(stats, slots(500, 800))
    r1, r2 = fc["rows"]
    assert r1["slot"] == 1 and r2["slot"] == 2
    assert r1["need_g"] == pytest.approx(grams(4830), abs=0.1)
    assert r2["flush_g"] == pytest.approx(grams(295), abs=0.05)
    assert r2["need_g"] == pytest.approx(grams(2660 + 295), abs=0.1)
    assert [r1["loads"], r2["loads"]] == [1, 1] and fc["changes"] == 1 and fc["loads_exact"]
    assert not fc["purge_missing"] and {r1["status"], r2["status"]} == {"ok"}
    assert fc["total_g"] == pytest.approx(grams(4830 + 2660 + 295), abs=0.2)


def test_purge_missing_when_the_profile_does_not_report_it(ks):
    # altes Drucker-Profil ohne EXTERNAL_PURGE: Wechsel ja, "Gereinigt" leer -> Hinweis statt zu kleiner Zahl
    stats = {"filaments": [fil(0, 1000), fil(1, 1000)],
             "transitions": [{"from": None, "to": 0, "count": 1}, {"from": 0, "to": 1, "count": 4},
                             {"from": 1, "to": 0, "count": 4}]}
    fc = ks.build_forecast(stats, slots(900, 900))
    assert fc["purge_missing"] and fc["changes"] == 8
    assert [r["loads"] for r in fc["rows"]] == [5, 4]
    assert any("make-profile.py" in w for w in ks.forecast_warnings(fc))
    assert "fehlt" in ks.forecast_html(fc)
    single = ks.build_forecast({"filaments": [fil(0, 1000)], "transitions": [{"from": None, "to": 0, "count": 1}]},
                               slots(900))
    assert not single["purge_missing"]           # einfarbig: kein Wechsel, nichts zu spuelen


def test_short_and_tight(ks):
    stats = {"total_filament_changes": 0, "filaments": [fil(0, 10000), fil(2, 3000)]}
    fc = ks.build_forecast(stats, slots(grams(10000) - 1, 999, grams(3000) + 2), reserve_g=5)
    by = {r["slot"]: r for r in fc["rows"]}
    assert by[1]["status"] == "short" and by[3]["status"] == "tight"
    assert fc["short"] == [1] and fc["tight"] == [3]
    w = ks.forecast_warnings(fc)
    assert w[0].startswith("Slot 1: braucht ca.") and "knapp" in w[1]


def test_orca_flush_and_tower_are_included(ks):
    stats = {"total_filament_changes": 1, "filaments": [fil(0, 1000, flush_mm=150, tower_mm=50), fil(1, 500)]}
    fc = ks.build_forecast(stats, slots(900, 900))
    r = fc["rows"][0]
    assert r["flush_g"] == pytest.approx(grams(150), abs=0.05)
    assert r["tower_g"] == pytest.approx(grams(50), abs=0.05)
    assert r["need_g"] == pytest.approx(grams(1200), abs=0.05)
    assert not fc["loads_exact"] and fc["changes"] == 1


def test_unused_slots_missing_spool_and_extra_filament(ks):
    stats = {"total_filament_changes": 2, "filaments": [fil(0, 0), fil(1, 100, flush_mm=90), fil(4, 100)]}
    fc = ks.build_forecast(stats, slots(100, False, 100, 100))
    by = {r["slot"]: r for r in fc["rows"]}
    assert 1 not in by                           # Filament 1 nicht benutzt
    assert by[2]["status"] == "nospool"
    assert by[5]["status"] == "noslot"
    assert len(ks.forecast_warnings(fc)) == 2


def test_density_from_orca_profile(ks):
    stats = {"total_filament_changes": 0, "filaments": [fil(0, 1000, density=1.04)]}
    fc = ks.build_forecast(stats, slots(900))
    assert fc["rows"][0]["need_g"] == pytest.approx(grams(1000, 1.04), abs=0.05)


def test_orca_values_match_the_legend(ks):
    # Echter Fall (Eidechse, 24.09.): Orcas total_volumes_per_extruder verteilt den Turm anders als
    # die Legende. Angezeigt wird wie in der Legende: Gesamt = Modell + Stuetzen + Gereinigt + Turm.
    stats = {"total_filament_changes": 35, "filaments": [
        fil(0, 1400, total_mm=1480), fil(1, 130, tower_mm=520, total_mm=330), fil(3, 8660, tower_mm=310, total_mm=9180)]}
    fc = ks.build_forecast(stats, slots(580, 890, 600, 796))
    by = {r["slot"]: r for r in fc["rows"]}
    assert by[1]["orca_g"] == pytest.approx(grams(1400), abs=0.01)
    assert by[2]["orca_g"] == pytest.approx(grams(650), abs=0.01)
    assert by[2]["tower_g"] == pytest.approx(grams(520), abs=0.01)
    assert by[4]["orca_g"] == pytest.approx(grams(8970), abs=0.01)
    assert fc["total_g"] == pytest.approx(grams(1400 + 650 + 8970), abs=0.2)


def test_loads_from_older_patch_without_transitions(ks):
    stats = {"total_filament_changes": 35, "filaments": [
        fil(0, 1400, loads=18), fil(1, 130, loads=1), fil(3, 8660, loads=17)]}
    fc = ks.build_forecast(stats, slots(580, 890, 600, 796))
    assert [r["loads"] for r in fc["rows"]] == [18, 1, 17] and fc["changes"] == 35


def test_panel_html_uses_orca_terms(ks):
    stats = {"plate_index": 0, "filaments": [fil(0, 1400, tower_mm=10), fil(1, 30000, flush_mm=300)],
             "transitions": [{"from": None, "to": 0, "count": 1}, {"from": 0, "to": 1, "count": 1}]}
    fc = ks.build_forecast(stats, slots(580, 50))
    html = ks.forecast_html(fc)
    assert "Platte 1" in html and "Details" in html
    for word in ("Filament", "Modell", "Gereinigt", "Turm", "Gesamt", "Rest"):
        assert word in html
    assert "Stützen" not in html                                     # leere Spalten wie in Orca weglassen
    assert "reicht nicht" in html                                   # Slot 2 reicht nicht
    assert "1 Farbwechsel (von Orca gezählt)" in html


def test_without_patch_there_is_no_preview(ks):
    assert not hasattr(ks.orca.host, "slice_statistics")
    assert ks.read_slice_statistics() is None
