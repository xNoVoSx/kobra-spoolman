"""View of the ACE under Rinkhals (acemodel): mmu from Rinkhals' mmu_ace.py and GoKlipper's filament_hub, in the shape
documented in docs/findings.md (Kobra S1, Rinkhals 20260901_01, firmware 2.7.2.7)."""

from __future__ import annotations

import ast
import shlex

from acebridge import acemodel


def rinkhals_status(**mmu):
    m = {"enabled": True, "num_gates": 4, "gate": 1, "tool": 1, "action": "Idle",
         "gate_status": [1, -1, 0, 1],
         "gate_material": ["PETG", "PLA", "Unknown", "PLA Silk"],
         "gate_color": ["685BC7FF", "EFF0F1FF", "000000FF", "52D2BCFF"],
         "gate_filament_name": ["PETG", "PLA", "Unknown", "Anycubic PLA Silk"],
         "gate_vendor": ["", "", "", "Anycubic"],
         "gate_temperature": [245, 210, -1, 215],
         "gate_spool_id": [0, 0, 0, 102],
         "ttg_map": [0, 1, 2, 3]}
    m.update(mmu)
    hub = {"filament_hubs": [{"id": 0, "status": "ready", "temp": 33, "humidity": 24,
                              "filament_model": "Anycubic Color Engine Pro 2.0", "enable_rfid": 1,
                              "dryer_status": {"status": "drying", "target_temp": 55, "duration": 360,
                                               "remain_time": 21540},
                              "slots": [{"index": 0, "rfid": 1}, {"index": 1, "rfid": 1}, {"index": 2, "rfid": 1},
                                        {"index": 3, "rfid": 2}]}]}
    return {"mmu": m, "filament_hub": hub, "print_stats": {"state": "standby"}}


def test_variant_from_the_status():
    assert acemodel.variant(rinkhals_status()) == acemodel.RINKHALS
    assert acemodel.variant({"ace_instance_0": {"slots": []}}) == acemodel.ACEPRO
    assert acemodel.variant({"print_stats": {}}) is None
    assert acemodel.touches({"filament_hub": {}}) and not acemodel.touches({"print_stats": {}})


def test_slots():
    st = rinkhals_status()
    assert acemodel.connected(st) and acemodel.num_slots(st) == 4
    s0, s1, s2, s3 = (acemodel.slot(st, i) for i in range(4))
    assert s0["present"] and not s0["active"] and s0["material"] == "PETG" and s0["color"] == "685BC7"
    assert s0["temperature"] == 245 and not s0["rfid"] and s0["tag_id"] is None
    assert s1["active"] and acemodel.active_slot(st) == 1 and acemodel.consuming_slot(st) == 1
    assert not s2["present"] and s2["material"] == "" and s2["temperature"] is None
    assert s3["rfid"] and s3["tag_id"] == 102 and s3["vendor"] == "Anycubic"
    assert acemodel.slot(st, 0, ready=False)["present"] is False


def test_active_gate_without_gate_status_uses_gate():
    st = rinkhals_status(gate_status=None, gate=2)
    assert acemodel.active_slot(st) == 2
    assert acemodel.active_slot(rinkhals_status(gate_status=[1, 1, 1, 1], gate=2)) is None   # gate flickers


def test_dryer_from_filament_hub():
    d = acemodel.dryer(rinkhals_status())
    assert d["present"] and d["drying"] and d["humidity"] == 24 and d["temp"] == 33
    assert d["target_temp"] == 55 and d["duration_min"] == 360 and d["remaining_min"] == 359.0
    assert d["model"] == "Anycubic Color Engine Pro 2.0"


def test_dryer_without_filament_hub_uses_rinkhals_view():
    st = rinkhals_status()
    del st["filament_hub"]
    st["mmu_machine"] = {"unit_0": {"dryer_status": "stop", "dryer_temp": 30, "dryer_humidity": 0}}
    d = acemodel.dryer(st)
    assert d["present"] and not d["drying"] and d["humidity"] is None and d["temp"] == 30


def test_changing_and_tool_map():
    st = rinkhals_status(action="Loading", ttg_map=[3, 1, 2, 0])
    assert acemodel.changing(st) == "Loading"
    assert acemodel.changing(rinkhals_status()) is None
    assert acemodel.tool_slot(st, 0) == 3 and acemodel.tool_slot(st, 1) == 1
    assert acemodel.target_slot(st) is None


def test_slot_command_is_mmu_gate_map():
    st = rinkhals_status()
    cmd = acemodel.set_slot_command(st, 0, 8, "PETG", "685BC7", 245, name='Sunlu "PETG" {x}')
    name, arg = shlex.split(cmd)
    assert name == "MMU_GATE_MAP" and arg.startswith("MAP=")
    entry = ast.literal_eval(arg[4:])[0]           # Rinkhals parses it exactly like this
    assert entry == {"status": 1, "name": "Sunlu PETG x", "material": "PETG", "color": "685BC7FF", "temp": 245,
                     "spool_id": 8, "speed_override": 100}
    assert acemodel.set_slot_command(st, 0, 8, "", "685BC7", 245) is None


def test_slot_command_acepro_unchanged():
    st = {"ace_instance_0": {"slots": []}}
    assert acemodel.set_slot_command(st, 1, 8, "PLA", "FF0000", 210) == "ACE_SET_SLOT T=1 MATERIAL=PLA COLOR=255,0,0 TEMP=210"
    assert acemodel.set_slot_command(st, 1, 8, "PLA", "FF0000", 0) is None      # ACEPRO needs TEMP


def test_dryer_commands():
    assert acemodel.dryer_start_command(rinkhals_status(), 55, 360) == "MMU_DRYER_START UNIT=0 DURATION=360 TEMP=55"
    assert acemodel.dryer_stop_command(rinkhals_status()) == "MMU_DRYER_STOP UNIT=0"
    st = {"ace_instance_0": {}}
    assert acemodel.dryer_start_command(st, 55, 360) == "ACE_START_DRYING TEMP=55 DURATION=360"
    assert acemodel.dryer_stop_command(st) == "ACE_STOP_DRYING"


def with_current(st, cur):
    st["filament_hub"]["current_filament"] = cur
    return st


def test_active_slot_from_current_filament():
    """Recorded on the printer 13.10. (load slot 3): GoKlipper rolls every slot back (gate_status -1 one after the
    other), feeds slot 3, then all slots are 'ready' (gate_status 1, gate -1) and only current_filament says '0-2'."""
    idle = with_current(rinkhals_status(gate_status=[1, 1, 1, 1], gate=-1, tool=-1), "0-2")
    assert acemodel.active_slot(idle) == 2
    assert [acemodel.slot(idle, i)["active"] for i in range(4)] == [False, False, True, False]
    rollback = with_current(rinkhals_status(gate_status=[-1, 1, 1, 1], gate=-1), "")
    assert acemodel.active_slot(rollback) is None and not acemodel.slot(rollback, 0)["active"]
    assert acemodel.slot(rollback, 0)["present"]                     # busy, but the spool is still there
    feeding = with_current(rinkhals_status(gate_status=[1, 1, -1, 1], gate=-1), "")
    assert acemodel.active_slot(feeding) is None
    flicker = with_current(rinkhals_status(gate_status=[1, 1, -1, 1], gate=-1), "0-2")   # assisting after load
    assert acemodel.active_slot(flicker) == 2


def test_current_filament_parsing():
    for cur, want in (("0-0", 0), ("0-3", 3), ("1-1", 5), ("", None), ("0-4", None), ("x-1", None), ("2", None)):
        assert acemodel._hub_slot(cur) == want, cur
