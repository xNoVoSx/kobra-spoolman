"""KI-Fehldruck-Erkennung der Bridge: Bewertung ueber die Zeit, Meldungen, Rueckmeldung, Bildersammlung."""

from __future__ import annotations

import asyncio
import json
import os

import pytest
from aiohttp.test_utils import TestClient, TestServer
from conftest import FakeMoonraker
from test_appapi import FakeBridge

from acebridge.status import notices
from acebridge.vision import INIT_SAFE_FRAMES, Prediction, Vision
from acebridge.web import build_app


def test_prediction_waits_then_escalates():
    p = Prediction()
    for _ in range(100):                                        # fruehere saubere Drucke: Grundlinie ~0
        p.update(0.0)
    p.new_print()
    for _ in range(INIT_SAFE_FRAMES - 1):
        p.update(3.0)
    assert p.level() == "ok"                                   # die ersten Bilder eines Drucks zaehlen nicht
    p.update(3.0)
    assert p.level() == "fail" and p.score() > 2 / 3


def test_prediction_quiet_print_stays_ok_and_baseline_survives_prints():
    p = Prediction()
    for _ in range(200):
        p.update(0.02)
    assert p.level() == "ok" and p.score() < 1 / 3
    long_before = p.long
    p.new_print()
    assert p.frames == 0 and p.long == long_before


def test_sudden_moderate_rise_is_a_warning_constant_noise_is_not():
    p = Prediction()
    for _ in range(50):
        p.update(0.0)
    for _ in range(10):
        p.update(0.6)                                          # ploetzlich: Warnung
    assert p.level() == "warn"
    q = Prediction()
    for _ in range(300):
        q.update(0.5)                                          # immer gleich (z. B. Muster auf der Platte)
    assert q.level() == "ok"


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


class FakeCamera:
    def __init__(self):
        self.calls = 0

    async def still(self):
        self.calls += 1
        return b"\xff\xd8fake-jpeg", 0.0


@pytest.fixture
def vision(cfg, monkeypatch):
    cfg.vision_url = "http://vision.invalid:7917"
    cfg.vision_interval_s = 10
    moon = FakeMoonraker()
    moon.merge({"print_stats": {"state": "standby", "filename": "Benchy PETG.gcode"}})
    clock = Clock()
    v = Vision(cfg, moon, FakeCamera(), None, clock=clock)
    v.p_next = 0.0

    async def analyze(_img):
        return {"detections": [["failure", v.p_next, [0.5, 0.5, 0.2, 0.2]]] if v.p_next else [],
                "width": 1280, "height": 720, "ms": 50, "provider": "CPUExecutionProvider"}

    async def health():
        v.health = {"ok": True, "model": {"loaded": False, "provider": None}}
    monkeypatch.setattr(v, "analyze", analyze)
    monkeypatch.setattr(v, "check_health", health)
    return v, moon, clock


def run_print(v, moon, clock, p, frames):
    v.p_next = p
    for _ in range(frames):
        clock.t += 10
        asyncio.run(v.tick())


def test_print_raises_alarm_message_and_false_alarm_mutes(vision):
    v, moon, clock = vision
    asyncio.run(v.tick())
    moon.merge({"print_stats": {"state": "printing"}})
    run_print(v, moon, clock, 0.0, INIT_SAFE_FRAMES + 10)
    assert v.job and v.job.endswith("Benchy_PETG")
    assert os.listdir(os.path.join(v.dir, "jobs", v.job))                         # Startbild gesammelt
    assert v.messages() == [] and v.status_line()["state"] == "ok"

    run_print(v, moon, clock, 2.5, 3)                                             # Spaghetti
    assert v.level == "fail" and v.event is not None
    msgs = v.messages()
    assert msgs and msgs[0]["key"] == "ai-fail" and msgs[0]["level"] == "error"
    assert v.summary()["event"]["id"] == v.event["id"] and v.summary()["detections"]
    assert v.frame_path(v.event["id"])                                            # Bild zum Ereignis

    ev_id = v.event["id"]
    v.feedback(ev_id, "false_alarm")
    assert v.muted and v.messages() == [] and "stumm" in v.status_line()["detail"]
    labels = os.path.join(v.dir, "jobs", v.job, "labels.jsonl")
    assert json.loads(open(labels).read().splitlines()[0])["verdict"] == "false_alarm"
    run_print(v, moon, clock, 3.0, 5)
    assert v.messages() == []                                                     # stumm bis Druckende

    moon.merge({"print_stats": {"state": "complete"}})
    run_print(v, moon, clock, 0.0, 1)
    lines = [json.loads(x) for x in open(os.path.join(v.dir, "jobs", v.job, "frames.jsonl"))]
    assert lines[0]["kind"] == "start" and lines[-1]["kind"] == "end" and lines[-1]["result"] == "complete"
    assert any(x["kind"] == "event" for x in lines)
    # naechster Druck: wieder scharf, Grundlinie bleibt (gespeichert)
    moon.merge({"print_stats": {"state": "printing"}})
    run_print(v, moon, clock, 0.0, 1)
    assert not v.muted and v.pred.frames == 1
    assert Vision(v.cfg, moon, FakeCamera(), None).pred.lifetime > 0


def test_pause_only_with_vision_action_pause(vision):
    v, moon, clock = vision
    sent = []

    async def action(method, label, source="Bridge", timeout=30):
        sent.append((method, source))
    moon.action = action
    asyncio.run(v.tick())
    moon.merge({"print_stats": {"state": "printing"}})
    run_print(v, moon, clock, 0.0, INIT_SAFE_FRAMES + 10)
    run_print(v, moon, clock, 3.0, 3)
    assert v.level == "fail" and sent == []                                       # Standard: nur melden
    v.cfg.vision_action = "pause"
    v.event = None
    run_print(v, moon, clock, 3.0, 1)
    assert sent == [("printer.print.pause", "KI")] and "pausiert" in v.messages()[0]["text"]


def test_unreachable_service_is_a_quiet_message_during_print(vision, monkeypatch):
    v, moon, clock = vision

    async def down(_img):
        raise ConnectionError("weg")
    monkeypatch.setattr(v, "analyze", down)
    asyncio.run(v.tick())
    moon.merge({"print_stats": {"state": "printing"}})
    run_print(v, moon, clock, 0.0, 8)
    m = v.messages()
    assert [x["key"] for x in m] == ["ai-down"] and m[0]["level"] == "warn"
    assert v.status_line()["state"] == "warn"


def test_dataset_is_pruned_oldest_first(vision):
    v, moon, clock = vision
    root = os.path.join(v.dir, "jobs")
    for name in ("20261001-100000_a", "20261002-100000_b", "20261003-100000_c"):
        os.makedirs(os.path.join(root, name))
        with open(os.path.join(root, name, "x.jpg"), "wb") as f:
            f.write(b"0" * 600_000)
    v.cfg.vision_dataset_gb = 1.3 / 1024                                          # ~1.3 MB: zwei passen
    v.job = "20261003-100000_c"
    assert v.prune() == 1 and sorted(os.listdir(root)) == ["20261002-100000_b", "20261003-100000_c"]
    assert v.dataset()["jobs"] == 2


def test_disabled_vision_is_an_off_status_line(cfg):
    bridge = FakeBridge(cfg)
    st = {s["key"]: s for s in notices(bridge)["status"]}
    assert st["ai"]["state"] == "off" and bridge.vision.messages() == []


def test_feedback_api_needs_pairing(cfg, vision):
    v, moon, clock = vision
    cfg.app_token = "geheim"
    bridge = FakeBridge(cfg)
    bridge.vision = v
    asyncio.run(v.tick())
    moon.merge({"print_stats": {"state": "printing"}})
    run_print(v, moon, clock, 0.0, INIT_SAFE_FRAMES + 10)
    run_print(v, moon, clock, 3.0, 3)
    ev = v.event["id"]

    async def go():
        async with TestClient(TestServer(build_app(bridge))) as c:
            assert (await c.post("/api/vision/feedback", json={"id": ev, "verdict": "confirmed"})).status == 401
            h = {"Authorization": "Bearer geheim"}
            assert (await c.post("/api/vision/feedback", json={"id": "nix", "verdict": "confirmed"}, headers=h)).status == 404
            assert (await c.post("/api/vision/feedback", json={"id": ev, "verdict": "egal"}, headers=h)).status == 400
            r = await c.post("/api/vision/feedback", json={"id": ev, "verdict": "confirmed"}, headers=h)
            assert r.status == 200 and (await r.json())["event"]["verdict"] == "confirmed"
            assert (await c.get(f"/api/vision/event/{ev}.jpg")).status == 401
            img = await c.get(f"/api/vision/event/{ev}.jpg", headers=h)
            assert img.status == 200 and (await img.read()).startswith(b"\xff\xd8")
            st = await (await c.get("/api/vision")).json()
            assert st["enabled"] and st["events"][0]["verdict"] == "confirmed" and st["dataset"]["frames"] >= 2
    asyncio.run(go())
