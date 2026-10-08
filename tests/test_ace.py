"""ACE-Karte unter ACEPRO: Endlosspule und Modus lesen/schreiben; der Spuel-Multiplikator ist entfallen."""

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
    # Form fuer App 1.8.0: auto_refill = Endlosspule, keine Zahl-Felder mit null
    assert st["auto_refill"] is True and st["flush_multiplier_editable"] is False and st["presets"] == {}
    assert a.purge_preview() == {"pairs": [], "source": "orca"}


def test_switch_endless_spool_and_mode(ace):
    a, moon = ace
    asyncio.run(a.set_options({"endless_spool": False, "endless_mode": "material"}))
    assert moon.sent == ["ACE_DISABLE_ENDLESS_SPOOL\nACE_SET_ENDLESS_SPOOL_MODE MODE=material"]
    asyncio.run(a.set_options({"auto_refill": True}))                     # Schalter der App 1.8.0
    assert moon.sent[-1] == "ACE_ENABLE_ENDLESS_SPOOL"


def test_allowed_while_printing(ace):
    a, moon = ace
    moon.merge({"print_stats": {"state": "printing"}})
    asyncio.run(a.set_options({"endless_spool": True}))
    assert moon.sent == ["ACE_ENABLE_ENDLESS_SPOOL"]


def test_rejects_unknown_and_removed_settings(ace):
    a, moon = ace
    for body, status in (({"endless_mode": "egal"}, 400), ({"runout_detect": True}, 400), ({"x": 1}, 400),
                         ({"endless_spool": "ja"}, 400), ({}, 400)):
        with pytest.raises(AceError) as e:
            asyncio.run(a.set_options(body))
        assert e.value.status == status
    with pytest.raises(AceError) as e:
        asyncio.run(a.set_flush_multiplier(1.0))
    assert e.value.status == 410 and "Orca" in str(e.value)
    assert moon.sent == []


def test_ace_not_connected(ace):
    a, moon = ace
    moon.merge(ace_status([], connected=False))
    assert a.state()["present"] is False and a.state()["endless_spool"] is None
    with pytest.raises(AceError) as e:
        asyncio.run(a.set_options({"endless_spool": True}))
    assert e.value.status == 503
