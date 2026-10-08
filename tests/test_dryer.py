"""ACE-Trockner: Temperatur nach dem empfindlichsten Filament, Automatik nach Feuchte, Sicherheit."""

from __future__ import annotations

import asyncio
import json

import pytest
from conftest import FakeMoonraker, ace_status

from acebridge.dryer import COMMAND_SETTLE_S, MAX_RESTARTS, Dryer, ace_max_temp, hub_state
from acebridge.slots import SlotManager


class GMoon(FakeMoonraker):
    def __init__(self):
        super().__init__()
        self.sent = []

    async def gcode(self, script, source="Bridge"):
        self.sent.append(script)


class SM:
    def __init__(self, spools, templates=()):
        self.spools = list(spools)
        self._t = list(templates)

    def templates(self):
        return self._t


class Clock:
    t = 1_000_000.0

    def __call__(self):
        return self.t


def hub(humidity=24, drying=False, target=0, remain=0, model="ACE2 (USB Single Serial)"):
    """ACE-Trockner wie ACEPRO ihn meldet (ace_instance_0; remain_time/duration in Sekunden)."""
    return {"ace_instance_0": {"humidity": humidity, "temp": 30, "model": model, "connection_state": "connected",
                               "dryer_status": {"status": "drying" if drying else "stop", "target_temp": target,
                                                "duration": 21600 if drying else 0, "remain_time": remain}}}


def spool(sid, slot, material, dry_temp=None):
    extra = {"dry_temp": json.dumps(dry_temp)} if dry_temp else {}
    return {"id": sid, "location": f"ACE Slot {slot}",
            "filament": {"id": 100 + sid, "name": material, "material": material, "vendor": {"name": "X"}, "extra": extra}}


@pytest.fixture
def make(cfg):
    def _make(spools, status, templates=()):
        moon = GMoon()
        n = 4
        moon.merge({**ace_status([{"material": "", "color": "000000"}] * n), "print_stats": {"state": "standby"}})
        moon.merge(status)
        clock = Clock()
        d = Dryer(cfg, moon, SlotManager(cfg, moon, SM(spools, templates)), clock=clock)
        return d, moon, clock
    return _make


def run(c):
    return asyncio.run(c)


def test_hub_state_and_ace_limits():
    h = hub_state(hub(humidity=24, drying=True, target=55, remain=12000))
    assert h["humidity"] == 24 and h["drying"] and h["target_temp"] == 55 and h["remaining_min"] == 200   # ACE meldet Sekunden
    assert isinstance(h["remaining_min"], int)                                                         # App: Long
    assert hub_state({})["present"] is False
    assert ace_max_temp("ACE2 (USB Single Serial)") == 65 and ace_max_temp("Anycubic Color Engine Pro 2.0") == 65
    assert ace_max_temp("ACE (USB)") == 55


def test_required_temp_is_the_most_sensitive_filament(make):
    d, _, _ = make([spool(1, 1, "PETG"), spool(2, 2, "PLA"), spool(3, 3, "PETG", dry_temp=70)], hub())
    r = d.required_temp()
    assert r["temp"] == 55 and r["limited_by"] == [2]             # PLA bestimmt
    d, _, _ = make([spool(1, 1, "PETG"), spool(3, 3, "ABS", dry_temp=70)], hub())
    assert d.required_temp()["temp"] == 60                        # PETG; ABS 70 > 65 ist ohnehin gedeckelt
    d, _, _ = make([spool(3, 3, "ABS", dry_temp=70)], hub(model="ACE (USB Single Serial)"))
    assert d.required_temp()["temp"] == 55                        # alte ACE Pro kann nur 55


def test_manual_start_is_capped(make):
    d, moon, _ = make([spool(1, 1, "PLA")], hub())
    res = run(d.start(70, 4))
    assert res["temp"] == 55 and moon.sent == ["ACE_START_DRYING TEMP=55 DURATION=240"]


def test_automation_starts_above_and_stops_below(make, cfg):
    d, moon, clock = make([spool(1, 1, "PETG")], hub(humidity=25))
    run(d.evaluate())
    assert moon.sent == []                                        # Automatik aus
    d.set_config({"enabled": True, "start_above": 20, "stop_below": 10, "max_hours": 6, "start_delay_minutes": 0})
    run(d.evaluate())
    assert moon.sent == ["ACE_START_DRYING TEMP=60 DURATION=360"] and d.auto_run
    run(d.evaluate())
    assert len(moon.sent) == 1                                    # ACE hat noch nicht gemeldet
    clock.t += COMMAND_SETTLE_S + 1
    moon.merge(hub(humidity=12, drying=True, target=60, remain=18000))
    run(d.evaluate())
    assert len(moon.sent) == 1                                    # 12 % > 10 %: weiter
    moon.merge(hub(humidity=9, drying=True, target=60, remain=15000))
    run(d.evaluate())
    assert moon.sent[-1] == "ACE_STOP_DRYING" and not d.auto_run
    clock.t += COMMAND_SETTLE_S + 1
    moon.merge(hub(humidity=25))
    run(d.evaluate())
    assert moon.sent[-1] == "ACE_STOP_DRYING"               # Pause nach dem Durchgang
    clock.t += 3600
    run(d.evaluate())
    assert moon.sent[-1].startswith("ACE_START_DRYING")


def test_sensitive_spool_lowers_a_running_manual_drying(make):
    d, moon, clock = make([spool(1, 1, "PETG"), spool(2, 2, "PLA")], hub(drying=True, target=60, remain=7200))
    run(d.evaluate())
    assert moon.sent == ["ACE_START_DRYING TEMP=55 DURATION=120"]
    assert "gesenkt" in d.last_event["text"]


def test_config_is_validated_and_kept(make, cfg):
    d, _, _ = make([], hub())
    with pytest.raises(ValueError):
        d.set_config({"start_above": 10, "stop_below": 20})
    d.set_config({"enabled": True, "start_above": 30})
    d2 = Dryer(cfg, d.moon, d.slots)
    assert d2.config.enabled and d2.config.start_above == 30


def test_no_ace_no_action(make):
    d, moon, _ = make([spool(1, 1, "PLA")], {"ace_instance_0": {"connection_state": "disconnected"}})
    d.set_config({"enabled": True})
    run(d.evaluate())
    assert moon.sent == [] and d.state()["present"] is False


def test_planned_drying_starts_once_and_survives_restart(make, cfg):
    d, moon, clock = make([spool(1, 1, "PLA")], hub(humidity=15))
    with pytest.raises(ValueError):
        d.set_schedule(clock.t - 10)                               # Vergangenheit
    with pytest.raises(ValueError):
        d.set_schedule(clock.t + 8 * 86400)                        # mehr als eine Woche
    d.set_schedule(clock.t + 3600, temp=70, hours=4)
    assert d.state()["schedule"]["temp"] == 70
    assert Dryer(cfg, moon, d.slots).schedule["at"] == clock.t + 3600   # bleibt nach Neustart
    run(d.evaluate())
    assert moon.sent == []                                         # noch nicht faellig
    clock.t += 3601
    run(d.evaluate())
    assert moon.sent == ["ACE_START_DRYING TEMP=55 DURATION=240"]   # auf PLA gedeckelt
    assert d.schedule is None and d.state()["schedule"] is None
    d.set_schedule(clock.t + 60)
    d.clear_schedule()
    assert d.schedule is None


def test_planned_drying_when_already_drying_is_dropped(make):
    d, moon, clock = make([spool(1, 1, "PETG")], hub(drying=True, target=60, remain=6000))
    d.set_schedule(clock.t + 10)
    clock.t += 11
    run(d.evaluate())
    assert moon.sent == [] and d.schedule is None and "lief bereits" in d.last_event["text"]


# ---------------------------------------------------------------- Wuensche Novos 09.10.2026
def test_manual_drying_runs_to_its_time_even_when_dry(make):
    """Von Hand gestartet: die Bridge stoppt nicht an der Feuchte (nur die Automatik tut das)."""
    d, moon, clock = make([spool(1, 1, "PETG")], hub(humidity=8))
    d.set_config({"enabled": True})
    run(d.start(60, 4))
    clock.t += COMMAND_SETTLE_S + 1
    moon.merge(hub(humidity=5, drying=True, target=60, remain=14000))
    run(d.evaluate())
    assert moon.sent == ["ACE_START_DRYING TEMP=60 DURATION=240"]
    assert d.state()["run"]["source"] == "hand"


def test_ace_ending_early_restarts_with_the_rest(make, cfg):
    d, moon, clock = make([spool(1, 1, "PETG")], hub(humidity=8))
    run(d.start(60, 4))
    until = d.run["until"]
    assert Dryer(cfg, moon, d.slots).run["until"] == until            # bleibt nach Neustart der Bridge
    clock.t += 3600                                                   # nach 1 h hoert die ACE von selbst auf
    moon.merge(hub(humidity=6, drying=False))
    run(d.evaluate())
    assert moon.sent[-1] == "ACE_START_DRYING TEMP=60 DURATION=180"  # Rest 3 h
    assert d.run["until"] == until and d.run["restarts"] == 1 and "vorzeitig" in d.last_event["text"]
    for _ in range(MAX_RESTARTS):                                     # hoert sie immer wieder auf: aufgeben
        clock.t += 60
        run(d.evaluate())
    assert d.run is None and "mehrfach" in d.last_event["text"]
    assert len(moon.sent) == 1 + MAX_RESTARTS


def test_finished_run_is_not_restarted_and_hand_stop_ends_it(make):
    d, moon, clock = make([spool(1, 1, "PETG")], hub())
    run(d.start(60, 1))
    clock.t += 3600 - 60                                              # Rest 1 min < MIN_REST_MIN: fertig
    run(d.evaluate())
    assert d.run is None and len(moon.sent) == 1
    run(d.start(60, 2))
    run(d.stop())
    clock.t += COMMAND_SETTLE_S + 1
    run(d.evaluate())
    assert d.run is None and moon.sent[-1] == "ACE_STOP_DRYING"


def test_automation_waits_until_humidity_stays_high(make):
    """Deckel auf: kurzer Ausschlag startet nichts - erst 15 min am Stueck ueber der Schwelle."""
    d, moon, clock = make([spool(1, 1, "PETG")], hub(humidity=12))
    d.set_config({"enabled": True, "start_above": 20})
    moon.merge(hub(humidity=45))                                      # Deckel auf
    run(d.evaluate())
    clock.t += 120
    moon.merge(hub(humidity=13))                                      # zu, faellt wieder
    run(d.evaluate())
    clock.t += 15 * 60
    run(d.evaluate())
    assert moon.sent == []
    moon.merge(hub(humidity=22))                                      # wirklich feucht
    run(d.evaluate())
    clock.t += 14 * 60
    run(d.evaluate())
    assert moon.sent == []
    clock.t += 61
    run(d.evaluate())
    assert moon.sent == ["ACE_START_DRYING TEMP=60 DURATION=360"] and d.auto_run
