"""Druckdateien fuers Display (files.py): Liste, Werkzeuge der Datei neben den Slots, Druckstart nur mit Rueckfrage."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from conftest import FakeMoonraker

from acebridge.files import FileError, Files, colour_far, tools_of

META = {"a.gcode": {"estimated_time": 3600, "filament_weight_total": 24.5, "filament_type": "PETG;PETG",
                    "filament_colors": ["#685BC7", "#C52E79"], "referenced_tools": [0, 1],
                    "thumbnails": [{"width": 48, "relative_path": ".thumbs/a-48.png"},
                                   {"width": 300, "relative_path": ".thumbs/a-300.png"}]},
        "b.gcode": {"filament_type": "PLA", "filament_colors": ["#FFFFFF"]}}


class Moon(FakeMoonraker):
    def __init__(self):
        super().__init__()
        self.posts, self.fetched = [], []
        self.console = None

    async def get_json(self, path, timeout=10):
        if path.startswith("/server/files/list"):
            return [{"path": "b.gcode", "modified": 1}, {"path": "a.gcode", "modified": 5},
                    {"path": "notiz.txt", "modified": 9}]
        name = path.split("filename=")[1]
        return META.get(name, {})

    async def get_bytes(self, path, timeout=10):
        self.fetched.append(path)
        return b"PNG"

    async def post_json(self, path, body, timeout=10):
        self.posts.append((path, body))


SPOOLS = {1: {"filament": {"material": "PETG", "color_hex": "685BC7", "name": "PETG Lavendel"}},
          2: {"filament": {"material": "PLA", "color_hex": "FFFFFF", "name": "PLA Weiss"}}}


@pytest.fixture
def env():
    moon = Moon()
    moon.merge({"print_stats": {"state": "standby"}})
    slots = SimpleNamespace(assignments=lambda: (SPOOLS, []))
    return Files(moon, slots), moon


def test_list_newest_first_only_gcode(env):
    f, _ = env
    files = asyncio.run(f.list())
    assert [x["path"] for x in files] == ["a.gcode", "b.gcode"]
    assert files[0]["est_s"] == 3600 and files[0]["thumb"] and files[0]["tools"][1]["color"] == "C52E79"


def test_thumbnail_picks_fitting_size(env):
    f, moon = env
    asyncio.run(f.list())
    assert asyncio.run(f.thumbnail("a.gcode")) == b"PNG"
    assert moon.fetched == ["/server/files/gcodes/.thumbs/a-300.png"]
    assert asyncio.run(f.thumbnail("b.gcode")) is None


def test_check_hints(env):
    f, _ = env
    c = asyncio.run(f.check("a.gcode"))
    assert c["tools"][0]["hints"] == [] and "Datei PETG, Slot PLA" in c["tools"][1]["hints"]
    assert "Farbe weicht ab" in c["tools"][1]["hints"] and c["ok"] is False


def test_start_needs_confirm_and_idle(env):
    f, moon = env
    with pytest.raises(FileError) as e:
        asyncio.run(f.start("a.gcode", False, "Display"))
    assert e.value.confirm and moon.posts == []
    res = asyncio.run(f.start("a.gcode", True, "Display"))
    assert moon.posts == [("/printer/print/start", {"filename": "a.gcode"})] and res["warnings"]
    moon.merge({"print_stats": {"state": "printing"}})
    with pytest.raises(FileError) as e:
        asyncio.run(f.start("b.gcode", True, "Display"))
    assert e.value.status == 409
    with pytest.raises(FileError) as e:
        asyncio.run(Files(moon, SimpleNamespace(assignments=lambda: ({}, []))).check("fehlt.gcode"))
    assert e.value.status == 404


def test_helpers():
    assert colour_far("000000", "FFFFFF") and not colour_far("685BC7", "6A5DC5") and not colour_far(None, "FFFFFF")
    assert [t["slot"] for t in tools_of({"filament_type": "PLA;PETG", "referenced_tools": [1]})] == [2]
