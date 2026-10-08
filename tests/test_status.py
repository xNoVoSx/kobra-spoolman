"""Meldungen und Status der Uebersicht (status.py) und Restverbrauch aus der Druckdatei (render.py)."""

from __future__ import annotations

import time

import pytest
from conftest import ace_status
from test_appapi import FakeBridge

from acebridge.render import parse_bytes
from acebridge.status import file_usage, notices, spool_reach


def two_tool_gcode() -> bytes:
    """T0 druckt 100 mm (mit Rueckzug), Wechsel auf T1 (50 mm), zurueck auf T0 (30 mm). Vor jedem T die Spuelmenge
    des Orca-Spuelskripts (ACE_SET_PURGE_AMOUNT) - vor dem ersten T keine."""
    lines = ["M83", "T0", "G1 X0 Y0", "G1 X10 Y0 E60", "G1 E-2", "G1 E2", "G1 X20 Y0 E40",
             "ACE_SET_PURGE_AMOUNT PURGELENGTH=120.50", "T1", "G1 X30 Y0 E50",
             "ACE_SET_PURGE_AMOUNT PURGELENGTH=60", "T0", "G1 X40 Y0 E30"]
    return ("\n".join(lines) + "\n").encode()


def test_model_counts_per_tool_and_remaining():
    data = two_tool_gcode()
    m = parse_bytes(data)
    assert m.e_total == pytest.approx({0: 130.0, 1: 50.0})           # Rueckzug und Wiederansetzen heben sich auf
    assert [(s, d, p) for _, s, d, p in m.changes] == [(None, 0, None), (0, 1, 120.5), (1, 0, 60.0)]
    rest, later = m.remaining(0)
    assert rest == pytest.approx({0: 130.0, 1: 50.0})
    assert later == [(None, 0, None), (0, 1, 120.5), (1, 0, 60.0)]
    after_t1 = data.index(b"T1") + 3                                 # Position hinter "T1\n"
    rest, later = m.remaining(after_t1)
    assert rest == pytest.approx({0: 30.0, 1: 50.0}) and later == [(1, 0, 60.0)]


@pytest.fixture
def bridge(cfg):
    cfg.app_token = "geheim"
    b = FakeBridge(cfg)
    b.moon.merge({"print_stats": {"state": "printing", "filename": "x.gcode"},
                  "virtual_sdcard": {"file_position": 0},
                  **ace_status([{"material": "PETG", "color": "685BC7"}, {"material": "PETG", "color": "EC008C"}])})
    b.preview.model, b.preview.status = parse_bytes(two_tool_gcode()), "ready"
    return b


def test_spool_reach_and_warning(bridge):
    reach = {r["slot"]: r for r in spool_reach(bridge)}
    assert reach[1]["enough"] is True and reach[1]["have_g"] == 978
    # T1 -> Slot 2 hat keine Spule: Hinweis statt Rechnung
    assert reach[2]["need_g"] is None and reach[2]["enough"] is None
    msgs = notices(bridge)["messages"]
    assert any(m["key"] == "reach2" and "keine Spule" in m["text"] for m in msgs)

    bridge.sm.spools[0]["remaining_weight"] = 0.2                     # Spule 1 fast leer
    msgs = notices(bridge)["messages"]
    keys = [m["key"] for m in msgs]
    assert "reach1" in keys and "low1" in keys
    levels = [m["level"] for m in msgs]
    assert levels == sorted(levels, key=["error", "warn", "info"].index)    # nach Wichtigkeit sortiert


def test_reach_includes_load_and_purge_of_coming_changes(bridge):
    """Je kommendem Wechsel: 85 mm Laden bis zur Duese + Spuelmenge aus der Datei (sonst 50 mm)."""
    from acebridge.status import _slot_need
    need = _slot_need(bridge, 0)
    assert need[0] == pytest.approx(130 + (85 + 50) + (85 + 60))      # Start (ohne Angabe) + Wechsel zurueck
    assert need[1] == pytest.approx(50 + 85 + 120.5)


def test_file_usage_lists_used_slots(bridge):
    uses = {u["slot"]: u for u in file_usage(bridge)}
    assert set(uses) == {1, 2}                                         # Slot 3/4 benutzt die Datei nicht
    assert uses[1]["total_mm"] >= 130 and uses[1]["total_g"] > 0 and uses[1]["color"]
    assert uses[1]["rest_mm"] == uses[1]["total_mm"]                   # Position 0: noch alles offen
    bridge.moon.merge({"virtual_sdcard": {"file_position": 10 ** 6}})
    assert file_usage(bridge)[0]["rest_mm"] < uses[1]["total_mm"]     # weiter hinten weniger offen (Stuetzstellen)
    bridge.moon.merge({"print_stats": {"state": "complete"}})
    assert file_usage(bridge) == []


def test_no_reach_without_print_or_model(bridge):
    bridge.preview.status = "loading"
    assert spool_reach(bridge) == []
    bridge.preview.status = "ready"
    bridge.moon.merge({"print_stats": {"state": "complete"}})
    assert spool_reach(bridge) == []


def test_messages_for_printer_states(bridge):
    bridge.moon.merge({"print_stats": {"state": "paused", "message": "Filament leer"}})
    first = notices(bridge)["messages"][0]
    assert first["level"] == "error" and first["text"] == "Druck pausiert: Filament leer"
    bridge.moon.connected = False
    assert notices(bridge)["messages"][0]["key"] == "printer"
    st = {s["key"]: s for s in notices(bridge)["status"]}
    assert st["printer"]["state"] == "bad" and st["spoolman"]["state"] == "ok"


def test_status_shows_devices_and_camera(bridge):
    now = time.time()
    bridge.devices.devices = [{"id": "a", "name": "S26", "kind": "app", "last_seen": now - 30},
                              {"id": "b", "name": "werkstatt", "kind": "plugin", "last_seen": now - 3600}]
    st = {s["key"]: s for s in notices(bridge, now)["status"]}
    assert st["app"]["state"] == "ok" and st["app"]["detail"] == "S26"
    assert st["plugin"]["state"] == "off"
    assert st["camera"]["state"] == "ok"


def test_recent_print_and_humidity_info(bridge):
    bridge.moon.merge({"print_stats": {"state": "complete"}})
    ended = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 300))
    bridge.usage.history = [{"file": "wuerfel.gcode", "ended": ended, "state": "complete", "slots": []}]
    bridge.moon.merge({"filament_hub": {"filament_hubs": [{"humidity": 40, "dryer_status": {"status": "stop"}}]}})
    msgs = {m["key"]: m for m in notices(bridge)["messages"]}
    assert msgs["done"]["text"].startswith("Druck fertig: wuerfel.gcode")
    assert msgs["humidity"]["level"] == "info"


def test_printer_cpu_is_a_status_line_never_a_message(bridge):
    import collections

    from acebridge.moonraker import Moonraker
    now = time.monotonic()
    m = Moonraker.__new__(Moonraker)                      # nur die CPU-Hilfen, ohne Verbindung
    m.cpu_samples = collections.deque([(now - 70 + i, 98.0) for i in range(70)])
    bridge.moon.cpu, bridge.moon.cpu_samples = m.cpu, m.cpu_samples
    n = notices(bridge)
    st = {s["key"]: s for s in n["status"]}
    assert st["cpu"]["state"] == "bad" and st["cpu"]["detail"] == "98 %"
    assert not any(x["key"] == "cpu" for x in n["messages"])   # im Druck laesst sich daran nichts aendern
    m.cpu_samples.clear()
    m.cpu_samples.extend([(now - 3, 85.0), (now - 1, 87.0)])     # normal im Druck
    assert {s["key"]: s for s in notices(bridge)["status"]}["cpu"]["state"] == "ok"
