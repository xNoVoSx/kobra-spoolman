"""Verstopfung erkennen (clog.py): Meldung solange Verdacht, Schalter, fehlendes Modul."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from conftest import FakeMoonraker

from acebridge.clog import Clog, ClogError
from acebridge.status import messages

ALARM = {"time": 1.0, "extruder_mm": 24.0, "encoder_mm": 0.0, "ratio": 0.0, "action": "warn"}


class Moon(FakeMoonraker):
    def __init__(self):
        super().__init__()
        self.sent = []

    async def gcode(self, script, timeout=15, source="Bridge"):
        self.sent.append(script)


@pytest.fixture
def env():
    moon = Moon()
    moon.merge({"kobra_clog": {"enabled": True, "action": "warn", "available": True, "suspect": False,
                               "alarm": None, "alarms": 0, "last": [1.0, 20.0, 18.0, 0.9], "min_ratio": 0.5}})
    return Clog(moon), moon


def _bridge(moon, cl):
    return SimpleNamespace(moon=moon, clog=cl, safety_warnings=lambda: [],
                           slots=SimpleNamespace(warnings=[], slots_view=lambda: [], unknown_tags={}, tag_events=[]),
                           usage=SimpleNamespace(open=[], history=[]), cfg=SimpleNamespace(),
                           sm=SimpleNamespace(connected=True), camera=SimpleNamespace(state=lambda: {}),
                           dryer=SimpleNamespace(state=lambda: {}))


def test_message_only_while_suspect(env):
    cl, moon = env
    assert cl.view()["last_ratio"] == 0.9 and cl.message() is None
    moon.merge({"kobra_clog": {"suspect": True, "alarm": dict(ALARM), "alarms": 1}})
    assert "Encoder sah nur 0 mm" in cl.message() and "prüfen" in cl.message()
    assert any(m["key"] == "clog" and m["level"] == "error" for m in messages(_bridge(moon, cl), [], 0.0))
    moon.merge({"kobra_clog": {"suspect": False}})          # wieder normal gefoerdert
    assert cl.message() is None and cl.view()["alarms"] == 1


def test_switch_and_errors(env):
    cl, moon = env
    asyncio.run(cl.switch(False))
    asyncio.run(cl.switch(action="pause"))
    asyncio.run(cl.switch(True, "warn"))
    assert moon.sent == ["KOBRA_CLOG ENABLE=0", "KOBRA_CLOG ACTION=pause", "KOBRA_CLOG ENABLE=1 ACTION=warn"]
    for args in ((None, "explode"), (None, None)):
        with pytest.raises(ClogError) as e:
            asyncio.run(cl.switch(*args))
        assert e.value.status == 400
    moon.status.pop("kobra_clog")
    assert cl.view()["present"] is False and cl.message() is None
    with pytest.raises(ClogError) as e:
        asyncio.run(cl.switch(True))
    assert e.value.status == 503
