"""First start (setup.py): new installations start with the core, existing ones keep every switch, what the
installation sets always wins, the decision is made once."""

from __future__ import annotations

import json
import os

from acebridge.runtime_settings import RuntimeSettings
from acebridge.setup import EXISTING, NEW, NEW_DEFAULTS, Setup


def fresh(cfg):
    settings = RuntimeSettings(cfg)
    return Setup(cfg, settings), settings


def test_new_installation_switches_comfort_off_and_opens_setup(cfg, monkeypatch):
    for k in NEW_DEFAULTS:
        monkeypatch.delenv(k.upper(), raising=False)
    cfg.auto_dry_on_insert = cfg.new_spools_dry = cfg.telemetry = True
    s, settings = fresh(cfg)
    assert s.state == NEW and s.view() == {"state": "new", "open_setup": True, "hint": False}
    assert cfg.auto_dry_on_insert is False and cfg.new_spools_dry is False and cfg.telemetry is False
    assert cfg.camera is True and cfg.render is True and cfg.book_usage is True          # core stays on
    s.done()
    assert Setup(cfg, RuntimeSettings(cfg)).view() == {"state": "done", "open_setup": False, "hint": False}


def test_what_the_installation_sets_wins(cfg, monkeypatch):
    for k in NEW_DEFAULTS:
        monkeypatch.delenv(k.upper(), raising=False)
    monkeypatch.setenv("TELEMETRY", "true")
    cfg.telemetry = True
    s, settings = fresh(cfg)
    assert s.state == NEW and cfg.telemetry is True and "telemetry" not in settings.saved


def test_existing_installation_keeps_everything(cfg):
    with open(os.path.join(cfg.data_dir, "devices.json"), "w", encoding="utf-8") as f:
        json.dump({"devices": [{"id": "a", "name": "Phone", "kind": "app"}]}, f)
    cfg.auto_dry_on_insert = cfg.telemetry = True
    s, settings = fresh(cfg)
    assert s.state == EXISTING and s.view()["hint"] is True and s.view()["open_setup"] is False
    assert cfg.auto_dry_on_insert is True and cfg.telemetry is True and not settings.saved


def test_empty_device_list_or_usage_folder_decide_correctly(cfg):
    with open(os.path.join(cfg.data_dir, "devices.json"), "w", encoding="utf-8") as f:
        json.dump({"devices": []}, f)
    assert fresh(cfg)[0].state == NEW                    # only the setup code was written: still new
    os.remove(os.path.join(cfg.data_dir, "setup.json"))
    os.makedirs(os.path.join(cfg.data_dir, "usage"))
    with open(os.path.join(cfg.data_dir, "usage", "journal.jsonl"), "w", encoding="utf-8") as f:
        f.write("{}\n")
    assert fresh(cfg)[0].state == EXISTING


def test_decided_once(cfg):
    s, _ = fresh(cfg)
    assert s.state == NEW
    with open(os.path.join(cfg.data_dir, "devices.json"), "w", encoding="utf-8") as f:
        json.dump({"devices": [{"id": "a", "kind": "app"}]}, f)
    assert fresh(cfg)[0].state == NEW                    # stored in setup.json, not decided again
