"""Sicht auf die ACE unter Klipper + ACEPRO (acemodel) - an einem echten Status vom 09.10.2026."""

import copy
import json

from conftest import DATA

from acebridge import acemodel

STATUS = json.loads((DATA / "acepro_status_2026-10-09.json").read_text())


def test_slots_aus_echtem_status():
    assert acemodel.num_slots(STATUS) == 4
    s0 = acemodel.slot(STATUS, 0)
    assert s0["present"] and s0["active"] and s0["rfid"]
    assert (s0["material"], s0["color"], s0["temperature"]) == ("PETG", "685BC7", 250)
    assert (s0["sku"], s0["tag_id"], s0["bed_temperature"]) == ("AHPEBK-34532", 34532, 75)
    s1 = acemodel.slot(STATUS, 1)
    assert s1["present"] and not s1["active"] and s1["color"] == "C52E79"
    s2 = acemodel.slot(STATUS, 2)
    assert not s2["present"] and s2["material"] == "" and s2["color"] == "" and s2["tag_id"] is None
    assert acemodel.slot(STATUS, 3)["temperature"] == 260


def test_aktiver_slot():
    assert acemodel.active_slot(STATUS) == 0
    st = copy.deepcopy(STATUS)
    st["ace"]["current_index"] = -1
    assert acemodel.active_slot(st) is None
    assert not acemodel.slot(st, 0)["active"]
    st["ace"]["current_index"] = 3
    assert acemodel.slot(st, 3)["active"]


def test_nicht_bereit_oder_getrennt_heisst_leer():
    assert not acemodel.slot(STATUS, 0, ready=False)["present"]
    st = copy.deepcopy(STATUS)
    st["ace_instance_0"]["connection_state"] = "disconnected"
    assert not acemodel.slot(st, 0)["present"]
    assert not acemodel.dryer(st)["present"]
    assert acemodel.slot({}, 0)["present"] is False


def test_spule_ohne_tag():
    st = copy.deepcopy(STATUS)
    st["ace_instance_0"]["slots"][1].update({"rfid": False, "sku": ""})
    s = acemodel.slot(st, 1)
    assert s["present"] and not s["rfid"] and s["tag_id"] is None and s["sku"] == ""


def test_trockner_und_feuchte():
    d = acemodel.dryer(STATUS)
    assert d["present"] and not d["drying"] and d["humidity"] == 7 and d["temp"] == 29
    st = copy.deepcopy(STATUS)
    st["ace_instance_0"]["dryer_status"] = {"status": "drying", "target_temp": 55, "duration": 600, "remain_time": 548}
    d = acemodel.dryer(st)
    assert d["drying"] and d["target_temp"] == 55
    assert d["remaining_min"] == 9.1 and d["duration_min"] == 10.0


def test_endlosspule_und_sensoren():
    assert acemodel.endless_spool(STATUS) == {"enabled": True, "mode": "exact"}
    s = acemodel.sensors(STATUS)
    assert s["toolhead"] is True and s["rdm"] is True and s["rdm_pulses"] == 5885


def test_hilfsfunktionen():
    assert acemodel.color_hex([104, 91, 199]) == "685BC7"
    assert acemodel.color_hex("#685bc7ff") == "685BC7"
    assert acemodel.color_hex(None) == ""
    assert acemodel.tag_number("AHPEBK-102") == 102
    assert acemodel.tag_number("") is None
