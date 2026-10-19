"""Direct feed (direct.py, Klipper kobra_direct): filament by hand in the toolhead, the ACE is passed by.

Booking goes to the direct spool (not to the spool in the slot of the tool), Auto PA and the Z offset take its
filament for every tool, switching sends exactly KOBRA_DIRECT, a multi-colour file is caught at the start."""

from __future__ import annotations

import asyncio
import types

import pytest
from conftest import FakeMoonraker, FakeSlots, FakeSpoolman, ace_status, spool

from acebridge.direct import DirectError, DirectFeed

TPU = 17


def tpu_spool():
    s = spool(TPU, None)
    s["filament"].update(material="TPU", name="TPU 95A Schwarz", color_hex="111111")
    return s


def direct_status(enabled=True, tool=None):
    return {"kobra_direct": {"enabled": enabled, "spool": TPU if enabled else 0, "name": "Test TPU 95A Schwarz",
                             "tool": tool}}


# ---------------------------------------------------------------- booking
def run_print(cfg, enabled):
    from acebridge.usage import UsageTracker
    moon = FakeMoonraker()
    sm = FakeSpoolman([spool(3, 1), spool(4, 3), tpu_spool()])
    tracker = UsageTracker(cfg, moon, sm, FakeSlots(moon, sm))
    tracker.direct = DirectFeed(moon, sm)

    async def go():
        status = ace_status([{"material": "PETG", "color": "685BC7"}, None, {"material": "PETG", "color": "212721"}])
        status["print_stats"] = {"state": "printing", "filename": "tpu.gcode", "filament_used": 0.0}
        status.update(direct_status(enabled, tool=None))
        moon.merge(status)
        await tracker.on_status(status, True, moon.status)
        for d in ({"print_stats": {"filament_used": 5.0}},            # before the start knows the tool
                  {"kobra_direct": {"tool": 2}},                      # _KOBRA_DIRECT_TOOL T=2 START=1
                  {"print_stats": {"filament_used": 25.0}},
                  {"print_stats": {"filament_used": 1225.0}},
                  {"print_stats": {"state": "complete"}}):
            moon.merge(d)
            await tracker.on_status(d, False, moon.status)
    asyncio.run(go())
    return sm, tracker


def test_direct_feed_books_on_the_direct_spool(cfg):
    sm, tracker = run_print(cfg, enabled=True)
    job = tracker.history[0]
    assert sm.booked(TPU) == pytest.approx(1225.0, abs=0.1)        # all of it, also before the tool was known
    assert sm.booked(4) == 0                                        # not the PETG in slot 3 (T2)
    assert tracker.open == []
    s = job["slots"][0]
    assert s["slot"] == 3 and s.get("direct") is True               # tool of the print, marked direct


def test_without_direct_feed_nothing_changes(cfg):
    sm, tracker = run_print(cfg, enabled=False)
    assert sm.booked(TPU) == 0                                      # ACEPRO reports no slot here: open item
    assert not any(s.get("direct") for s in tracker.history[0]["slots"])


# ---------------------------------------------------------------- switching
class GcodeMoon(FakeMoonraker):
    def __init__(self):
        super().__init__()
        self.sent = []

    async def gcode(self, script, timeout=15, source="Bridge"):
        self.sent.append((script, timeout))


def feed():
    moon = GcodeMoon()
    moon.merge({"print_stats": {"state": "standby"}, **direct_status(False)})
    return moon, DirectFeed(moon, FakeSpoolman([tpu_spool()]), wait_s=0)


def test_switch_on_and_off_sends_kobra_direct():
    moon, d = feed()
    asyncio.run(d.set(True, TPU))
    asyncio.run(d.set(True, TPU, unload=True))
    asyncio.run(d.set(False))
    assert moon.sent[0] == ('KOBRA_DIRECT ENABLE=1 SPOOL=17 NAME="Test TPU 95A Schwarz"', 15)
    assert moon.sent[1][0].endswith(" UNLOAD=1") and moon.sent[1][1] == 600    # unloading takes its time
    assert moon.sent[2][0] == "KOBRA_DIRECT ENABLE=0"


@pytest.mark.parametrize("kw, status", [({"enable": True, "spool_id": None}, 400),
                                        ({"enable": True, "spool_id": 999}, 404)])
def test_switch_needs_a_known_spool(kw, status):
    _, d = feed()
    with pytest.raises(DirectError) as e:
        asyncio.run(d.set(kw["enable"], kw["spool_id"]))
    assert e.value.status == status


def test_switch_refused_during_a_print_and_without_module():
    moon, d = feed()
    moon.merge({"print_stats": {"state": "printing"}})
    with pytest.raises(DirectError) as e:
        asyncio.run(d.set(False))
    assert e.value.status == 409
    moon.status.pop("kobra_direct")
    with pytest.raises(DirectError) as e:
        asyncio.run(d.set(False))
    assert e.value.status == 503 and moon.sent == []


def test_view_has_the_red_warning_only_when_on():
    moon, d = feed()
    assert d.view()["active"] is False and d.view()["warning"] is None
    moon.merge(direct_status(True, tool=0))
    v = d.view()
    assert v["active"] and v["spool_id"] == TPU and v["material"] == "TPU" and v["tool"] == 0
    assert "TPU 95A Schwarz" in v["warning"]


# ---------------------------------------------------------------- Auto PA / Z offset: direct spool for every tool
def test_pa_and_z_take_the_direct_filament(cfg):
    from acebridge.filament_z import FilamentZSync
    from acebridge.pa import PaSync
    moon = FakeMoonraker()
    sm = FakeSpoolman([spool(3, 1), tpu_spool()])
    sm.templates = lambda: []
    slots = FakeSlots(moon, sm)
    pa, z = PaSync(cfg, moon, sm, slots), FilamentZSync(cfg, moon, sm, slots)
    pa.direct = z.direct = DirectFeed(moon, sm)
    moon.merge(ace_status([{"material": "PETG", "color": "685BC7"}, None, None, None]))
    before = pa.desired()
    assert "FILAMENT=103" in before[0] and "CLEAR=1" in before[1]
    moon.merge(direct_status(True))
    after = pa.desired()
    assert all(f"FILAMENT={100 + TPU}" in after[t] for t in range(4))
    assert len(z.desired()) == 4


# ---------------------------------------------------------------- print start check
def test_print_check_catches_a_multi_colour_file():
    from acebridge import printcheck
    moon = FakeMoonraker()
    sm = FakeSpoolman([tpu_spool()])
    moon.merge({"print_stats": {"state": "printing"}, **direct_status(True, tool=0)})
    model = type("M", (), {"e_total": {0: 500.0, 1: 300.0}, "types": ["TPU", "PLA"], "colours": ["111111", "FF0000"],
                           "__len__": lambda self: 2})()
    bridge = types.SimpleNamespace(moon=moon, slots=FakeSlots(moon, sm), direct=DirectFeed(moon, sm),
                                   preview=types.SimpleNamespace(model=model, status="ready"),
                                   moisture=types.SimpleNamespace(view=lambda s: {"needs_drying": False}))
    kinds = [i["kind"] for i in printcheck.check(bridge)]
    assert kinds == ["direct_multi"]
    model.e_total = {0: 500.0}
    model.types = ["PLA"]
    kinds = [i["kind"] for i in printcheck.check(bridge)]
    assert kinds == ["material"]                                    # file wants PLA, the direct spool is TPU
