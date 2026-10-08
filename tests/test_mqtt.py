"""Home Assistant ueber MQTT: Inhalte, Discovery, nur Aenderungen senden, Raumsensor, Wiederverbinden."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from conftest import FakeMoonraker

from acebridge import mqtt as mq
from acebridge.mqtt import MqttBridge, room_reading


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class FakeClient:
    """Wie aiomqtt.Client: async with, publish, subscribe, messages."""

    def __init__(self, log, incoming=(), fail=None):
        self.log, self.incoming, self.fail = log, list(incoming), fail

    async def __aenter__(self):
        if self.fail:
            raise self.fail
        self.log.append(("connect",))
        return self

    async def __aexit__(self, *exc):
        self.log.append(("disconnect",))

    async def publish(self, topic, payload, retain=False):
        self.log.append(("pub", topic, payload, retain))

    async def subscribe(self, topic):
        self.log.append(("sub", topic))

    @property
    def messages(self):
        async def gen():
            for topic, payload in self.incoming:
                yield SimpleNamespace(topic=topic, payload=payload)
            await asyncio.Event().wait()
        return gen()


def cfg(**kw):
    base = dict(mqtt_host="broker", mqtt_port=1883, mqtt_user="", mqtt_password="", mqtt_prefix="kobra-spoolman",
                mqtt_discovery="homeassistant", room_sensor_topic="", room_rh=50.0)
    base.update(kw)
    return SimpleNamespace(**base)


def bridge(monkeypatch, **kw):
    moon = FakeMoonraker()
    moon.connected = True
    moon.merge({"print_stats": {"state": "printing", "filename": "teil.gcode", "print_duration": 600.0,
                                "info": {"current_layer": 3, "total_layer": 40}},
                "virtual_sdcard": {"progress": 0.25},
                "extruder": {"temperature": 219.6, "target": 220}, "heater_bed": {"temperature": 60.04, "target": 60},
                "ace_instance_0": {"humidity": 18, "temp": 31, "connection_state": "connected",
                                   "dryer_status": {"status": "stop"}}})
    slots = [{"slot": 1, "ace": {"present": True, "active": True, "material": "PETG", "color": "685BC7"},
              "spool": {"spool_id": 7, "display_name": "Sunlu PETG Lavendel", "material": "PETG", "color": "685BC7",
                        "remaining_weight": 812.4}},
             {"slot": 2, "ace": {"present": False, "active": False, "material": "", "color": ""}, "spool": None}]
    monkeypatch.setattr(mq, "notices", lambda b: {"messages": [{"level": "warn", "text": "Slot 1 feucht"}]})
    monkeypatch.setattr(mq, "printer_cpu", lambda b: 71.4)
    b = SimpleNamespace(
        cfg=cfg(**kw), moon=moon,
        slots=SimpleNamespace(slots_view=lambda: slots, num_gates=lambda: 4),
        dryer=SimpleNamespace(state=lambda: {"humidity": 18, "temp": 31, "drying": False, "target_temp": None,
                                             "remaining_min": None}),
        sm=SimpleNamespace(spool=lambda sid: {"id": sid}),
        moisture=SimpleNamespace(view=lambda sp: {"score": 120, "needs_drying": True}),
        vision=SimpleNamespace(configured=False))
    return b


def test_room_reading_formats():
    assert room_reading(b'{"humidity": 47.3, "temperature": 21.24, "battery": 90}') == (47.3, 21.2)
    assert room_reading(b"52") == (52.0, None)
    assert room_reading(b"kaputt") == (None, None)
    assert room_reading(b'{"temperature": 20}') == (None, 20.0)


def test_payloads(monkeypatch):
    m = MqttBridge(bridge(monkeypatch), clock=Clock())
    p = m.payloads()
    pr = p["printer"]
    assert pr["state"] == "printing" and pr["progress"] == 25.0 and pr["eta_min"] == 30
    assert pr["layer"] == 3 and pr["nozzle"] == 219.6 and pr["bed"] == 60.0 and pr["active_slot"] == 1 and pr["cpu"] == 71
    assert p["slot/1"] == {"spool": "Sunlu PETG Lavendel", "spool_id": 7, "material": "PETG", "color": "#685BC7",
                           "remaining_g": 812.0, "moisture": 120, "needs_drying": True, "loaded": True}
    assert p["slot/2"]["spool"] is None and p["slot/2"]["color"] is None
    assert p["ace"]["humidity"] == 18 and p["ace"]["drying"] is False
    assert p["notices"]["warnings"] == 1 and p["notices"]["top"] == "Slot 1 feucht"
    assert "vision" not in p


def test_offline_printer_state(monkeypatch):
    b = bridge(monkeypatch)
    b.moon.connected = False
    assert MqttBridge(b, clock=Clock()).payloads()["printer"]["state"] == "offline"


def test_discovery(monkeypatch):
    m = MqttBridge(bridge(monkeypatch), clock=Clock())
    d = dict(m.discovery())
    assert "homeassistant/sensor/kobra_spoolman_progress/config" in d
    assert "homeassistant/binary_sensor/kobra_spoolman_ace_drying/config" in d
    assert sum("slot" in t and t.endswith("_remaining/config") for t in d) == 4        # ein Satz pro Slot
    c = d["homeassistant/sensor/kobra_spoolman_ace_humidity/config"]
    assert c["state_topic"] == "kobra-spoolman/ace" and c["device_class"] == "humidity"
    assert c["availability_topic"] == "kobra-spoolman/status" and c["device"]["identifiers"] == ["kobra-spoolman"]
    assert len({v["unique_id"] for v in d.values()}) == len(d)
    assert MqttBridge(bridge(monkeypatch, mqtt_discovery=""), clock=Clock()).discovery() == []


def test_only_changes_are_sent(monkeypatch):
    b = bridge(monkeypatch)
    m = MqttBridge(b, clock=Clock())
    log = []
    c = FakeClient(log)
    assert asyncio.run(m.publish_changes(c)) == 5                         # printer, ace, 2 Slots, notices
    assert all(x[3] for x in log)                                         # alles retained
    assert asyncio.run(m.publish_changes(c)) == 0
    b.moon.merge({"extruder": {"temperature": 221.0}})
    log.clear()
    assert asyncio.run(m.publish_changes(c)) == 1 and log[0][1] == "kobra-spoolman/printer"
    assert asyncio.run(m.publish_changes(c, force=True)) == 5


def test_room_sensor_freshness(monkeypatch):
    clock = Clock()
    m = MqttBridge(bridge(monkeypatch, room_sensor_topic="zigbee2mqtt/Lager"), clock=clock)
    assert m.room_rh() is None
    m.on_room(b'{"humidity": 140}')                                       # unsinnig -> ignoriert
    assert m.room_rh() is None
    m.on_room(b'{"humidity": 44.5, "temperature": 20.1}')
    assert m.room_rh() == 44.5
    assert m.status_lines()[-1]["state"] == "ok" and "44,5 %" in m.status_lines()[-1]["detail"]
    clock.t += mq.ROOM_FRESH_S + 1
    assert m.room_rh() is None
    assert "rechne mit 50 %" in m.status_lines()[-1]["detail"]


def test_moisture_uses_measured_room(tmp_path):
    from acebridge.moisture import MoistureModel
    c = SimpleNamespace(data_dir=str(tmp_path), room_rh=50.0, dry_locations="Trockenbox=15")
    moon = FakeMoonraker()
    mm = MoistureModel(c, moon, SimpleNamespace(sm=SimpleNamespace(spools=[])))
    assert mm._env({"location": "Regal"}, None, {})[1] == 50.0
    mm.room_rh_measured = lambda: 38.0
    assert mm._env({"location": "Regal"}, None, {})[1] == 38.0
    assert mm._env({"location": "Trockenbox"}, None, {})[1] == 15.0        # eigener Lagerort bleibt


def test_disabled_without_host(monkeypatch):
    m = MqttBridge(bridge(monkeypatch, mqtt_host=""), clock=Clock())
    assert not m.enabled and m.status_lines() == []
    asyncio.run(m.run())                                                   # kehrt sofort zurueck


def test_run_connects_publishes_and_listens(monkeypatch):
    monkeypatch.setattr(mq, "MIN_GAP_S", 0.01)
    b = bridge(monkeypatch, room_sensor_topic="zigbee2mqtt/Lager")
    log, seen = [], {}

    def factory(host, port, **kw):
        seen.update(kw, host=host, port=port)
        return FakeClient(log, incoming=[("zigbee2mqtt/Lager", b'{"humidity": 41}')])
    m = MqttBridge(b, client_factory=factory, clock=Clock())

    async def go():
        t = asyncio.create_task(m.run())
        await asyncio.sleep(0.1)
        seen["connected"] = m.connected
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
    asyncio.run(go())
    assert seen["host"] == "broker" and seen["identifier"] == "kobra-spoolman-bridge"
    assert seen["will"].topic == "kobra-spoolman/status" and seen["will"].payload == "offline" and seen["will"].retain
    assert log[0] == ("connect",) and log[1] == ("pub", "kobra-spoolman/status", "online", True)
    assert ("sub", "zigbee2mqtt/Lager") in log
    assert any(x[0] == "pub" and x[1].startswith("homeassistant/") for x in log)
    assert seen["connected"] and m.room_rh() == 41.0
    state = json.loads(next(x[2] for x in log if x[0] == "pub" and x[1] == "kobra-spoolman/slot/1"))
    assert state["spool_id"] == 7


def test_run_retries_after_error(monkeypatch):
    monkeypatch.setattr(mq, "RECONNECT_S", 0.01)
    calls = []

    def factory(host, port, **kw):
        calls.append(1)
        return FakeClient([], fail=OSError("Verbindung abgelehnt"))
    m = MqttBridge(bridge(monkeypatch), client_factory=factory, clock=Clock())

    async def go():
        t = asyncio.create_task(m.run())
        await asyncio.sleep(0.1)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
    asyncio.run(go())
    assert len(calls) >= 3 and not m.connected
    assert m.status_lines()[0]["state"] == "warn" and "abgelehnt" in m.status_lines()[0]["detail"]


def test_clean_shutdown_reports_offline(monkeypatch):
    monkeypatch.setattr(mq, "MIN_GAP_S", 0.01)
    log = []
    m = MqttBridge(bridge(monkeypatch), client_factory=lambda h, p, **kw: FakeClient(log), clock=Clock())

    async def go():
        t = asyncio.create_task(m.run())
        await asyncio.sleep(0.05)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
    asyncio.run(go())
    pubs = [x for x in log if x[0] == "pub" and x[1] == "kobra-spoolman/status"]
    assert pubs[-1][2] == "offline" and pubs[-1][3] and not m.connected
