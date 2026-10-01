"""Meldungen und Status der Uebersicht (status.py) und Restverbrauch aus der Druckdatei (render.py)."""

from __future__ import annotations

import time

import pytest
from test_appapi import FakeBridge

from acebridge.render import parse_bytes
from acebridge.status import notices, spool_reach


def two_tool_gcode() -> bytes:
    """T0 druckt 100 mm (mit Rueckzug), Wechsel auf T1 (50 mm), zurueck auf T0 (30 mm)."""
    lines = ["M83", "T0", "G1 X0 Y0", "G1 X10 Y0 E60", "G1 E-2", "G1 E2", "G1 X20 Y0 E40",
             "T1", "G1 X30 Y0 E50",
             "T0", "G1 X40 Y0 E30"]
    return ("\n".join(lines) + "\n").encode()


def test_model_counts_per_tool_and_remaining():
    data = two_tool_gcode()
    m = parse_bytes(data)
    assert m.e_total == pytest.approx({0: 130.0, 1: 50.0})           # Rueckzug und Wiederansetzen heben sich auf
    assert [(s, d) for _, s, d in m.changes] == [(None, 0), (0, 1), (1, 0)]
    rest, later = m.remaining(0)
    assert rest == pytest.approx({0: 130.0, 1: 50.0}) and later == [(None, 0), (0, 1), (1, 0)]
    after_t1 = data.index(b"T1") + 3                                 # Position hinter "T1\n"
    rest, later = m.remaining(after_t1)
    assert rest == pytest.approx({0: 30.0, 1: 50.0}) and later == [(1, 0)]


@pytest.fixture
def bridge(cfg):
    cfg.app_token = "geheim"
    b = FakeBridge(cfg)
    b.moon.merge({"print_stats": {"state": "printing", "filename": "x.gcode"},
                  "virtual_sdcard": {"file_position": 0},
                  "mmu": {"gate_color": ["685BC7FF", "EC008CFF", "", ""], "ttg_map": [0, 1, 2, 3]}})
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


def test_reach_includes_purge_of_coming_changes(bridge):
    need_without = spool_reach(bridge)[0]["need_mm"]
    bridge.purge.first_load_mm = 0
    assert spool_reach(bridge)[0]["need_mm"] < need_without            # erster Ladevorgang zaehlt mit


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
