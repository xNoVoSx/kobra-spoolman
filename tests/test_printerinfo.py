"""Printer and ACE model for the UIs (printerinfo.py) instead of a fixed "Kobra S1"."""

from __future__ import annotations

import asyncio

from conftest import FakeMoonraker

from acebridge.printerinfo import PrinterInfo, ace_model, model_from_gcode_tail


def _moon():
    moon = FakeMoonraker()
    moon._headers = lambda: {}
    return moon


TAIL = """; filament_type = PLA;PLA
; printer_model = Anycubic Kobra 3
; printer_settings_id = Anycubic Kobra 3 0.4 nozzle - Z-0.04
; CONFIG_BLOCK_END
"""


def test_model_from_the_print_files_tail():
    assert model_from_gcode_tail(TAIL) == "Kobra 3"
    assert model_from_gcode_tail("; printer_model = Anycubic Kobra S1\n") == "Kobra S1"
    assert model_from_gcode_tail("; printer_model = Voron 2.4\n") == "Voron 2.4"
    assert model_from_gcode_tail("G1 X1\n; layer_height = 0.2\n") is None


def test_ace_model_from_the_driver():
    assert ace_model({"ace_instance_0": {"model": "ACE2 (USB Single Serial)"}}) == "ACE 2 Pro"     # ACEPRO, S1
    assert ace_model({"filament_hub": {"filament_hubs": [{"filament_model": "Anycubic Color Engine Pro"}]}}) \
        == "ACE Pro"                                                                            # Rinkhals, Kobra 3
    assert ace_model({"filament_hub": {"filament_hubs": [{"id": 0}]}}) is None                 # Rinkhals, S1
    assert ace_model({}) is None


class _Resp:
    def __init__(self, status, body):
        self.status, self._body = status, body
        self.content = self

    async def read(self, n=-1):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Session:
    def __init__(self, status=206, body=TAIL.encode()):
        self.status, self.body, self.calls = status, body, []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers))
        return _Resp(self.status, self.body)


def _learn(info, status):
    async def go():
        info.watch(status)
        await info._task
    asyncio.run(go())


PRINTING = {"print_stats": {"state": "printing", "filename": "steam frame.gcode"}}


def test_learns_the_model_at_a_print_start_and_keeps_it(cfg):
    moon, session = _moon(), _Session()
    info = PrinterInfo(cfg, moon, session)
    assert info.view({})["printer_name"] is None             # nothing known yet: the UI says "Printer"
    _learn(info, PRINTING)
    url, headers = session.calls[0]
    assert url.endswith("/server/files/gcodes/steam%20frame.gcode") and headers["Range"].startswith("bytes=-")
    assert info.view({})["printer_name"] == "Kobra 3"
    assert PrinterInfo(cfg, moon, None).view({})["printer_name"] == "Kobra 3"      # survives a restart
    info.watch(PRINTING)                                     # same file: not read again
    assert len(session.calls) == 1


def test_never_downloads_a_whole_file(cfg):
    """A server without range support answers 200 with the whole file - the bridge does not read it."""
    info = PrinterInfo(cfg, _moon(), _Session(status=200))
    _learn(info, PRINTING)
    assert info.view({})["printer_name"] is None


def test_the_setting_wins(cfg):
    cfg.printer_name = "Werkstatt-Kobra"
    info = PrinterInfo(cfg, _moon(), _Session())
    _learn(info, PRINTING)
    assert info.view({})["printer_name"] == "Werkstatt-Kobra" and info.name() == "Werkstatt-Kobra"


def test_learns_from_the_last_print_while_nothing_is_known(cfg):
    """Right after an update: the printer is idle, but Klipper still names the last print's file."""
    session = _Session()
    info = PrinterInfo(cfg, _moon(), session)
    _learn(info, {"print_stats": {"state": "complete", "filename": "steam frame.gcode"}})
    assert info.view({})["printer_name"] == "Kobra 3"
    info.watch({"print_stats": {"state": "standby", "filename": "other.gcode"}})     # known now: idle files are ignored
    assert len(session.calls) == 1
