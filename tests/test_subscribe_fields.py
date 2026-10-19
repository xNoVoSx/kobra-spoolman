"""Subscription: never subscribe objects whose fields may only appear later (ACE after connecting) with None -
with None Klipper freezes the field list at the first query."""

from acebridge import acemodel
from acebridge.moonraker import OPTIONAL_OBJECTS


def test_ace_objects_have_explicit_fields():
    for obj in ("ace", "ace_instance_0"):
        fields = acemodel.SUBSCRIBE[obj]
        assert isinstance(fields, list) and fields, obj
    assert {"humidity", "firmware", "slots", "dryer_status", "temp"} <= set(acemodel.SUBSCRIBE["ace_instance_0"])
    assert {"current_index", "target_index", "endless_spool_enabled"} <= set(acemodel.SUBSCRIBE["ace"])


def test_no_optional_object_subscribes_all_fields():
    assert [k for k, v in OPTIONAL_OBJECTS.items() if v is None] == []


# ---------------------------------------------------------------- frozen subscription (2026-10-19)
import asyncio  # noqa: E402

from acebridge.config import Config  # noqa: E402
from acebridge.moonraker import Moonraker  # noqa: E402


def _moon(status, fresh):
    async def nothing(delta, full):
        return None
    m = Moonraker(Config(), None, nothing)     # no HTTP session needed: query/subscribe are replaced
    m.status = status
    m.klippy_ready = True
    m.queried, m.subscribed = [], 0

    async def query(objects, timeout=5):
        m.queried.append(objects)
        return fresh

    async def subscribe():
        m.subscribed += 1
    m.query, m._subscribe = query, subscribe
    return m


def test_heal_subscribes_again_when_subscription_misses_humidity():
    m = _moon({"ace_instance_0": {"temp": 28, "connection_state": "connected"}},
              {"ace_instance_0": {"humidity": 14, "firmware": None}})
    assert asyncio.run(m.heal_late_fields(now=100.0)) is True
    assert m.queried == [{"ace_instance_0": ["humidity", "firmware"]}] and m.subscribed == 1


def test_heal_does_nothing_when_subscription_is_fine():
    m = _moon({"ace_instance_0": {"humidity": 14, "temp": 28}}, {"ace_instance_0": {"humidity": 15, "firmware": None}})
    assert asyncio.run(m.heal_late_fields(now=100.0)) is False and m.subscribed == 0


def test_heal_rate_limited_and_only_with_ace():
    m = _moon({"ace_instance_0": {}}, {"ace_instance_0": {"humidity": 14}})
    assert asyncio.run(m.heal_late_fields(now=100.0)) is True
    assert asyncio.run(m.heal_late_fields(now=130.0)) is False      # within 60 s: no query at all
    assert len(m.queried) == 1
    rinkhals = _moon({"mmu": {}}, {})
    assert asyncio.run(rinkhals.heal_late_fields(now=100.0)) is False and rinkhals.queried == []
