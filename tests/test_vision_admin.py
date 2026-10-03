"""KI-Tab: Einstellungen, ignorierte Bereiche, Ruhezeiten, Bildersammlung, Export."""

from __future__ import annotations

import asyncio
import io
import json
import time
import zipfile

import pytest
from aiohttp.test_utils import TestClient, TestServer
from test_appapi import FakeBridge
from conftest import FakeCamera, run_print

from acebridge import vision_settings as vs
from acebridge.vision import Vision
from acebridge.web import build_app


def test_settings_are_validated_and_saved(vision):
    v, moon, clock = vision
    s = v.update_settings({"sensitivity": 1.5, "action": "pause", "notify": "fail",
                           "zones": [{"x": 0.9, "y": 0.0, "w": 0.5, "h": 0.2}]})
    assert s.sensitivity == 1.5 and s.zones == [{"x": 0.9, "y": 0.0, "w": 0.1, "h": 0.2}]   # auf das Bild begrenzt
    for bad in ({"sensitivity": 9}, {"action": "explode"}, {"interval_s": 1}, {"quiet": {"start": "25:00"}},
                {"unbekannt": 1}, {"zones": "x"}):
        with pytest.raises(ValueError):
            v.update_settings(bad)
    again = Vision(v.cfg, moon, FakeCamera(), None)
    assert again.settings.action == "pause" and again.settings.notify == "fail"           # gespeichert


def test_suspect_pictures_are_rate_limited(vision):
    v, moon, clock = vision
    asyncio.run(v.tick())
    moon.merge({"print_stats": {"state": "printing"}})
    v.mute(False)
    run_print(v, moon, clock, 0.0, 1)
    v.mute(True)                                    # stumm: kein Alarm, nur Sammeln
    run_print(v, moon, clock, 0.2, 30)              # 300 s leicht verdaechtig
    suspects = [f for f in v.data.frames(v.job) if f["kind"] == "suspect"]
    assert 9 <= len(suspects) <= 11                 # alle 30 s statt alle 10 s


def test_old_event_frame_paths_still_work(vision):
    v, moon, clock = vision
    v.data.add("20261003-010000_alt", "010000_event_1.97.jpg", b"\xff\xd8", {"kind": "event"})
    v.events.append({"id": "alt1", "frame": "jobs/20261003-010000_alt/010000_event_1.97.jpg"})
    assert v.frame_path("alt1")
    v.feedback("alt1", "confirmed")
    assert v.data.frames("20261003-010000_alt")[0]["label"] == "spaghetti"


def test_one_bad_saved_value_does_not_discard_the_others(vision, tmp_path):
    v, moon, clock = vision
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"safe_s": 60, "interval_s": 0.5, "notify": "fail", "unbekannt": 1}))
    s = vs.load(str(path), vs.VisionSettings())
    assert s.safe_s == 60 and s.notify == "fail" and s.interval_s == 10.0


def test_quiet_hours_over_midnight():
    s = vs.VisionSettings(quiet={"enabled": True, "start": "22:00", "end": "07:00", "mode": "pause"})
    assert vs.in_quiet(s, 23 * 60) and vs.in_quiet(s, 3 * 60) and not vs.in_quiet(s, 12 * 60)
    s.quiet["enabled"] = False
    assert not vs.in_quiet(s, 23 * 60)


def test_zone_hides_findings_from_the_score(vision):
    v, moon, clock = vision
    v.update_settings({"zones": [{"x": 0.4, "y": 0.4, "w": 0.2, "h": 0.2}]})     # die Testbox sitzt bei 0.5/0.5
    asyncio.run(v.tick())
    moon.merge({"print_stats": {"state": "printing"}})
    run_print(v, moon, clock, 0.0, 40)
    run_print(v, moon, clock, 3.0, 5)
    assert v.level == "ok" and v.detections == [] and len(v.ignored) == 1 and v.messages() == []


def test_warning_is_yellow_when_phone_only_wants_failures(vision):
    v, moon, clock = vision
    v.update_settings({"notify": "fail"})
    asyncio.run(v.tick())
    moon.merge({"print_stats": {"state": "printing"}})
    run_print(v, moon, clock, 0.0, 40)
    v.p_next = 0.7
    for _ in range(10):
        clock.t += 10
        asyncio.run(v.tick())
        if v.level == "warn":
            break
    assert v.level == "warn" and v.messages()[0]["level"] == "warn"                  # kein Handy-Alarm
    v.update_settings({"notify": "warn"})
    assert v.messages()[0]["level"] == "error"


def test_manual_mute_and_pause_with_heater_off(vision):
    v, moon, clock = vision
    sent = []

    async def action(method, label, source="Bridge", timeout=30):
        sent.append(method)

    async def gcode(script, timeout=15, source="Bridge"):
        sent.append(script)
    moon.action, moon.gcode = action, gcode
    v.update_settings({"action": "pause", "heater_off": True})
    asyncio.run(v.tick())
    moon.merge({"print_stats": {"state": "printing"}})
    run_print(v, moon, clock, 0.0, 1)
    v.mute(True)                                                                   # nach dem Druckstart
    run_print(v, moon, clock, 0.0, 40)
    run_print(v, moon, clock, 3.0, 4)
    assert sent == [] and "von Hand" in v.status_line()["detail"]
    v.mute(False)
    run_print(v, moon, clock, 3.0, 1)
    assert sent == ["printer.print.pause", "M104 S0"]


def test_quiet_hours_can_pause_even_in_warn_mode(vision):
    v, moon, clock = vision
    sent = []

    async def action(method, label, source="Bridge", timeout=30):
        sent.append(method)
    moon.action = action
    now = time.localtime(clock.t)
    start = f"{now.tm_hour:02d}:00"
    end = f"{(now.tm_hour + 1) % 24:02d}:00"
    v.update_settings({"quiet": {"enabled": True, "start": start, "end": end, "mode": "pause"}})
    assert v.quiet_now() and v.effective_action() == "pause"
    asyncio.run(v.tick())
    moon.merge({"print_stats": {"state": "printing"}})
    run_print(v, moon, clock, 0.0, 40)
    run_print(v, moon, clock, 3.0, 4)
    assert sent == ["printer.print.pause"]


def test_dataset_api_label_delete_export(cfg, vision):
    v, moon, clock = vision
    cfg.app_token = "geheim"
    bridge = FakeBridge(cfg)
    bridge.vision = v
    asyncio.run(v.tick())
    moon.merge({"print_stats": {"state": "printing"}})
    run_print(v, moon, clock, 0.0, 40)
    run_print(v, moon, clock, 3.0, 3)
    h = {"Authorization": "Bearer geheim"}

    async def go():
        async with TestClient(TestServer(build_app(bridge))) as c:
            jobs = (await (await c.get("/api/vision/jobs")).json())["jobs"]
            assert jobs[0]["job"] == v.job and jobs[0]["events"] >= 1
            page = await (await c.get(f"/api/vision/jobs/{v.job}?limit=2")).json()
            assert len(page["frames"]) == 2 and page["total"] > 2
            assert (await c.get(f"/api/vision/jobs/{v.job}?filter=quatsch")).status == 400
            ev = (await (await c.get(f"/api/vision/jobs/{v.job}?filter=event")).json())["frames"]
            assert ev and all(f["kind"] == "event" for f in ev)
            frames = (await (await c.get(f"/api/vision/jobs/{v.job}")).json())["frames"]
            kinds = {f["kind"] for f in frames}
            assert {"start", "event"} <= kinds
            fr = frames[0]["frame"]
            assert (await c.get(f"/api/vision/jobs/{v.job}/{fr}")).status == 401
            assert (await c.get(f"/api/vision/jobs/{v.job}/{fr}", headers=h)).status == 200
            assert (await c.get(f"/api/vision/jobs/{v.job}/..%2Fstate.json", headers=h)).status == 404
            body = {"job": v.job, "frame": fr, "label": "plate_empty"}
            assert (await c.post("/api/vision/label", json=body)).status == 401
            assert (await c.post("/api/vision/label", json={**body, "label": "quatsch"}, headers=h)).status == 400
            assert (await c.post("/api/vision/label", json=body, headers=h)).status == 200
            frames = (await (await c.get(f"/api/vision/jobs/{v.job}")).json())["frames"]
            assert next(f for f in frames if f["frame"] == fr)["label"] == "plate_empty"
            r = await c.get("/api/vision/export.zip", headers=h)
            z = zipfile.ZipFile(io.BytesIO(await r.read()))
            assert r.status == 200 and f"{v.job}/{fr}" in z.namelist() and "README.txt" in z.namelist()
            assert json.loads(z.read(f"{v.job}/labels.jsonl").splitlines()[-1])["label"] == "plate_empty"
            assert (await c.delete(f"/api/vision/jobs/{v.job}", headers=h)).status == 409   # laeuft noch
            assert (await c.delete(f"/api/vision/jobs/{v.job}/{fr}", headers=h)).status == 200
            r = await c.post("/api/vision/settings", json={"sensitivity": 2}, headers=h)
            assert r.status == 200 and (await r.json())["settings"]["sensitivity"] == 2
            assert (await c.post("/api/vision/settings", json={"sensitivity": 20}, headers=h)).status == 400
            r = await c.post("/api/vision/test", data=b"\xff\xd8bild", headers={**h, "Content-Type": "image/jpeg"})
            t = await r.json()
            assert r.status == 200 and t["source"] == "upload" and t["verdict"] == "auffällig"
            assert (await c.post("/api/vision/baseline/reset", headers=h)).status == 200
            assert v.pred.lifetime == 0
    asyncio.run(go())


def test_summary_stays_compatible_with_app_1_5(vision):
    """App 1.5.0 liest vision.muted als Boolean - ein Text dort laesst sie abstuerzen."""
    v, moon, clock = vision
    asyncio.run(v.tick())
    moon.merge({"print_stats": {"state": "printing"}})
    run_print(v, moon, clock, 0.0, 1)
    v.mute(True)
    s = v.summary()
    assert s["muted"] is True and s["muted_reason"] == "manual"
    assert set(s) >= {"enabled", "level", "muted", "score", "detections", "size", "event"}
