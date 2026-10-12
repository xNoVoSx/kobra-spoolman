"""ACE card under Rinkhals: GoKlipper's ACE configuration (endless spool = auto_refill, runout detection, purge
multiplier), the lock during a print and the purge preview of the firmware model."""

from __future__ import annotations

import asyncio

import pytest
from conftest import FakeMoonraker
from test_acemodel_rinkhals import rinkhals_status

from acebridge.ace import AceError, AceSettings
from acebridge.slots import SlotManager

CONFIG = {"auto_refill": 1, "flush_multiplier": 1.5, "flush_multiplier_editable": 1, "flush_volume_max": 800,
          "flush_volume_min": 107, "runout_detect": 1}


class Moon(FakeMoonraker):
    def __init__(self):
        super().__init__()
        self.sent, self.posted, self.config = [], [], dict(CONFIG)

    async def gcode(self, script, source="Bridge"):
        self.sent.append(script)
        if script.startswith("SET_ACE_FLUSH_MULTIPLIER VALUE="):
            self.config["flush_multiplier"] = float(script.split("=", 1)[1])

    async def get_json(self, path, timeout=10):
        assert path == "/printer/filament_hub/get_config"
        return dict(self.config)

    async def post_json(self, path, body, timeout=10):
        assert path == "/printer/filament_hub/set_config"
        self.posted.append(body)
        self.config.update(body)
        return {}


class SM:
    spools: list = []

    def templates(self):
        return []


@pytest.fixture
def ace(cfg):
    moon = Moon()
    moon.merge(rinkhals_status())
    a = AceSettings(moon, SlotManager(cfg, moon, SM()))
    asyncio.run(a.refresh(force=True))
    return a, moon


def test_state_from_goklipper_config(ace):
    a, _ = ace
    st = a.state()
    assert st["variant"] == "rinkhals" and st["present"]
    assert st["options"] == ["endless_spool", "runout_detect", "flush_multiplier"]
    assert st["endless_spool"] is True and st["runout_detect"] is True and st["flush_multiplier"] == 1.5
    assert st["endless_modes"] == {} and st["model"] == "Anycubic Color Engine Pro 2.0"
    assert a.purge.flush["flush_multiplier"] == 1.5 and a.purge.flush_source == "printer"


def test_options_and_multiplier(ace):
    a, moon = ace
    st = asyncio.run(a.set_options({"endless_spool": False, "runout_detect": False}))
    assert moon.posted == [{"auto_refill": 0, "runout_detect": 0}]
    assert st["endless_spool"] is False and st["runout_detect"] is False
    st = asyncio.run(a.set_options({"flush_multiplier": 1.0}))
    assert moon.sent == ["SET_ACE_FLUSH_MULTIPLIER VALUE=1"] and st["flush_multiplier"] == 1.0
    for bad in ({"flush_multiplier": 5}, {"flush_multiplier": "x"}, {"endless_mode": "exact"}, {"runout_detect": 1}):
        with pytest.raises(AceError) as e:
            asyncio.run(a.set_options(bad))
        assert e.value.status == 400


def test_changes_during_a_print_need_confirmation(ace):
    a, moon = ace
    moon.merge({"print_stats": {"state": "printing"}})
    with pytest.raises(AceError) as e:
        asyncio.run(a.set_options({"flush_multiplier": 1.0}))
    assert e.value.status == 409 and moon.sent == []
    asyncio.run(a.set_options({"flush_multiplier": 1.0}, confirm_printing=True))
    assert moon.sent == ["SET_ACE_FLUSH_MULTIPLIER VALUE=1"]


def test_purge_preview_per_colour_pair(ace):
    a, _ = ace
    p = a.purge_preview()
    assert p["flush_multiplier"] == 1.5 and {s["slot"] for s in p["slots"]} == {1, 2, 4}
    pair = next(x for x in p["pairs"] if x["from_slot"] == 1 and x["to_slot"] == 2)
    assert pair["volume_mm3"] > 107 and pair["mm"] > 0
    cheaper = a.purge_preview(1.0)
    assert next(x for x in cheaper["pairs"] if x["from_slot"] == 1 and x["to_slot"] == 2)["mm"] < pair["mm"]


def test_acepro_has_no_purge_preview(cfg):
    from conftest import ace_status
    moon = Moon()
    moon.merge({**ace_status([{"material": "PETG", "color": "685BC7"}]), "print_stats": {"state": "standby"}})
    a = AceSettings(moon, SlotManager(cfg, moon, SM()))
    assert a.purge_preview() is None and a.state()["options"] == ["endless_spool", "endless_mode"]
