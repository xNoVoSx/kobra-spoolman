"""Kopplung im Orca-Plugin: Schluessel speichern, mitschicken, Ablehnung erkennen - gegen eine kleine Fake-Bridge."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent / "fake_orca"))


@pytest.fixture(scope="module")
def ks():
    spec = importlib.util.spec_from_file_location("kobra_spoolman_pair", ROOT / "orca-plugin" / "kobra_spoolman.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeBridge(BaseHTTPRequestHandler):
    token = "schluessel-123"
    seen = []

    def log_message(self, *a):
        pass

    def _send(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authed(self):
        return self.headers.get("Authorization") == f"Bearer {self.token}"

    def do_GET(self):
        if self.path == "/api/auth/status":
            self._send(200, {"device": {"id": "p1", "name": "Orca-Plugin"} if self._authed() else None})
        else:
            self._send(404, {"error": "?"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        FakeBridge.seen.append((self.path, body, self.headers.get("Authorization")))
        if self.path == "/api/auth/pair":
            if body.get("code") != "123456":
                return self._send(401, {"error": "Code falsch oder abgelaufen"})
            return self._send(201, {"token": self.token, "device": {"id": "p1", "name": body["name"], "kind": body["kind"]}})
        if not self._authed():
            return self._send(401, {"error": "Dieses Gerät ist nicht (mehr) gekoppelt"})
        self._send(200, {"ok": True, "applied": {"a": 1}, "ignored": []})


@pytest.fixture
def bridge_url():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeBridge)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
def core(ks, tmp_path, monkeypatch, bridge_url):
    monkeypatch.setattr(ks, "DEVICE_FILE", tmp_path / "kobra_device.json")
    monkeypatch.setattr(ks, "STATE_FILE", tmp_path / "kobra_state.json")
    return ks.Core(lambda: json.dumps({"bridge_url": bridge_url + "/"}))


def test_key_only_for_the_bridge_it_was_paired_with(ks, tmp_path):
    key = ks.DeviceKey(tmp_path / "k.json")
    assert key.headers("http://a:7913") == {}
    key.save("http://a:7913/", "t1", {"id": "x"})
    assert ks.DeviceKey(tmp_path / "k.json").headers("http://a:7913") == {"Authorization": "Bearer t1"}
    assert key.headers("http://b:7913") == {}          # andere Bridge -> neu koppeln
    key.forget()
    assert not (tmp_path / "k.json").exists() and key.token("http://a:7913") is None


def test_unpaired_write_is_refused_then_pairing_fixes_it(ks, core):
    core.check_pairing(force=True)
    assert core.paired is False
    with pytest.raises(ks.NotPaired):
        core.http("POST", "/api/orca/backsync", {"orca_id": "SM000001", "changes": {"a": 1}})

    core.pair_code = "999999"
    core.redeem_pair_code()
    assert core.paired is False and core.pair_msg["error"] and "falsch" in core.pair_msg["text"]

    core.pair_code = "123456"
    core.redeem_pair_code()
    assert core.paired is True and not core.pair_msg["error"]
    path, body, _ = FakeBridge.seen[-1]
    assert path == "/api/auth/pair" and body["kind"] == "plugin" and body["name"].startswith("Orca-Plugin")
    assert json.loads(ks.DEVICE_FILE.read_text())["token"] == FakeBridge.token

    res = core.http("POST", "/api/orca/backsync", {"orca_id": "SM000001", "changes": {"a": 1}})
    assert res["ok"] and FakeBridge.seen[-1][2] == f"Bearer {FakeBridge.token}"
    core.check_pairing(force=True)
    assert core.paired is True


def test_revoked_key_is_forgotten(ks, core):
    core.key.save(core.cfg("bridge_url"), "alt-und-entfernt", {"id": "old"})
    core.check_pairing(force=True)
    assert core.paired is False and core.key.token(core.cfg("bridge_url")) is None


def test_panel_shows_pairing_only_when_needed(ks, core):
    core.bridge_state = {"slots": [], "version": "2.6.0"}
    core.paired = False
    msg = ks.build_panel_message(core)
    assert msg["pair"]["show"] is True and "nicht gekoppelt" in msg["status"]
    core.paired = True
    assert ks.build_panel_message(core)["pair"]["show"] is False
