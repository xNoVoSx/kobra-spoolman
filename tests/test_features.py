"""All features in one list (features.py): state from the existing switches, switching where the switch lives,
what the installation sets is never changed here, every feature links to an existing heading in the docs."""

from __future__ import annotations

import asyncio
import pathlib
import re
from types import SimpleNamespace

import pytest

from acebridge import features
from acebridge.runtime_settings import RuntimeSettings

ROOT = pathlib.Path(__file__).resolve().parents[1]


class FakeSwitches:
    def __init__(self, items):
        self.items, self.sent = items, []

    def view(self):
        return {"groups": [], "items": self.items}

    async def set(self, key, value):
        self.sent.append((key, value))
        return {"ok": True}


def bridge(cfg, platform="klipper", switch_items=(), devices=()):
    return SimpleNamespace(cfg=cfg, settings=RuntimeSettings(cfg), moon=SimpleNamespace(platform=platform),
                           switches=FakeSwitches(list(switch_items)), devices=SimpleNamespace(devices=list(devices)))


def by_key(view):
    return {i["key"]: i for i in view["items"]}


def test_states_from_the_existing_switches(cfg, monkeypatch):
    monkeypatch.delenv("CAMERA", raising=False)
    cfg.camera, cfg.mqtt_host, cfg.vision_url = True, "", "http://vision:7917"
    b = bridge(cfg, switch_items=[{"key": "pa", "on": True}, {"key": "clog", "on": False}],
               devices=[{"kind": "app"}, {"kind": "app"}, {"kind": "web"}])
    v = by_key(features.view(b))
    assert v["spools"]["on"] is True and v["spools"]["switchable"] is False
    assert v["camera"]["on"] is True and v["camera"]["switchable"] is True
    assert v["auto_pa"]["on"] is True and v["clog"]["on"] is False and v["clog"]["switchable"]
    assert v["powerloss"]["available"] is False                       # module not installed
    assert v["mqtt"]["on"] is False and "MQTT" in v["mqtt"]["why"]
    assert v["vision"]["on"] is True and v["vision"]["switchable"] is False   # set by the installation
    assert v["app"]["on"] is True and v["app"]["paired"] == 2 and v["display"]["on"] is False
    assert all(g["key"] in {i["group"] for i in features.view(b)["items"]} for g in features.view(b)["groups"])


def test_rinkhals_has_no_printer_modules(cfg):
    v = by_key(features.view(bridge(cfg, platform="rinkhals", switch_items=[{"key": "pa", "on": True}])))
    assert v["auto_pa"]["available"] is False and "Klipper" in v["auto_pa"]["why"]
    assert v["camera"]["available"] is True


def test_switching_goes_where_the_switch_lives(cfg, monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    b = bridge(cfg, switch_items=[{"key": "light_auto", "on": False}, {"key": "sound", "on": False}])
    asyncio.run(features.switch(b, "preview", False))
    assert cfg.render is False and b.settings.saved["render"] is False
    asyncio.run(features.switch(b, "io", True))
    assert b.switches.sent == [("light_auto", True), ("sound", True)]


def test_never_switches_what_the_installation_sets(cfg, monkeypatch):
    monkeypatch.setenv("CAMERA", "true")
    b = bridge(cfg)
    st = by_key(features.view(b))["camera"]
    assert st["source"] == "install" and st["switchable"] is False and "CAMERA" in st["why"]
    with pytest.raises(features.FeatureError) as e:
        asyncio.run(features.switch(b, "camera", False))
    assert e.value.status == 409
    for key, status in (("vision", 409), ("app", 409), ("spools", 409), ("nope", 404)):
        with pytest.raises(features.FeatureError) as e:
            asyncio.run(features.switch(b, key, True))
        assert e.value.status == status, key
    with pytest.raises(features.FeatureError) as e:
        asyncio.run(features.switch(b, "preview", "yes"))
    assert e.value.status == 400


def test_every_feature_links_to_an_existing_heading():
    heads = {lang: {features._slug(h) for h in re.findall(r"^## (.+)$", (ROOT / path).read_text(encoding="utf-8"), re.M)}
             for lang, path in (("en", "docs/usage.md"), ("de", "docs/de/usage.md"))}
    for f in features.FEATURES:
        for lang in ("en", "de"):
            url = features.doc_url(f, lang)
            assert url and url.split("#")[1] in heads[lang], (f.key, lang, url)
