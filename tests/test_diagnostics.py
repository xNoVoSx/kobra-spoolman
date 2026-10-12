"""Diagnostics for bug reports (diagnostics.py): nothing private in the text, secrets only as set/not set."""

from __future__ import annotations

from acebridge.config import Config
from acebridge.diagnostics import redact, settings


def test_redact_removes_hosts_addresses_and_keys():
    text = ("Connected to http://192.168.1.20:7125 and ws://printer.local/websocket, mail me@example.org, "
            "Authorization: Bearer abc.def, key 0123456789abcdef0123456789abcdef, token Zq3xK9mP2vL7nR4tW8yB1cD5")
    out = redact(text)
    for private in ("192.168.1.20", "printer.local", "me@example.org", "abc.def", "0123456789abcdef0123456789abcdef",
                    "Zq3xK9mP2vL7nR4tW8yB1cD5"):
        assert private not in out
    assert "http://<host>:7125" in out and "ws://<host>/websocket" in out
    assert "10.0.0.5" not in redact("from 10.0.0.5")


def test_redact_keeps_what_helps_to_reproduce():
    text = "Slot 2: PLA #FF0000, spool 17, file Benchy_PLA_0.2mm_bed_type_textured_plate.gcode, K 0.0542, v3.13.0"
    assert redact(text) == text


def test_settings_show_secrets_only_as_set(monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "very-secret-token")
    monkeypatch.setenv("MQTT_PASSWORD", "")
    monkeypatch.setenv("MOONRAKER_URL", "http://10.1.2.3:7125")
    monkeypatch.setenv("BOOK_USAGE", "false")
    s = settings(Config())
    assert s["app_token"] == "set" and s["mqtt_password"] == "not set"
    assert s["moonraker_url"] == "http://<host>:7125"
    assert s["book_usage"] is False
    assert "very-secret-token" not in repr(s)


def test_bug_report_form_and_web_ui_fit_together():
    """The web UI prefills the GitHub form by field id and asks to paste into "Diagnostics"."""
    from pathlib import Path

    import yaml
    root = Path(__file__).resolve().parents[1]
    form = yaml.safe_load((root / ".github/ISSUE_TEMPLATE/bug_report.yml").read_text(encoding="utf-8"))
    fields = {b.get("id"): b for b in form["body"]}
    js = (root / "bridge/app/acebridge/static/js/dialogs.js").read_text(encoding="utf-8")
    assert "template=bug_report.yml&bridge_version=" in js and "bridge_version" in fields
    assert fields["diagnostics"]["attributes"]["label"] == "Diagnostics"
    assert "“Diagnostics”" in js
