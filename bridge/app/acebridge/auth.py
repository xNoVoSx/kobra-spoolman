"""Geraete koppeln: die Bridge vergibt die Zugaenge selbst.

- Jedes Geraet (App, Browser, spaeter das Orca-Plugin) bekommt einen eigenen, langen Schluessel.
  Gespeichert wird nur dessen SHA-256 (devices.json im Datenordner), nie der Schluessel selbst.
- Koppeln mit einem 6-stelligen Code, 5 Minuten gueltig, einmal verwendbar. Den Code erzeugt ein
  schon gekoppeltes Geraet ("Geraet hinzufuegen").
- Erstes Geraet: Solange nichts gekoppelt ist, schreibt die Bridge beim Start einen
  Einrichtungscode ins Log (Portainer -> Logs). Ein gesetztes APP_TOKEN gilt weiter als Schluessel
  (Uebergang) und kann ebenfalls zum Koppeln verwendet werden.
- Falsche Codes werden gebremst (nach 5 Fehlversuchen 60 s Sperre).
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

log = logging.getLogger("auth")

CODE_TTL_S = 300
MAX_FAILS = 5
LOCK_S = 60
KINDS = ("app", "web", "plugin", "other")


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
        self.codes: Dict[str, float] = {}          # Kopplungscode -> gueltig bis
        self.setup_code: Optional[str] = None
        self._fails: List[float] = []
        self._dirty_seen = 0.0
        self._load()
        if not self.devices:
            self.setup_code = _code()

    # ------------------------------------------------------------ Speicher
    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                self.devices = json.load(fh).get("devices") or []
        except FileNotFoundError:
            self.devices = []
        except Exception as e:  # noqa: BLE001
            log.error("devices.json unlesbar (%s) - keine Geraete gekoppelt", e)
            self.devices = []

    def _save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"devices": self.devices}, fh, indent=1)
        os.replace(tmp, self.path)

    def announce(self) -> None:
        """Beim Start: Einrichtungscode ins Log, wenn noch nichts gekoppelt ist."""
        if self.setup_code:
            log.warning("Noch kein Gerät gekoppelt. Einrichtungscode: %s  (in der Weboberfläche oder App eingeben)",
                        self.setup_code)

    # ------------------------------------------------------------ Pruefen
    def identify(self, authorization: Optional[str]) -> Optional[Dict[str, Any]]:
        """Geraet zum Header "Authorization: Bearer <schluessel>" oder None."""
        if not authorization or not authorization.startswith("Bearer "):
            return None
        token = authorization[7:].strip()
        if not token:
            return None
        if self.legacy and hmac.compare_digest(token, self.legacy):
            return {"id": "app_token", "name": "APP_TOKEN (Übergang)", "kind": "other"}
        h = _hash(token)
        for d in self.devices:
            if hmac.compare_digest(h, d["token_sha256"]):
                now = self.clock()
                if now - (d.get("last_seen") or 0) > 60:     # nicht bei jeder Anfrage schreiben
                    d["last_seen"] = now
                    self._save()
                return d
        return None

    def require(self, authorization: Optional[str]) -> Dict[str, Any]:
        """Wie identify, aber ohne gekoppeltes Geraet AuthError (fuer alles, was schreibt)."""
        dev = self.identify(authorization)
        if dev is not None:
            return dev
        if self.setup_required:
            raise AuthError(403, "Noch kein Gerät gekoppelt – Einrichtungscode aus dem Bridge-Log eingeben")
        raise AuthError(401, "Dieses Gerät ist nicht (mehr) gekoppelt")

    @property
    def setup_required(self) -> bool:
        return not self.devices and not self.legacy

    # ------------------------------------------------------------ Koppeln
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
            raise AuthError(429, "Zu viele falsche Codes – eine Minute warten")

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
            raise AuthError(401, "Code falsch oder abgelaufen")
        name = (name or "").strip()[:60] or "Gerät"
        kind = kind if kind in KINDS else "other"
        token = secrets.token_urlsafe(32)
        dev = {"id": uuid.uuid4().hex[:12], "name": name, "kind": kind, "token_sha256": _hash(token),
               "created": now, "last_seen": now}
        self.devices.append(dev)
        self.setup_code = None
        self._save()
        log.info("Gerät gekoppelt: %s (%s)", name, kind)
        return {"token": token, "device": self.public(dev)}

    def remove(self, device_id: str) -> None:
        before = len(self.devices)
        self.devices = [d for d in self.devices if d["id"] != device_id]
        if len(self.devices) == before:
            raise AuthError(404, "Gerät nicht gefunden")
        self._save()
        log.info("Gerät entfernt: %s", device_id)
        if not self.devices:
            self.setup_code = _code()
            self.announce()

    @staticmethod
    def public(d: Dict[str, Any]) -> Dict[str, Any]:
        return {k: d.get(k) for k in ("id", "name", "kind", "created", "last_seen")}
