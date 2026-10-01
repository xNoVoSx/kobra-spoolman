"""ACE-Einstellungen: Multiplikator und Display-Optionen lesen/schreiben, Freigabe beim Drucken, Vorschau."""

from __future__ import annotations

import asyncio

import pytest
from conftest import FakeMoonraker

from acebridge.ace import AceError, AceSettings
from acebridge.purge import PurgeModel
from acebridge.slots import SlotManager

HUB = {"auto_refill": 1, "flush_multiplier": 1, "flush_multiplier_editable": 1, "flush_volume_max": 800,
       "flush_volume_min": 107, "runout_detect": 1}


class Moon(FakeMoonraker):
    def __init__(self):
        super().__init__()
        self.sent, self.posted, self.hub = [], [], dict(HUB)

    async def gcode(self, script):
        self.sent.append(script)
        if script.startswith("SET_ACE_FLUSH_MULTIPLIER"):       # so wie Rinkhals es weiterreicht
            self.hub["flush_multiplier"] = float(script.split("VALUE=")[1])

    async def get_json(self, path):
        assert path == "/printer/filament_hub/get_config"
        return dict(self.hub)

    async def post_json(self, path, body):
        self.posted.append((path, body))
        self.hub.update(body)


class SM:
    def __init__(self, spools):
        self.spools = spools

    def templates(self):
        return []


def spool(sid, slot, color, density=1.27):
    return {"id": sid, "location": f"ACE Slot {slot}",
            "filament": {"id": 100 + sid, "name": f"PETG {color}", "material": "PETG", "color_hex": color,
                         "density": density, "vendor": {"name": "Sunlu"}}}


@pytest.fixture
def ace(cfg):
    moon = Moon()
    moon.merge({"mmu": {"num_gates": 4, "gate_status": [1, 1, 0, 0], "gate_material": ["PETG", "PETG", "", ""],
                        "gate_color": ["685BC7FF", "EC008CFF", "", ""]}, "print_stats": {"state": "standby"}})
    slots = SlotManager(cfg, moon, SM([spool(1, 1, "685BC7"), spool(2, 2, "C52E79")]))
    a = AceSettings(moon, PurgeModel(), slots, slots.sm)
    asyncio.run(a.refresh())
    return a, moon


def test_reads_settings_from_the_printer(ace):
    a, _ = ace
    st = a.state()
    assert st["present"] and st["flush_multiplier"] == 1 and st["auto_refill"] is True
    assert a.purge.flush_source == "printer"


def test_flush_multiplier_via_rinkhals_command(ace):
    a, moon = ace
    st = asyncio.run(a.set_flush_multiplier("0.8"))
    assert moon.sent == ["SET_ACE_FLUSH_MULTIPLIER VALUE=0.8"] and st["flush_multiplier"] == 0.8
    assert a.purge.flush["flush_multiplier"] == 0.8           # Spuel-Modell kennt den neuen Wert
    for bad in ("0", "3.5", "viel"):
        with pytest.raises(AceError):
            asyncio.run(a.set_flush_multiplier(bad))


def test_changes_while_printing_need_confirmation(ace):
    a, moon = ace
    moon.merge({"print_stats": {"state": "printing"}})
    with pytest.raises(AceError) as e:
        asyncio.run(a.set_flush_multiplier(1.5))
    assert e.value.status == 409 and moon.sent == []
    asyncio.run(a.set_flush_multiplier(1.5, confirm_printing=True))
    assert moon.sent == ["SET_ACE_FLUSH_MULTIPLIER VALUE=1.5"]
    with pytest.raises(AceError):
        asyncio.run(a.set_options({"auto_refill": False}))


def test_display_options(ace):
    a, moon = ace
    st = asyncio.run(a.set_options({"auto_refill": False, "runout_detect": True}))
    assert moon.posted == [("/printer/filament_hub/set_config", {"auto_refill": 0, "runout_detect": 1})]
    assert st["auto_refill"] is False and st["runout_detect"] is True
    for bad in ({"flush_volume_max": 900}, {"auto_refill": "ja"}, {}):
        with pytest.raises(AceError):
            asyncio.run(a.set_options(bad))


def test_purge_preview_uses_ace_colours(ace):
    a, _ = ace
    p = a.purge_preview()
    pairs = {(x["from_slot"], x["to_slot"]): x for x in p["pairs"]}
    assert set(pairs) == {(1, 2), (2, 1)}
    # Slot 2: die ACE meldet EC008C (Spoolman sagt C52E79) - gerechnet wird mit der ACE-Farbe
    assert pairs[(1, 2)]["volume_mm3"] == 312 and pairs[(2, 1)]["volume_mm3"] == 381
    assert pairs[(1, 2)]["mm"] == pytest.approx(312 / 2.405 - 3, abs=0.2)
    double = a.purge_preview(2.0)
    assert {(x["from_slot"], x["to_slot"]): x for x in double["pairs"]}[(1, 2)]["mm"] > 2 * pairs[(1, 2)]["mm"] - 5
