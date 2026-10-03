"""Pruefung beim Druckstart: Slots gegen die Druckdatei (Material, Farbe, Spule, Feuchte)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from conftest import FakeMoonraker

from acebridge.printcheck import PrintGuard, check, colour_distance
from acebridge.render import parse_bytes


GCODE = "\n".join([
    "M83", "T0", "G1 Z0.2", "G1 X10 Y10 E1", "G1 X20 Y10 E1",
    "T1", "G1 X30 Y30 E1", "G1 X40 Y30 E1",
    "; filament_type = PLA;PETG;PLA",
    "; filament_colour = #FFFFFF;#685BC7;#000000",
]).encode() + b"\n"


class Slots:
    def __init__(self, moon, assigned):
        self.moon, self.assigned = moon, assigned

    def assignments(self):
        return self.assigned, []

    def ace_gate(self, gate):
        m = self.moon.status["mmu"]
        st = m["gate_status"][gate]
        return {"present": st != 0, "material": m["gate_material"][gate], "color": m["gate_color"][gate][:6]}


def spool(sid, material, colour, name="X"):
    return {"id": sid, "filament": {"name": name, "material": material, "color_hex": colour}}


def bridge(gates, assigned, wet=(), action="warn"):
    moon = FakeMoonraker()
    moon.merge({"print_stats": {"state": "printing", "filename": "teil.gcode"},
                "mmu": {"ttg_map": [0, 1, 2, 3], "gate_status": [g[0] for g in gates],
                        "gate_material": [g[1] for g in gates], "gate_color": [g[2] for g in gates]}})
    sent = []

    async def act(method, label, source="Bridge", timeout=30):
        sent.append((method, source))
    moon.action = act
    model = parse_bytes(GCODE)
    moisture = SimpleNamespace(view=lambda sp: {"needs_drying": sp["id"] in wet, "score": 140 if sp["id"] in wet else 20,
                                                "hours_needed": 6.0})
    b = SimpleNamespace(moon=moon, preview=SimpleNamespace(model=model, status="ready"), slots=Slots(moon, assigned),
                        moisture=moisture, cfg=SimpleNamespace(wet_print_action=action))
    return b, sent


def test_everything_fits_gives_no_issue():
    b, _ = bridge([(1, "PLA", "FFFFFFFF"), (1, "PETG", "685BC7FF"), (1, "PLA", "000000FF"), (0, "", "000000FF")],
                  {1: spool(1, "PLA", "FFFFFF"), 2: spool(2, "PETG", "685BC7")})
    assert check(b) == []                                    # Werkzeug 2 wird nicht benutzt -> egal


def test_wrong_material_colour_empty_and_missing_spool():
    b, _ = bridge([(1, "PETG", "000000FF"), (0, "", "000000FF"), (1, "PLA", "000000FF"), (0, "", "000000FF")],
                  {1: spool(1, "PETG", "000000")})
    kinds = {(i["slot"], i["kind"], i["level"]) for i in check(b)}
    assert (1, "material", "error") in kinds and (1, "colour", "warn") in kinds and (2, "empty", "error") in kinds
    b, _ = bridge([(1, "PLA", "FFFFFFFF"), (1, "PETG", "685BC7FF"), (0, "", ""), (0, "", "")], {1: spool(1, "PLA", "FFFFFF")})
    assert [(i["slot"], i["kind"]) for i in check(b)] == [(2, "nospool")]


def test_wet_spool_warns_and_pauses_only_when_set():
    gates = [(1, "PLA", "FFFFFFFF"), (1, "PETG", "685BC7FF"), (0, "", ""), (0, "", "")]
    assigned = {1: spool(1, "PLA", "FFFFFF"), 2: spool(2, "PETG", "685BC7", "PETG Lavendel")}
    b, sent = bridge(gates, assigned, wet={2})
    issues = check(b)
    assert [(i["slot"], i["kind"], i["level"]) for i in issues] == [(2, "wet", "error")] and "~6 h" in issues[0]["text"]
    g = PrintGuard(b)
    asyncio.run(g.tick())
    assert sent == []                                         # Standard: nur warnen
    b, sent = bridge(gates, assigned, wet={2}, action="pause")
    g = PrintGuard(b)
    asyncio.run(g.tick())
    asyncio.run(g.tick())
    assert sent == [("printer.print.pause", "Druckstart-Prüfung")]   # einmal je Druck


def test_not_printing_or_file_not_read_yet():
    b, _ = bridge([(0, "", "")] * 4, {})
    b.preview.status = "loading"
    assert check(b) == []
    b.preview.status = "ready"
    b.moon.status["print_stats"]["state"] = "standby"
    assert check(b) == []


def test_colour_distance():
    assert colour_distance("FFFFFF", "#ffffff") == 0 and colour_distance("FFFFFF", "000000") > 400
    assert colour_distance(None, "FFFFFF") is None
