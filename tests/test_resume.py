"""Fortsetzen nach Stromausfall (resume.py): Angebot, Meldung, Fortsetzen nur mit Bestaetigung, Verwerfen, Schalter."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from conftest import FakeMoonraker

from acebridge.resume import Resume, ResumeError
from acebridge.status import messages

PENDING = {"file": "teil.gcode", "pos": 1000, "progress": 0.4, "layer": 26, "layers": 65, "tool": 1, "saved_at": 1.0}


class Moon(FakeMoonraker):
    def __init__(self):
        super().__init__()
        self.sent = []
        self.fail = None

    async def gcode(self, script, timeout=15, source="Bridge"):
        self.sent.append(script)
        if self.fail:
            raise RuntimeError(self.fail)


@pytest.fixture
def env():
    moon = Moon()
    moon.merge({"kobra_resume": {"enabled": True, "pending": dict(PENDING), "result": None}})
    return Resume(moon, SimpleNamespace(printing=False)), moon


def test_offer_and_alarm_message(env):
    rs, moon = env
    v = rs.view()
    assert v["present"] and v["pending"]["layer"] == 26 and not v["running"]
    assert "Schicht 26" in rs.message()
    bridge = SimpleNamespace(moon=moon, resume=rs, safety_warnings=lambda: [],
                             slots=SimpleNamespace(warnings=[], slots_view=lambda: [], unknown_tags={}, tag_events=[]),
                             usage=SimpleNamespace(open=[], history=[]), cfg=SimpleNamespace(),
                             sm=SimpleNamespace(connected=True), camera=SimpleNamespace(state=lambda: {}),
                             dryer=SimpleNamespace(state=lambda: {}))
    msgs = messages(bridge, [], 0.0)
    assert any(m["key"] == "resume" and m["level"] == "error" for m in msgs)       # Alarm in der App


def test_start_only_when_sensible(env):
    rs, moon = env

    async def go():
        rs.start()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
    asyncio.run(go())
    assert moon.sent == ["KOBRA_RESUME CONFIRM=1"] and rs.running is False
    rs.slots.printing = True
    with pytest.raises(ResumeError) as e:
        rs.start()
    assert e.value.status == 409
    rs.slots.printing = False
    moon.merge({"kobra_resume": {"pending": None}})
    with pytest.raises(ResumeError):
        rs.start()


def test_failure_is_reported(env):
    rs, moon = env
    moon.fail = "Fortsetzen abgebrochen: Hoehe weicht 9.28 mm ab"

    async def go():
        rs.start()
        for _ in range(3):
            await asyncio.sleep(0)
    asyncio.run(go())
    assert "weicht" in rs.view()["error"] and not rs.running


def test_discard_switch_and_missing_module(env):
    rs, moon = env
    asyncio.run(rs.discard())
    asyncio.run(rs.switch(False))
    assert moon.sent == ["KOBRA_RESUME_DISCARD", "KOBRA_POWERLOSS ENABLE=0"]
    moon.status.pop("kobra_resume")
    assert rs.view()["present"] is False and rs.message() is None
    with pytest.raises(ResumeError) as e:
        asyncio.run(rs.switch(True))
    assert e.value.status == 503
