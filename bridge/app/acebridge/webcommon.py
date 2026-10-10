"""Gemeinsame Hilfen der HTTP-API (web.py und die Bereiche api_*.py): Fehlerantwort, Kopplungspruefung, Kamera-Zugang,
JSON-Koerper, MJPEG-Stream."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from aiohttp import web

from .auth import AuthError
from .camera import CameraError

if TYPE_CHECKING:
    from .__main__ import Bridge

log = logging.getLogger("web")
BOUNDARY = "kobraframe"


def _err(status: int, msg: str) -> web.Response:
    return web.json_response({"error": msg}, status=status)


async def send_mjpeg(resp: web.StreamResponse, first: bytes, frames, who: Optional[str] = None) -> None:
    """Bilder als multipart/x-mixed-replace schreiben, bis der Zuschauer geht. Trennen (Reset, Broken pipe,
    aiohttp "Connection lost") ist normal und kein Fehler - sonst stuende jedes Schliessen als Traceback im Log."""
    frame = first
    try:
        while True:
            await resp.write(b"--" + BOUNDARY.encode() + b"\r\nContent-Type: image/jpeg\r\n"
                             + f"Content-Length: {len(frame)}\r\n\r\n".encode() + frame + b"\r\n")
            frame = await frames.__anext__()
    except (ConnectionError, CameraError, StopAsyncIteration):
        log.debug("Kamera-Zuschauer %s getrennt", who)


class Ctx:
    """Hilfen, die mehrere Bereiche der API brauchen (an die Bridge gebunden)."""

    def __init__(self, bridge: "Bridge"):
        self.bridge = bridge

    def need_device(self, fn):
        """Dekorator: nur fuer gekoppelte Geraete (Weboberflaeche, App, Plugin, Display)."""
        async def wrapped(request: web.Request):
            try:
                self.bridge.devices.require(request.headers.get("Authorization"))
            except AuthError as e:
                return _err(e.status, str(e))
            return await fn(request)
        return wrapped

    def paired(self, request: web.Request) -> Optional[web.Response]:
        """None, wenn gekoppelt, sonst die Fehlerantwort."""
        try:
            self.bridge.devices.require(request.headers.get("Authorization"))
        except AuthError as e:
            return _err(e.status, str(e))
        return None

    def camera_allowed(self, request: web.Request) -> bool:
        """Kamera: gekoppeltes Geraet (Header) oder der Kamera-Schluessel in der Adresse (Mainsail, <img>)."""
        return (self.bridge.camera_key.check(request.query.get("key"))
                or self.bridge.devices.identify(request.headers.get("Authorization")) is not None)

    @staticmethod
    def camera_denied() -> web.Response:
        return _err(401, "Kamera nur für gekoppelte Geräte oder mit dem Kamera-Link")

    @staticmethod
    async def body(request: web.Request) -> dict:
        """JSON-Koerper als dict ({} bei fehlendem oder kaputtem Koerper)."""
        try:
            data: Any = await request.json()
        except Exception:  # noqa: BLE001
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def int_(v, default=0) -> int:
        try:
            return int(v)
        except (TypeError, ValueError):
            return default
