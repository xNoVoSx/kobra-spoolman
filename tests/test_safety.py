"""Warnung bei doppelter Buchung: die Firmware-Einstellung spoolman_support in allen bekannten Schreibweisen."""

from acebridge.__main__ import spoolman_support_off


def test_spoolman_support_off_variants():
    for off in (None, "off", "OFF", False, 0, "false", "0", ""):
        assert spoolman_support_off(off), off
    for on in ("on", True, 1, "true", "enabled"):
        assert not spoolman_support_off(on), on
