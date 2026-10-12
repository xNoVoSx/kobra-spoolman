"""Names in Spoolman: an install from before 3.12 keeps its German names, a new one gets English ones,
explicit settings always win."""

from __future__ import annotations

from acebridge.profiles import find_template
from acebridge.spoolman import Spoolman


def make(cfg, vendors, locations):
    sm = Spoolman(cfg, session=None)
    sm.vendors = [{"id": i, "name": n} for i, n in enumerate(vendors, 1)]
    sm.spools = [{"id": i, "location": loc} for i, loc in enumerate(locations, 1)]
    sm.resolve_names()
    return sm


def test_new_install_gets_english_names(cfg):
    make(cfg, ["Sunlu"], ["ACE Slot 1"])
    assert (cfg.template_vendor, cfg.shelf_location) == ("Template", "Shelf")


def test_existing_german_install_keeps_its_names(cfg):
    make(cfg, ["Vorlage", "Sunlu"], ["Regal", "ACE Slot 2"])
    assert (cfg.template_vendor, cfg.shelf_location) == ("Vorlage", "Regal")


def test_explicit_settings_win(cfg, monkeypatch):
    monkeypatch.setenv("TEMPLATE_VENDOR", "Presets")
    monkeypatch.setenv("SHELF_LOCATION", "Drybox")
    from acebridge.config import Config
    c = Config()
    make(c, ["Vorlage"], ["Regal"])
    assert (c.template_vendor, c.shelf_location) == ("Presets", "Drybox")


def test_decided_once(cfg):
    sm = make(cfg, [], [])
    sm.vendors = [{"id": 1, "name": "Vorlage"}]
    sm.resolve_names()
    assert cfg.template_vendor == "Template"


def test_template_by_name_in_both_languages():
    old = {"id": 2, "name": "Vorlage PETG", "material": "PETG", "vendor": {"name": "Vorlage"}}
    new = {"id": 3, "name": "Template PETG", "material": "PETG", "vendor": {"name": "Template"}}
    other = {"id": 1, "name": "PETG fast", "material": "PETG", "vendor": {"name": "Template"}}
    fil = {"material": "petg", "extra": {}}
    assert find_template(fil, [other, old]) is old
    assert find_template(fil, [other, new]) is new
