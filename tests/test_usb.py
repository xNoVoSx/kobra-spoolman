"""USB tunnel watchdog (acebridge/usb.py): state from Moonraker's database, status line, message, switches."""

from __future__ import annotations

import asyncio

import pytest

from acebridge.switches import SwitchError, Switches
from acebridge.usb import NS, UsbError, UsbTunnel

NOW = 1_800_000_000.0


class Moon:
    def __init__(self, state=None):
        self.connected = True
        self.klippy_ready = True
        self.status = {}
        self.db = {(NS, "state"): state} if state is not None else {}
        self.reads = 0

    async def db_get(self, ns, key):
        self.reads += 1
        return self.db.get((ns, key))

    async def db_post(self, ns, key, value):
        self.db[(ns, key)] = value


def watcher_state(**kw):
    st = {"state": "configured", "present": True, "tries": 0, "max_tries": 10, "gave_up": False, "restarts": 0,
          "max_speed": "super-speed-plus", "switches": {"watch": True, "auto_restart": True, "full_speed": False},
          "events": [{"at": NOW - 5, "text": "Gadget: default -> configured"}], "at": NOW - 10}
    st.update(kw)
    return st


def make(state=None, mono=None):
    moon = Moon(state)
    t = [0.0] if mono is None else mono
    usb = UsbTunnel(moon, clock=lambda: NOW, mono=lambda: t[0])
    asyncio.run(usb.tick())
    return moon, usb, t


def test_no_watcher_shows_nothing():
    _moon, usb, _ = make()
    assert not usb.available() and usb.items() == [] and usb.message() is None


def test_reads_every_30_s_only():
    moon, usb, t = make(watcher_state())
    asyncio.run(usb.tick())
    assert moon.reads == 1
    t[0] = 31
    asyncio.run(usb.tick())
    assert moon.reads == 2
    asyncio.run(usb.tick(force=True))
    assert moon.reads == 3


@pytest.mark.parametrize("kw,state,text", [
    ({}, "ok", "connected"),
    ({"max_speed": "full-speed"}, "ok", "12 Mbit/s"),
    ({"state": "not attached", "present": False}, "off", "Printer off"),
    ({"state": "default", "tries": 3}, "warn", "attempt 3/10"),
    ({"state": "default", "tries": 10, "gave_up": True}, "bad", "check the cable"),
    ({"at": NOW - 600}, "warn", "Watchdog not reporting"),
])
def test_summary(kw, state, text):
    _moon, usb, _ = make(watcher_state(**kw))
    s = usb.summary()
    assert s["state"] == state and text in s["detail"]


def test_message_only_when_given_up():
    _m, usb, _ = make(watcher_state(state="default", tries=10, gave_up=True))
    assert "check the cable" in usb.message()
    _m, usb, _ = make(watcher_state(state="default", tries=2))
    assert usb.message() is None


def test_switches_listed_and_set():
    moon, usb, _ = make(watcher_state())
    sw = Switches(moon, usb)
    keys = {i["key"]: i for i in sw.view()["items"]}
    assert keys["usb_watch"]["on"] is True and keys["usb_full_speed"]["on"] is False
    assert all(keys[k]["group"] == "system" for k in ("usb_watch", "usb_auto_restart", "usb_full_speed"))
    assert "system" in [g["key"] for g in sw.view()["groups"]]
    asyncio.run(sw.set("usb_full_speed", True))
    assert moon.db[(NS, "switches")] == {"watch": True, "auto_restart": True, "full_speed": True}
    assert {i["key"]: i for i in sw.view()["items"]}["usb_full_speed"]["on"] is True   # sofort sichtbar


def test_switch_errors():
    moon, usb, _ = make(watcher_state())
    sw = Switches(moon, usb)
    with pytest.raises(SwitchError) as e:
        asyncio.run(sw.set("usb_watch", "ja"))
    assert e.value.status == 400
    with pytest.raises(UsbError):
        asyncio.run(usb.set("usb_quatsch", True))
    moon2, dead, _ = make(watcher_state(at=NOW - 999))
    assert dead.items() == []
    with pytest.raises(UsbError) as e:
        asyncio.run(dead.set("usb_watch", False))
    assert e.value.status == 503 and (NS, "switches") not in moon2.db


def test_status_line_and_notice(cfg):
    from test_appapi import FakeBridge

    from acebridge.status import notices
    b = FakeBridge(cfg)
    b.moon.merge({"print_stats": {"state": "standby"}})
    st = watcher_state(state="default", tries=10, gave_up=True)
    b.usb = UsbTunnel(b.moon, clock=lambda: NOW)
    b.usb.state = st
    n = notices(b, NOW)
    line = {x["key"]: x for x in n["status"]}["usb"]
    assert line["state"] == "bad" and line["label"] == "USB tunnel"
    assert any(m["key"] == "usb" and "cable" in m["text"] for m in n["messages"])
    b.usb.state = watcher_state()
    n = notices(b, NOW)
    assert {x["key"]: x for x in n["status"]}["usb"]["state"] == "ok"
    assert not any(m["key"] == "usb" for m in n["messages"])


def test_app_state_carries_usb(cfg):
    """/api/app/state: field usb (web card, app) - None without a watchdog; switching via /api/switch."""
    from test_appapi import FakeBridge
    from aiohttp.test_utils import TestClient, TestServer

    from acebridge.web import build_app
    cfg.app_token = "geheim"
    b = FakeBridge(cfg)
    b.usb = UsbTunnel(b.moon, clock=lambda: NOW)

    async def get():
        async with TestClient(TestServer(build_app(b))) as client:
            resp = await client.get("/api/app/state", headers={"Authorization": "Bearer geheim"})
            return (await resp.json())["usb"]
    assert asyncio.run(get()) is None
    b.usb.state = watcher_state(state="default", tries=2)
    usb = asyncio.run(get())
    assert usb["state"] == "warn" and usb["switches"]["watch"] is True and usb["events"]


def test_nothing_on_rinkhals():
    moon = Moon(watcher_state())
    moon.platform = "rinkhals"                  # stock firmware: no USB tunnel, even if a namespace is left over
    usb = UsbTunnel(moon, clock=lambda: NOW, mono=lambda: 0.0)
    asyncio.run(usb.tick())
    assert not usb.available() and usb.items() == [] and moon.reads == 0
