"""Auto-PA (pa.py): Spoolman-Werte an das Klipper-Modul kobra_pa geben, Messergebnisse zurueckschreiben, Schalter."""

from __future__ import annotations

import asyncio
import json
import time

import pytest
from conftest import FakeMoonraker, FakeSlots, FakeSpoolman, spool

from acebridge.pa import PaError, PaSync, filament_pa, k_at
from acebridge.spoolman import extra_value


class Moon(FakeMoonraker):
    def __init__(self):
        super().__init__()
        self.sent = []

    async def gcode(self, script, timeout=15, source="Bridge"):
        self.sent.append(script)


class SM(FakeSpoolman):
    def __init__(self, spools):
        super().__init__(spools)
        self.fields = []
        self.down = False

    def filament(self, fid):
        return next((f for f in self.filaments if f["id"] == fid), None)

    async def ensure_field(self, entity, key, body):
        if self.down:
            raise ConnectionError("spoolman down")
        if (entity, key) not in self.fields:
            self.fields.append((entity, key))

    async def patch_filament(self, fid, data):
        if self.down:
            raise ConnectionError("spoolman down")
        f = self.filament(fid)
        extra = f.setdefault("extra", {})
        for k, v in data.get("extra", {}).items():
            if v is None:
                extra.pop(k, None)
            else:
                extra[k] = v
        return f


def table(**kw):
    return json.dumps(json.dumps({"speeds": [100, 200, 300], "k": [0.04, 0.035, 0.03], **kw}))


@pytest.fixture
def env(cfg):
    moon = Moon()
    spools = [spool(1, 1), spool(2, 2), spool(3, None)]
    spools[0]["filament"]["extra"] = {"pa_table": table()}                    # gemessen
    spools[1]["filament"]["extra"] = {}                                       # noch kein PA
    spools[1]["filament"]["settings_extruder_temp"] = 250
    sm = SM(spools)
    moon.merge({"kobra_pa": {"enabled": True, "auto": True, "patched": True, "measuring": False, "active_t": None,
                             "slots": {}, "result": None, "result_seq": 0}, "print_stats": {"state": "standby"}})
    slots = FakeSlots(moon, sm)
    slots.printing = False
    return PaSync(cfg, moon, sm, slots), moon, sm


def run(coro):
    return asyncio.run(coro)


def test_filament_pa_uses_own_values_only():
    assert filament_pa({"extra": {"pa_table": table()}})["source"] == "table"
    assert filament_pa({"extra": {"pressure_advance": "0.042"}}) == {"speeds": [200.0], "k": [0.042], "source": "manual"}
    assert filament_pa({"extra": {}}) is None
    assert filament_pa({"extra": {"pa_table": json.dumps("kaputt")}}) is None
    assert filament_pa({"extra": {"pa_table": table(k=[0.04, 2, 0.03])}}) is None          # unplausibel -> ignoriert
    assert abs(k_at([100, 200, 300], [0.04, 0.035, 0.03]) - 0.035) < 1e-12
    assert k_at([100, 300], [0.04, 0.03], 50) == 0.04 and k_at([100, 300], [0.04, 0.03], 900) == 0.03
    assert k_at([100, 300], [0.03, 0.04], 200) == 0.03                                        # steigend: unterer Wert


def test_pushes_spoolman_state_once_and_again_after_restart(env):
    pa, moon, sm = env
    run(pa.tick())
    assert moon.sent == ["KOBRA_PA_SET T=0 SPEEDS=100,200,300 K=0.04,0.035,0.03 FILAMENT=101\n"
                         "KOBRA_PA_SET T=1 NONE=1 FILAMENT=102 TEMP=250\n"
                         "KOBRA_PA_SET T=2 CLEAR=1\nKOBRA_PA_SET T=3 CLEAR=1"]
    run(pa.tick())
    assert len(moon.sent) == 1                                    # unveraendert: nichts schicken
    sm.spools[2]["location"] = "ACE Slot 3"                      # Spule eingelegt (Filament ohne PA)
    run(pa.tick())
    assert moon.sent[-1] == "KOBRA_PA_SET T=2 NONE=1 FILAMENT=103"
    run(pa.tick(full=True))                                       # Klipper/Moonraker neu verbunden
    assert moon.sent[-1].count("KOBRA_PA_SET") == 4


def test_off_switch_and_missing_module_send_nothing(env, cfg):
    pa, moon, _ = env
    cfg.pa_sync = False
    run(pa.tick())
    assert moon.sent == []
    cfg.pa_sync = True
    moon.status.pop("kobra_pa")                                   # Klipper ohne Modul
    run(pa.tick())
    assert moon.sent == [] and pa.view()["present"] is False
    with pytest.raises(PaError):
        run(pa.switch(enabled=False))


def test_nothing_is_pushed_while_measuring(env):
    pa, moon, _ = env
    moon.merge({"kobra_pa": {"measuring": True}})
    run(pa.tick())
    assert moon.sent == []


def test_result_is_written_to_the_filament(env):
    pa, moon, sm = env
    run(pa.tick())
    t0 = time.time()
    moon.merge({"kobra_pa": {"result_seq": 1, "result": {
        "t": 1, "kind": "dynamic", "speeds": [100.0, 200.0, 300.0], "k": [0.05, 0.045, 0.04], "temp": 250.0,
        "nozzle": 0.4, "filament": "102", "time": t0, "message": ""}}})
    run(pa.tick())
    fil = sm.filament(102)
    tbl = json.loads(extra_value(fil, "pa_table"))
    assert tbl["k"] == [0.05, 0.045, 0.04] and tbl["temp"] == 250.0 and tbl["kind"] == "dynamic"
    assert extra_value(fil, "pressure_advance") == 0.045 and ("filament", "pa_table") in sm.fields
    assert moon.sent[-1] == "KOBRA_PA_SET T=1 SPEEDS=100,200,300 K=0.05,0.045,0.04 FILAMENT=102"
    assert any("gemessen: 0.045" in e["text"] for e in pa.events)
    # gleiches Ergebnis nach Bridge-Neustart: nicht nochmal schreiben
    del fil["extra"]["pa_table"]
    pa2 = PaSync(pa.cfg, moon, sm, pa.slots)
    run(pa2.tick())
    assert "pa_table" not in fil["extra"]


def test_failed_result_and_spoolman_down(env):
    pa, moon, sm = env
    moon.merge({"kobra_pa": {"result": {"t": 1, "kind": "error", "message": "Duese blockiert?", "filament": "102",
                                        "time": time.time()}}})
    run(pa.tick())
    assert extra_value(sm.filament(102), "pa_table") is None
    assert any(e["level"] == "warn" and "blockiert" in e["text"] for e in pa.events)
    sm.down = True
    moon.merge({"kobra_pa": {"result": {"t": 1, "kind": "static", "speeds": [200.0], "k": [0.04], "filament": "102",
                                        "time": time.time() + 1}}})
    run(pa.tick())
    assert any("nachgeholt" in e["text"] for e in pa.events)
    sm.down = False
    run(pa.tick())                                               # beim naechsten Takt gespeichert
    assert extra_value(sm.filament(102), "pressure_advance") == 0.04


def test_switch_calibrate_forget(env):
    pa, moon, sm = env
    run(pa.switch(enabled=True, auto=False))
    assert moon.sent[-1] == "KOBRA_PA ENABLE=1 AUTO=0"

    async def calib():
        pa.calibrate(2)
        await asyncio.sleep(0)
    run(calib())
    assert moon.sent[-1] == "KOBRA_PA_CALIBRATE T=1" and pa.view()["calibrating"] == 2
    with pytest.raises(PaError) as e:
        pa.calibrate(1)
    assert e.value.status == 409                                  # laeuft schon
    pa.calibrating = None
    pa.slots.printing = True
    with pytest.raises(PaError):
        pa.calibrate(1)
    pa.slots.printing = False
    moon.merge({"kobra_pa": {"enabled": False}})
    with pytest.raises(PaError):
        pa.calibrate(1)
    run(pa.forget(101))
    assert filament_pa(sm.filament(101)) is None


def test_view_lists_slots(env):
    pa, moon, _ = env
    moon.merge({"kobra_pa": {"active_t": 0, "slots": {"1": {"state": "failed"}}}})
    v = pa.view()
    s1, s2, s3 = v["slots"][:3]
    assert s1["source"] == "table" and s1["k_ref"] == 0.035 and s1["active"] and s1["state"] == "table"
    assert s2["state"] == "failed" and s2["k"] == []
    assert s3["state"] == "empty"
    assert v["enabled"] is True and v["patched"] is True


def test_nothing_is_pushed_before_spoolman_is_loaded(env):
    """Bridge-Start: bis Spoolman geladen ist, nicht alle Slots als leer an Klipper melden."""
    pa, moon, sm = env
    sm.connected = False
    run(pa.tick())
    assert moon.sent == []
    sm.connected = True
    run(pa.tick())
    assert len(moon.sent) == 1
