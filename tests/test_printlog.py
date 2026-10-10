"""Druck-Aufzeichnung mit Konsole (telemetry.py) und lesbares Druckprotokoll (printlog.py)."""

from __future__ import annotations

from types import SimpleNamespace

from acebridge import printlog
from acebridge.console import Console
from acebridge.telemetry import Recorder


def status(state, **extra):
    st = {"print_stats": {"state": state, "filename": "teil_ASA.gcode", "filament_used": 0.0},
          "ace": {"current_index": 0, "target_index": -1}, "extruder": {"target": 187.5},
          "ace_instance_0": {"slots": [{"material": "PETG", "color": "685BC7", "temp": 250, "status": "ready"}]}}
    for k, v in extra.items():
        st.setdefault(k, {}).update(v)
    return st


def test_console_lines_recorded_and_rendered(tmp_path):
    cfg = SimpleNamespace(data_dir=str(tmp_path), telemetry=True, telemetry_keep=5)
    rec = Recorder(cfg)
    con = Console()
    con.listeners.append(rec.on_console)
    con.add("response", "vor dem Druck - nicht aufzeichnen")
    st = status("printing")
    rec.on_status({}, True, st)                                   # Aufzeichnung beginnt
    con.add("response", "echo: Hot wipe before Z homing (187C, geladenes Filament)...")
    con.add("response", "B:112.0 /110.0 T0:237.9 /255.0")      # Temperatur-Spam: nicht
    con.add("response", "ok B:112.0 /110.0 T0:240 /255.0")
    st["ace"]["target_index"] = 3
    rec.on_status({"ace": {"target_index": 3}}, False, st)
    con.add("command", "KOBRA_PA_AUTO T=3", "Klipper")
    con.add("error", "Auto-PA: Messung T3 fehlgeschlagen")
    st["kobra_pa"] = {"measuring": True}
    rec.on_status({"kobra_pa": {"measuring": True}}, False, st)
    st["print_stats"]["info"] = {"current_layer": 3, "total_layer": 42}
    rec.on_status({"print_stats": {"info": {"current_layer": 3, "total_layer": 42}}}, False, st)
    st["print_stats"]["state"] = "complete"
    rec.on_status({"print_stats": {"state": "complete"}}, False, st)
    rec._close(st)
    name = rec.list_files()[0]["name"]
    raw = (tmp_path / "telemetry" / name).read_text()
    assert "vor dem Druck" not in raw and "B:112" not in raw and "Hot wipe" in raw
    text = printlog.render(raw.splitlines())
    lines = text.splitlines()
    assert lines[0] == "Druckprotokoll: teil_ASA.gcode" and "Slot 1: PETG 685BC7 250°C ready" in text
    order = [i for i, line in enumerate(lines) for key in ("Hot wipe", "Wechsel nach T: 3", "> KOBRA_PA_AUTO T=3",
                                                           "!! Auto-PA", "Auto-PA misst: True", "Schicht 3/42",
                                                           "Druckstatus: complete") if key in line]
    assert len(order) == 7 and order == sorted(order)             # alles da, in zeitlicher Reihenfolge
    assert "Ende: complete" in text


def test_render_tolerates_garbage_and_old_files():
    text = printlog.render(["kaputt", '{"t": 0, "type": "start", "status": {}}',
                            '{"t": 5, "type": "console", "kind": "response", "text": "hallo"}'])
    assert "+     5.0s    hallo" in text                            # ohne Startzeit: relative Zeit
