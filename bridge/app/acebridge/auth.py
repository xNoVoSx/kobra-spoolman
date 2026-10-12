"""Pairing devices: the bridge issues the access keys itself.

- Every device (app, browser, Orca plugin, display) gets its own long key. Only its SHA-256 is stored (devices.json in
  the data folder), never the key itself.
- Pairing with a 6-digit code, valid for 5 minutes, usable once. The code is created by a device that is already
  paired ("add device").
- First device: as long as nothing is paired, the bridge writes a setup code to its log at start (e.g. Portainer ->
  Logs). A set APP_TOKEN still counts as a key (legacy) and can also be used for pairing.
- Wrong codes are throttled (60 s lock after 5 failed attempts).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from .i18n import tr
from .storage import save_json

log = logging.getLogger("auth")

CODE_TTL_S = 300
MAX_FAILS = 5
LOCK_S = 60
KINDS = ("app", "web", "plugin", "display", "other")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _code() -> str:
    return f"{secrets.randbelow(10**6):06d}"


class AuthError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


class Devices:
    def __init__(self, data_dir: str, legacy_token: str = "", clock: Callable[[], float] = time.time):
        self.path = os.path.join(data_dir, "devices.json")
        self.legacy = legacy_token
        self.clock = clock
        self.devices: List[Dict[str, Any]] = []
        self.codes: Dict[str, float] = {}          # pairing code -> valid until
        self.setup_code: Optional[str] = None
        self._fails: List[float] = []
        self._load()
        if not self.devices:
            self.setup_code = _code()

    # ------------------------------------------------------------ storage
    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                self.devices = json.load(fh).get("devices") or []
        except FileNotFoundError:
            self.devices = []
        except Exception as e:  # noqa: BLE001
            log.error("devices.json unreadable (%s) - no devices paired", e)
            self.devices = []

    def _save(self) -> None:
        save_json(self.path, {"devices": self.devices}, indent=1)

    def announce(self) -> None:
        """At start: setup code to the log while nothing is paired yet."""
        if self.setup_code:
            log.warning("No device paired yet. Setup code: %s  (enter it in the web UI or the app)",
                        self.setup_code)

    # ------------------------------------------------------------ checking
    def identify(self, authorization: Optional[str]) -> Optional[Dict[str, Any]]:
        """Device for the header "Authorization: Bearer <key>", or None."""
        if not authorization or not authorization.startswith("Bearer "):
            return None
        token = authorization[7:].strip()
        if not token:
            return None
        if self.legacy and hmac.compare_digest(token, self.legacy):
            return {"id": "app_token", "name": "APP_TOKEN (legacy)", "kind": "other"}
        h = _hash(token)
        for d in self.devices:
            if hmac.compare_digest(h, d["token_sha256"]):
                now = self.clock()
                if now - (d.get("last_seen") or 0) > 60:     # do not write on every request
                    d["last_seen"] = now
                    self._save()
                return d
        return None

    def require(self, authorization: Optional[str]) -> Dict[str, Any]:
        """Like identify, but AuthError without a paired device (for everything that writes)."""
        dev = self.identify(authorization)
        if dev is not None:
            return dev
        if self.setup_required:
            raise AuthError(403, tr("No device paired yet – enter the setup code from the bridge log"))
        raise AuthError(401, tr("This device is not paired (any more)"))

    @property
    def setup_required(self) -> bool:
        return not self.devices and not self.legacy

    # ------------------------------------------------------------ pairing
    def new_code(self) -> Dict[str, Any]:
        now = self.clock()
        self.codes = {c: t for c, t in self.codes.items() if t > now}
        code = _code()
        while code in self.codes:
            code = _code()
        self.codes[code] = now + CODE_TTL_S
        return {"code": code, "expires_in": CODE_TTL_S}

    def _check_rate(self) -> None:
        now = self.clock()
        self._fails = [t for t in self._fails if now - t < LOCK_S]
        if len(self._fails) >= MAX_FAILS:
            raise AuthError(429, tr("Too many wrong codes – wait a minute"))

    def pair(self, code: str, name: str, kind: str) -> Dict[str, Any]:
        self._check_rate()
        code = (code or "").strip().replace(" ", "")
        now = self.clock()
        ok = False
        if self.setup_code and hmac.compare_digest(code, self.setup_code):
            ok = True
        elif self.legacy and hmac.compare_digest(code, self.legacy):
            ok = True
        elif code in self.codes and self.codes[code] > now:
            del self.codes[code]
            ok = True
        if not ok:
            self._fails.append(now)
            raise AuthError(401, tr("Code wrong or expired"))
        name = (name or "").strip()[:60] or "Device"
        kind = kind if kind in KINDS else "other"
        token = secrets.token_urlsafe(32)
        dev = {"id": uuid.uuid4().hex[:12], "name": name, "kind": kind, "token_sha256": _hash(token),
               "created": now, "last_seen": now}
        self.devices.append(dev)
        self.setup_code = None
        self._save()
        log.info("Device paired: %s (%s)", name, kind)
        return {"token": token, "device": self.public(dev)}

    def remove(self, device_id: str) -> None:
        before = len(self.devices)
        self.devices = [d for d in self.devices if d["id"] != device_id]
        if len(self.devices) == before:
            raise AuthError(404, tr("Device not found"))
        self._save()
        log.info("Device removed: %s", device_id)
        if not self.devices:
            self.setup_code = _code()
            self.announce()

    @staticmethod
    def public(d: Dict[str, Any]) -> Dict[str, Any]:
        return {k: d.get(k) for k in ("id", "name", "kind", "created", "last_seen")}


class CameraKey:
    """Separate key for the camera only, as ?key=... in the URL.

    Mainsail and an <img> in the browser cannot send an Authorization header. This key only shows camera images,
    writes nothing and can be renewed by any paired device (the old link is dead then). It is stored in plain text so
    paired devices can show the link again at any time (camera.json in the data folder).
    """

    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, "camera.json")
        self.key = ""
        try:
            with open(self.path, encoding="utf-8") as fh:
                self.key = json.load(fh).get("key") or ""
        except FileNotFoundError:
            pass
        except Exception as e:  # noqa: BLE001
            log.error("camera.json unreadable (%s) - creating a new camera key", e)
        if not self.key:
            self.rotate()

    def rotate(self) -> str:
        self.key = secrets.token_urlsafe(24)
        save_json(self.path, {"key": self.key})
        log.info("New camera key created (old camera links stop working)")
        return self.key

    def check(self, key: Optional[str]) -> bool:
        return bool(key) and hmac.compare_digest(key.encode(), self.key.encode())
