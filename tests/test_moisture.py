"""Feuchte je Spule, Feuchte-Verlauf und Trocknungen, automatisch trocknen beim Einlegen."""

from __future__ import annotations

import json
import os

import pytest
from conftest import ace_status
from test_dryer import GMoon, Clock, hub, run

from acebridge.dryer import Dryer
from acebridge.humidity import HumidityLog
from acebridge.moisture import (OPEN_DAYS, U_WARN, MoistureModel, absorb, dry, hours_needed, material_params,
                                parse_locations)
from acebridge.slots import SlotManager


def test_absorb_reaches_the_warning_after_open_days_at_50_percent():
    u = absorb(0.0, 50, OPEN_DAYS["PETG"] * 24, OPEN_DAYS["PETG"])
    assert u == pytest.approx(U_WARN, abs=1e-6)
    assert absorb(0.0, 15, 10_000, 5) < U_WARN                       # Trockenbox: nie
    assert absorb(0.0, 70, OPEN_DAYS["PETG"] * 24 * 0.7, OPEN_DAYS["PETG"]) > U_WARN   # feuchter Raum: schneller


def test_drying_time_and_cooler_ace_takes_longer():
    assert dry(0.5, 6, 6, 60, 60) == pytest.approx(0.05)
    assert dry(0.5, 6, 6, 50, 60) > dry(0.5, 6, 6, 60, 60)           # 10 degC kuehler -> langsamer
    assert hours_needed(None, 6, 50, 60) == pytest.approx(12)        # unbekannt: volle Dauer x2
    assert hours_needed(0.02, 6, 60, 60) == 0


def test_parse_locations():
    assert parse_locations("Trockenbox=15; Vakuumbeutel = 10 %") == {"Trockenbox": 15, "Vakuumbeutel": 10}
    for bad in ("Trockenbox", "Box=nass", "Box=150"):
        with pytest.raises(ValueError):
            parse_locations(bad)


def test_material_params_from_filament_template_or_default():
    tpl = {"name": "Vorlage PETG", "material": "PETG", "vendor": {"name": "Vorlage"}, "extra": {"dry_hours": "8"}}
    fil = {"material": "PETG", "extra": {"open_days": "2"}}
    p = material_params(fil, [tpl])
    assert (p["open_days"], p["dry_hours"]) == (2.0, 8.0)
    assert material_params({"material": "TPU"}, [])["open_days"] == OPEN_DAYS["TPU"]


class SM:
    """Spoolman mit Spulen im Speicher, Feldern und PATCH-Mitschnitt."""
    def __init__(self, spools):
        self.spools = spools
        self.patched = []
        self.field_keys = {"moisture", "last_in_ace", "last_dried", "last_dried_info"}

    def templates(self):
        return []

    def spool(self, sid):
        return next((s for s in self.spools if s["id"] == sid), None)

    def is_template(self, fil):
        return False

    async def fields(self, entity, refresh=False):
        return [{"key": k} for k in self.field_keys]

    async def patch_spool(self, sid, data):
        self.patched.append((sid, data))


def sp(sid, location, material="PETG"):
    return {"id": sid, "location": location, "filament": {"id": 100 + sid, "name": material, "material": material,
                                                         "vendor": {"name": "Sunlu"}, "extra": {}}}


@pytest.fixture
def world(cfg):
    moon = GMoon()
    moon.merge({**ace_status([{"material": "", "color": "000000"}] * 4), "print_stats": {"state": "standby"}})
    moon.merge(hub(humidity=20))
    clock = Clock()
    clock.t = 1_000_000.0
    spools = [sp(1, "Regal"), sp(2, "Trockenbox")]
    sm = SM(spools)
    slots = SlotManager(cfg, moon, sm)
    m = MoistureModel(cfg, moon, slots, clock=clock)
    return m, moon, clock, sm


def advance(m, clock, hours, step_h=1.0):
    t = 0.0
    while t < hours:
        clock.t += step_h * 3600
        t += step_h
        run(m.tick())


def test_shelf_spool_gets_wet_trockenbox_does_not(world, cfg):
    m, moon, clock, sm = world
    cfg.dry_locations = "Trockenbox=15"
    run(m.tick())
    for sid in ("1", "2"):
        m.state[sid]["u"] = 0.0                                       # frisch getrocknet
    advance(m, clock, 6 * 24)                                         # 6 Tage, PETG: 5 Tage bis zur Schwelle
    assert m.view(sm.spool(1))["needs_drying"] and m.view(sm.spool(1))["score"] >= 100
    assert not m.view(sm.spool(2))["needs_drying"]
    assert any(d["extra"].get("moisture") for _, d in sm.patched)    # Feld in Spoolman geschrieben


def test_new_spool_is_unknown_and_counts_as_wet(world, cfg):
    m, moon, clock, sm = world
    run(m.tick())
    v = m.view(sm.spool(1))
    assert v["score"] is None and v["state"] == "unknown" and v["needs_drying"]
    cfg.new_spools_dry = False
    assert not m.view(sm.spool(1))["needs_drying"]


def test_insert_calls_back_and_drying_in_the_ace_dries(world):
    m, moon, clock, sm = world
    seen = []
    m.on_insert = lambda spool, info: seen.append((spool["id"], info))
    run(m.tick())
    m.state["1"]["u"] = 0.4
    sm.spool(1)["location"] = "ACE Slot 2"
    clock.t += 10
    run(m.tick())
    assert seen and seen[0][0] == 1 and seen[0][1]["needs_drying"] and seen[0][1]["slot"] == 2
    moon.merge(hub(humidity=20, drying=True, target=60, remain=6 * 3600))
    moon.status["ace_instance_0"]["temp"] = 60                        # gemessene Lufttemperatur zaehlt
    advance(m, clock, 6)
    assert m.view(sm.spool(1))["score"] < 30
    moon.merge(hub(humidity=10, drying=False))
    advance(m, clock, 0.1, 0.1)
    hist = m.history(1)
    assert hist[0]["kind"] == "dried" and hist[0]["temp"] == 60
    sm.spool(1)["location"] = "Regal"
    clock.t += 10
    run(m.tick())
    assert m.history(1)[0]["kind"] == "out" and any("last_in_ace" in d["extra"] for _, d in sm.patched)


def test_humidity_log_points_sessions_and_cleanup(cfg):
    moon = GMoon()
    moon.merge(hub(humidity=25))
    clock = Clock()
    clock.t = 1_000_000.0
    log = HumidityLog(cfg, moon, clock=clock)
    log.spools_in_ace = lambda: [{"slot": 1, "spool_id": 7}]
    for _ in range(5):
        clock.t += 60
        log.tick()
    log.note_start("auto", 55, 6, "Automatik: Feuchte 25 % ≥ 20 %")
    moon.merge(hub(humidity=25, drying=True, target=55, remain=6 * 3600))
    clock.t += 60
    log.tick()
    assert log.open and log.open["source"] == "auto" and log.open["spools"][0]["spool_id"] == 7
    moon.merge(hub(humidity=24, drying=True, target=50, remain=5 * 3600))
    clock.t += 60
    log.tick()
    assert log.open["temps"][-1][1] == 50                             # Soll gesenkt -> mitgeschrieben
    log.note_stop("auto", "Ziel erreicht: Feuchte 9 % ≤ 10 %")
    moon.merge(hub(humidity=9, drying=False))
    clock.t += 60
    log.tick()
    s = log.recent_sessions()[0]
    assert s["end_reason"].startswith("Ziel erreicht") and s["humidity_start"] == 25 and s["humidity_end"] == 9
    assert 7 <= len(log.points(1)) <= 8
    assert len(log.points(1, max_points=3)) == 3
    old = os.path.join(log.dir, "1969-01-01.jsonl")                    # Testuhr steht auf Januar 1970
    open(old, "w").write("[1,1,1,0,0]\n")
    assert log.cleanup() == 1 and not os.path.exists(old)
    again = HumidityLog(cfg, moon, clock=clock)                        # gespeichert
    assert again.recent_sessions()[0]["id"] == s["id"]


def test_display_started_drying_is_recorded_too(cfg):
    moon = GMoon()
    moon.merge(hub(humidity=30))
    clock = Clock()
    log = HumidityLog(cfg, moon, clock=clock)
    log.tick()                                                          # Bridge laeuft, ACE trocknet noch nicht
    moon.merge(hub(humidity=30, drying=True, target=45, remain=60 * 60))
    clock.t += 60
    log.tick()
    assert log.open["source"] == "drucker"
    moon.merge(hub(humidity=20, drying=False))
    clock.t += 360 * 60                                                 # geplante 360 min (Display)
    log.tick()
    assert log.recent_sessions()[0]["end_reason"] == "Laufzeit um"


def test_drying_already_running_at_bridge_start_has_unknown_origin(cfg):
    moon = GMoon()
    moon.merge(hub(humidity=30, drying=True, target=50, remain=3600))
    log = HumidityLog(cfg, moon, clock=Clock())
    log.tick()
    assert log.open["source"] == "unbekannt" and "Start der Bridge" in log.open["reason"]


def test_ensure_only_restarts_when_too_short(cfg):
    moon = GMoon()
    moon.merge({**ace_status([{"material": "", "color": "000000"}] * 4), "print_stats": {"state": "standby"}})
    moon.merge(hub(drying=True, target=55, remain=8 * 3600))

    class S:
        spools = [{"id": 1, "location": "ACE Slot 1", "filament": {"id": 9, "material": "PETG", "extra": {}}}]

        def templates(self):
            return []
    d = Dryer(cfg, moon, SlotManager(cfg, moon, S()), clock=Clock())
    assert run(d.ensure(6, "x")) is False and moon.sent == []
    moon.merge(hub(drying=True, target=55, remain=2 * 3600))
    assert run(d.ensure(6, "Spule eingelegt")) is True and moon.sent[-1].startswith("ACE_START_DRYING") and "DURATION=360" in moon.sent[-1]


def test_spoolman_values_are_json_encoded(world):
    m, moon, clock, sm = world
    run(m._write(1, {"moisture": 42, "unbekannt": 1}))
    assert sm.patched == [(1, {"extra": {"moisture": json.dumps(42)}})]
