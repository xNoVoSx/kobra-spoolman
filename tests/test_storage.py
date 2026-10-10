"""Sicheres Schreiben im Datenordner (storage.py): ganz oder gar nicht."""

import json

import pytest

from acebridge.storage import save_json, save_lines


def test_writes_and_replaces(tmp_path):
    p = str(tmp_path / "x.json")
    save_json(p, {"a": "Grün"}, indent=1)
    save_json(p, {"a": 2})
    assert json.load(open(p, encoding="utf-8")) == {"a": 2}
    assert not (tmp_path / "x.json.tmp").exists()
    save_json(p, {"a": "Grün"})
    assert "Grün" in open(p, encoding="utf-8").read()         # Umlaute bleiben lesbar


def test_failed_write_keeps_the_old_file(tmp_path):
    p = str(tmp_path / "x.json")
    save_json(p, {"ok": True})
    with pytest.raises(TypeError):
        save_json(p, {"kaputt": object()})                     # nicht serialisierbar -> Abbruch mitten im Schreiben
    assert json.load(open(p, encoding="utf-8")) == {"ok": True}


def test_lines(tmp_path):
    p = str(tmp_path / "x.jsonl")
    save_lines(p, ["1\n", "2\n"])
    assert open(p, encoding="utf-8").read() == "1\n2\n"
