"""ACE card under ACEPRO: read/write endless spool and mode; the purge multiplier is gone."""

from __future__ import annotations

import asyncio

import pytest
from conftest import FakeMoonraker, ace_status

from acebridge.ace import AceError, AceSettings
from acebridge.slots import SlotManager


class Moon(FakeMoonraker):
    def __init__(self):
        super().__init__()
        self.sent = []

    async def gcode(self, script, source="Bridge"):
        self.sent.append(script)
        for line in script.split("\n"):              # like the driver: the new state comes back in the subscription
            if line in ("ACE_ENABLE_ENDLESS_SPOOL", "ACE_DISABLE_ENDLESS_SPOOL"):
                self.merge({"ace": {"endless_spool_enabled": line.startswith("ACE_ENABLE")}})
            elif line.startswith("ACE_SET_ENDLESS_SPOOL_MODE MODE="):
                self.merge({"ace": {"endless_spool_match_mode": line.split("=", 1)[1]}})


class SM:
    spools: list = []

    def templates(self):
        return []


@pytest.fixture
def ace(cfg):
    moon = Moon()
    moon.merge({**ace_status([{"material": "PETG", "color": "685BC7"}], endless=True),
                "print_stats": {"state": "standby"}})
    return AceSettings(moon, SlotManager(cfg, moon, SM())), moon


def test_reads_endless_spool_from_the_driver(ace):
    a, _ = ace
    st = a.state()
    assert st["present"] and st["endless_spool"] is True and st["endless_mode"] == "exact"
    assert st["firmware"] == "V1.1.36" and set(st["endless_modes"]) == {"exact", "material", "next"}
    assert "flush_multiplier" not in st and "auto_refill" not in st     # the GoKlipper fields are gone (11.10.)


def test_switch_endless_spool_and_mode(ace):
    a, moon = ace
    st = asyncio.run(a.set_options({"endless_spool": False, "endless_mode": "material"}))
    assert moon.sent == ["ACE_DISABLE_ENDLESS_SPOOL\nACE_SET_ENDLESS_SPOOL_MODE MODE=material"]
    assert st["endless_spool"] is False and st["endless_mode"] == "material"     # the answer shows the new state
    st = asyncio.run(a.set_options({"endless_spool": True}))
    assert moon.sent[-1] == "ACE_ENABLE_ENDLESS_SPOOL" and st["endless_spool"] is True


def test_answer_does_not_hang_when_the_driver_stays_silent(ace, monkeypatch):
    a, moon = ace
    monkeypatch.setattr("acebridge.ace.CONFIRM_WAIT_S", 0.2)
    moon.gcode = lambda script, source="Bridge": moon.sent.append(script) or asyncio.sleep(0)
    st = asyncio.run(a.set_options({"endless_spool": False}))
    assert moon.sent == ["ACE_DISABLE_ENDLESS_SPOOL"] and st["endless_spool"] is True   # old state, no error


def test_allowed_while_printing(ace):
    a, moon = ace
    moon.merge({"print_stats": {"state": "printing"}})
    asyncio.run(a.set_options({"endless_spool": True}))
    assert moon.sent == ["ACE_ENABLE_ENDLESS_SPOOL"]


def test_rejects_unknown_and_removed_settings(ace):
    a, moon = ace
    for body, status in (({"endless_mode": "egal"}, 400), ({"runout_detect": True}, 400), ({"auto_refill": True}, 400),
                         ({"x": 1}, 400), ({"endless_spool": "ja"}, 400), ({}, 400)):
        with pytest.raises(AceError) as e:
            asyncio.run(a.set_options(body))
        assert e.value.status == status
    assert moon.sent == []


def test_ace_not_connected(ace):
    a, moon = ace
    moon.merge(ace_status([], connected=False))
    assert a.state()["present"] is False and a.state()["endless_spool"] is None
    with pytest.raises(AceError) as e:
        asyncio.run(a.set_options({"endless_spool": True}))
    assert e.value.status == 503
