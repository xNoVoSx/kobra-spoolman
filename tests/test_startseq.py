"""Pause and cancel during the print start sequence (startseq.py, Klipper module kobra_seq): routing of the print
actions to printer.kobra_seq.control, state for the UIs and the action check."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import aiohttp

from acebridge import startseq
from acebridge.appapi import printer_state
from acebridge.control import ControlError, check_action
from acebridge.moonraker import SUBSCRIBE_OBJECTS, OPTIONAL_OBJECTS, Moonraker
from acebridge.status import messages


def seq(**kw):
    s = {"enabled": True, "active": True, "step": "_STARTSEQ_BED", "index": 0, "steps": 9, "paused": False,
         "requested": "", "paused_since": None, "seq": 1}
    s.update(kw)
    return {"print_stats": {"state": "printing"}, "kobra_seq": s}


def test_actions_go_to_kobra_seq_only_while_a_start_sequence_runs():
    assert startseq.route("printer.print.pause", seq()) == {"action": "pause"}
    assert startseq.route("printer.print.cancel", seq()) == {"action": "cancel"}
    assert startseq.route("printer.print.resume", seq(paused=True)) == {"action": "resume"}
    assert startseq.route("printer.emergency_stop", seq()) is None           # the emergency stop stays direct
    assert startseq.route("printer.print.pause", seq(active=False)) is None
    assert startseq.route("printer.print.pause", seq(enabled=False)) is None
    assert startseq.route("printer.print.pause", {"print_stats": {"state": "printing"}}) is None   # Rinkhals/old


def test_a_paused_start_sequence_counts_as_paused():
    assert startseq.print_state(seq(paused=True), "printing") == "paused"
    assert startseq.print_state(seq(), "printing") == "printing"
    assert startseq.print_state(seq(paused=True), "cancelled") == "cancelled"
    # resume is allowed, pause is not (already paused) - the same check as for a normal pause
    st = startseq.print_state(seq(paused=True), "printing")
    assert check_action("resume", st, False)[0] == "printer.print.resume"
    try:
        check_action("pause", st, False)
        raise AssertionError("pause while paused")
    except ControlError as e:
        assert e.status == 409


def test_ui_state_and_messages():
    p = printer_state(seq(paused=True), True, True, 1)
    assert p["state"] == "paused" and p["start_seq"]["paused"] is True
    assert p["message"] == "Start sequence paused"
    assert p["phase"].startswith("Start sequence paused")
    st = seq(paused=True)
    st["kobra_phase"] = {"enabled": True, "phase": "heat_bed", "seq": 1}
    st["heater_bed"] = {"temperature": 63.0, "target": 100.0}
    text = printer_state(st, True, True, 1)["phase"]
    assert text.startswith("Start sequence paused · ") and "100" in text, text
    p = printer_state(seq(requested="cancel"), True, True, 1)
    assert p["state"] == "printing" and p["start_seq"]["requested"] == "cancel"
    assert p["message"] == "cancels after this step"
    assert printer_state({"print_stats": {"state": "printing"}}, True, True, 1)["start_seq"] is None

    moon = SimpleNamespace(connected=True, klippy_ready=True, status=seq(paused=True))
    bridge = SimpleNamespace(moon=moon, clog=None, safety_warnings=lambda: [],
                             slots=SimpleNamespace(warnings=[], slots_view=lambda: [], unknown_tags={}, tag_events=[]),
                             usage=SimpleNamespace(open=[], history=[]), cfg=SimpleNamespace(),
                             sm=SimpleNamespace(connected=True), camera=SimpleNamespace(state=lambda: {}),
                             dryer=SimpleNamespace(state=lambda: {}))
    keys = [m["key"] for m in messages(bridge, [], 0.0)]
    assert "start_seq" in keys


def test_bridge_subscribes_kobra_seq():
    assert "kobra_seq" in OPTIONAL_OBJECTS and "kobra_seq" not in SUBSCRIBE_OBJECTS
    assert set(OPTIONAL_OBJECTS["kobra_seq"]) >= {"enabled", "active", "paused", "requested"}


def test_moonraker_action_sends_to_the_endpoint(cfg):
    async def go():
        async with aiohttp.ClientSession() as s:
            moon = Moonraker(cfg, s, None)
            calls = []

            async def fake_call(method, params=None, timeout=10, subscribe=False):
                calls.append((method, params))

            moon._ws = object()
            moon._call = fake_call
            moon.status = seq()
            await moon.action("printer.print.pause", "PAUSE", source="test")
            moon.status = {"print_stats": {"state": "printing"}}
            await moon.action("printer.print.pause", "PAUSE", source="test")
            return calls
    calls = asyncio.run(go())
    assert calls == [("printer.kobra_seq.control", {"action": "pause"}), ("printer.print.pause", None)]
