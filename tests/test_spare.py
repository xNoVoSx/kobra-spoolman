"""Another spool when one runs out (spare.py, Klipper kobra_spare): the question with Spoolman names, the choice sends
exactly KOBRA_SPARE T=<n> in the background, a red message (phone alarm) while it waits, the switches."""

from __future__ import annotations

import asyncio

import pytest
from conftest import FakeMoonraker

from acebridge import status, switches
from acebridge.spare import Spare, SpareError

CANDS = [{"tool": 1, "material": "PETG", "color": "C52E79", "temp": 250, "same_material": True, "same_color": False,
          "sticks": True},
         {"tool": 3, "material": "ASA", "color": "808080", "temp": 260, "same_material": False, "same_color": False,
          "sticks": False}]


def ks(waiting=True, **kw):
    st = {"enabled": True, "auto_after": 0.0, "auto_order": ["material", "color"],
          "waiting": {"tool": 0, "material": "PETG", "color": "685BC7", "temp": 250} if waiting else None,
          "candidates": CANDS if waiting else [], "auto_in": None, "busy": False, "map": {}, "last": None}
    st.update(kw)
    return {"kobra_spare": st}


class Slots:
    """Slot (1-based) -> spool, like SlotManager."""

    SPOOLS = {1: {"id": 5, "name": "Lavendel"}, 2: {"id": 7, "name": "Magenta"}}

    def assignments(self):
        return dict(self.SPOOLS), []

    def spool_info(self, s):
        return {"spool_id": s["id"], "display_name": "Sunlu PETG " + s["name"], "color": "C52E79", "material": "PETG",
                "remaining_weight": 812.0}


class GcodeMoon(FakeMoonraker):
    def __init__(self):
        super().__init__()
        self.sent = []
        self.fail = None

    async def gcode(self, script, timeout=15, source="Bridge"):
        self.sent.append((script, timeout))
        if self.fail:
            raise RuntimeError(self.fail)


def make(**kw):
    moon = GcodeMoon()
    moon.merge({"print_stats": {"state": "paused"}, "ace": {"endless_spool_enabled": True}, **ks(**kw)})
    return moon, Spare(moon, Slots())


def test_view_with_spoolman_names():
    _, sp = make()
    v = sp.view()
    assert v["available"] and v["waiting"]["slot"] == 1 and v["waiting"]["spool"]["name"] == "Sunlu PETG Lavendel"
    c1, c3 = v["candidates"]
    assert c1["slot"] == 2 and c1["spool"]["spool_id"] == 7 and c1["same_material"] and not c1["same_color"]
    assert c3["spool"] is None and not c3["sticks"]                      # slot 4 without a spool in Spoolman
    idle = make(waiting=False)[1].view()
    assert idle["waiting"] is None and idle["candidates"] == [] and idle["map"] == {}
    empty = Spare(FakeMoonraker()).view()
    assert empty["available"] is False and empty["candidates"] == []


def test_choose_sends_kobra_spare_in_the_background():
    moon, sp = make()

    async def go():
        v = sp.choose(1)
        assert v["busy"]
        await sp.task
        assert moon.sent == [("KOBRA_SPARE T=1", 600)] and sp.error is None
        moon.fail = "KOBRA_SPARE: Wechsel auf T3 gescheitert"
        sp.choose(3)
        await sp.task
    asyncio.run(go())
    assert sp.error and sp.view()["error"].startswith("KOBRA_SPARE")


def test_choose_refilled_slot_is_allowed():
    moon, sp = make()

    async def go():
        sp.choose(0)
        await sp.task
    asyncio.run(go())
    assert moon.sent[-1][0] == "KOBRA_SPARE T=0"


@pytest.mark.parametrize("tool, code", [(2, 404), ("1", 400), (True, 400), (-1, 400)])
def test_bad_choices(tool, code):
    moon, sp = make()
    with pytest.raises(SpareError) as e:
        sp.choose(tool)
    assert e.value.status == code and moon.sent == []


def test_nothing_waiting_or_busy_or_missing_module():
    _, sp = make(waiting=False)
    with pytest.raises(SpareError) as e:
        sp.choose(1)
    assert e.value.status == 409
    _, sp = make(busy=True)
    with pytest.raises(SpareError) as e:
        sp.choose(1)
    assert e.value.status == 409
    with pytest.raises(SpareError) as e:
        Spare(FakeMoonraker()).choose(1)
    assert e.value.status == 503


def test_red_message_while_waiting():
    moon, sp = make()
    msgs = status.spare_messages(sp)
    assert [m["key"] for m in msgs] == ["spare"] and msgs[0]["level"] == "error"
    assert "Sunlu PETG Lavendel" in msgs[0]["text"]
    sp.error = "kaputt"
    assert [m["key"] for m in status.spare_messages(sp)] == ["spare", "spare_error"]
    moon.merge(ks(busy=True))
    assert [m["key"] for m in status.spare_messages(sp)] == ["spare_error"]
    moon.merge(ks(waiting=False))
    assert status.spare_messages(sp) == []                                 # error only while it waits


def test_switches():
    st = {"ace": {"endless_spool_enabled": True}, **ks(auto_after=15.0)}
    items = {i["key"]: i for i in switches.items(st)}
    assert items["spare"]["on"] and items["spare"]["sensitive"] and items["spare_auto"]["current"] == "15"
    off = {i["key"]: i for i in switches.items({"ace": {"endless_spool_enabled": False}, **ks()})}
    assert not off["spare"]["sensitive"] and "spare_auto" not in off       # needs the endless spool
    assert switches._commands("spare")(False) == "KOBRA_SPARE ENABLE=0"
    assert switches._commands("spare_auto")("5") == "KOBRA_SPARE AUTO=5"
    with pytest.raises(switches.SwitchError):
        switches._commands("spare_auto")("7")
    assert "spare" not in {i["key"] for i in switches.items({})}
