"""App-Update ueber die Bridge (appupdate.py, /api/app/update)."""

from __future__ import annotations

import asyncio
import json

from aiohttp.test_utils import TestClient, TestServer
from test_appapi import FakeBridge

from acebridge import appupdate
from acebridge.web import build_app


def test_load(tmp_path):
    assert appupdate.load(str(tmp_path)) is None                              # ohne app.json: kein Update
    (tmp_path / "app.json").write_text(json.dumps({"version": "1.2.3", "code": 10203, "file": "x.apk",
                                                   "changes": ["neu"]}))
    assert appupdate.load(str(tmp_path)) is None                              # APK fehlt
    (tmp_path / "x.apk").write_bytes(b"PK apk")
    info = appupdate.load(str(tmp_path))
    assert info["code"] == 10203 and info["size"] == 6
    assert appupdate.public(info) == {"available": True, "version": "1.2.3", "code": 10203, "size": 6,
                                      "changes": ["neu"], "url": "/api/app/update/apk"}
    (tmp_path / "app.json").write_text("kaputt")
    assert appupdate.load(str(tmp_path)) is None


def test_routes(cfg, tmp_path, monkeypatch):
    (tmp_path / "app.json").write_text(json.dumps({"version": "1.0.0", "code": 10000, "file": "a.apk"}))
    (tmp_path / "a.apk").write_bytes(b"PK apk")
    monkeypatch.setattr(appupdate, "APPDIST", str(tmp_path))
    monkeypatch.setattr(appupdate.load, "__defaults__", (str(tmp_path),))
    bridge = FakeBridge(cfg)

    async def go():
        async with TestClient(TestServer(build_app(bridge))) as c:
            info = await (await c.get("/api/app/update")).json()
            r = await c.get(info["url"])
            return info, r.status, r.headers["Content-Type"], await r.read()
    info, status, ctype, body = asyncio.run(go())
    assert info["available"] and info["version"] == "1.0.0"
    assert status == 200 and ctype == "application/vnd.android.package-archive" and body == b"PK apk"
