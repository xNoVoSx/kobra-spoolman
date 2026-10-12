"""Shared helpers of the HTTP API (web.py and the areas api_*.py): translated JSON responses, error response, pairing
check, camera access, JSON body, MJPEG stream."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from aiohttp import web

from . import i18n
from .i18n import msg_of, tr  # noqa: F401 - msg_of is used by the api_*.py modules
from .auth import AuthError
from .camera import CameraError

if TYPE_CHECKING:
    from .__main__ import Bridge

log = logging.getLogger("web")
BOUNDARY = "kobraframe"


def json_response(data: Any, status: int = 200, **kw: Any) -> web.Response:
    """web.json_response with every text in the language of the request (i18n.localize)."""
    return web.json_response(data, status=status, dumps=i18n.dumps, **kw)


def _err(status: int, msg: str) -> web.Response:
    return json_response({"error": msg}, status=status)


async def send_mjpeg(resp: web.StreamResponse, first: bytes, frames, who: Optional[str] = None) -> None:
    """Write images as multipart/x-mixed-replace until the viewer leaves. A disconnect (reset, broken pipe, aiohttp
    "Connection lost") is normal and no error - otherwise every close would leave a traceback in the log."""
    frame = first
    try:
        while True:
            await resp.write(b"--" + BOUNDARY.encode() + b"\r\nContent-Type: image/jpeg\r\n"
                             + f"Content-Length: {len(frame)}\r\n\r\n".encode() + frame + b"\r\n")
            frame = await frames.__anext__()
    except (ConnectionError, CameraError, StopAsyncIteration):
        log.debug("Camera viewer %s disconnected", who)


class Ctx:
    """Helpers several areas of the API need (bound to the bridge)."""

    def __init__(self, bridge: "Bridge"):
        self.bridge = bridge

    def need_device(self, fn):
        """Decorator: paired devices only (web UI, app, plugin, display)."""
        async def wrapped(request: web.Request):
            try:
                self.bridge.devices.require_request(request)
            except AuthError as e:
                return _err(e.status, msg_of(e))
            return await fn(request)
        return wrapped

    def paired(self, request: web.Request) -> Optional[web.Response]:
        """None when paired, else the error response."""
        try:
            self.bridge.devices.require_request(request)
        except AuthError as e:
            return _err(e.status, msg_of(e))
        return None

    def camera_allowed(self, request: web.Request) -> bool:
        """Camera: a paired device (header) or the camera key in the URL (Mainsail, <img>)."""
        return (self.bridge.camera_key.check(request.query.get("key"))
                or self.bridge.devices.identify_request(request) is not None)

    @staticmethod
    def camera_denied() -> web.Response:
        return _err(401, tr("Camera only for paired devices or with the camera link"))

    @staticmethod
    async def body(request: web.Request) -> dict:
        """JSON body as a dict ({} for a missing or broken body)."""
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
