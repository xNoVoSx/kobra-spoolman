"""HTTP-API, Bereich: Kamera (Einzelbild, Link, weiterverteilter Stream) und Druckvorschau (Info, Bild, 3D-Bahnen, Vorschaubild).

Eingebunden von web.build_app; gemeinsame Hilfen in webcommon.py."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

from aiohttp import web

from .camera import CameraError
from .webcommon import BOUNDARY, Ctx, _err, send_mjpeg

if TYPE_CHECKING:
    from .__main__ import Bridge

log = logging.getLogger("web")


def add_routes(r: web.RouteTableDef, bridge: "Bridge", ctx: Ctx) -> None:
    need_device = ctx.need_device
    camera_allowed = ctx.camera_allowed
    camera_denied = ctx.camera_denied

    # ---------------------------------------------------------------- Kamera und Druckvorschau
    @r.get("/api/camera")
    async def camera_state(_):
        return web.json_response(bridge.camera.state())

    @r.get("/api/camera/link")
    @need_device
    async def camera_link(_):
        """Kamera-Schluessel fuer Links (Mainsail, Weboberflaeche). Nur gekoppelt."""
        return web.json_response({"key": bridge.camera_key.key})

    @r.post("/api/camera/link")
    @need_device
    async def camera_link_rotate(_):
        """Neuen Kamera-Schluessel erzeugen; alte Links (z. B. in Mainsail) gelten danach nicht mehr."""
        return web.json_response({"key": bridge.camera_key.rotate()})

    @r.get("/api/camera/snapshot.jpg")
    async def camera_snapshot(request: web.Request):
        """Es ist ein Bild aus der Wohnung: nur gekoppelt oder mit Kamera-Schluessel."""
        if not camera_allowed(request):
            return camera_denied()
        try:
            data, taken = await bridge.camera.snapshot()
        except CameraError as e:
            return _err(503, str(e))
        return web.Response(body=data, content_type="image/jpeg",
                            headers={"Cache-Control": "no-store", "X-Taken-At": str(int(taken))})

    @r.get("/api/camera/stream.mjpg")
    async def camera_stream(request: web.Request):
        """Weiterverteilter MJPEG-Stream: egal wie viele zuschauen, zum Drucker geht eine Verbindung.
        ?fps=5 begrenzt die Bildrate fuer diesen Zuschauer."""
        if not camera_allowed(request):
            return camera_denied()
        try:
            max_fps = float(request.query["fps"]) if request.query.get("fps") else None
        except ValueError:
            return _err(400, "fps muss eine Zahl sein")
        async with contextlib.aclosing(bridge.camera.frames(max_fps)) as frames:
            try:
                first = await frames.__anext__()
            except CameraError as e:
                return _err(503, str(e))
            resp = web.StreamResponse(headers={
                "Content-Type": f"multipart/x-mixed-replace; boundary={BOUNDARY}",
                "Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"})
            await resp.prepare(request)
            await send_mjpeg(resp, first, frames, request.remote)
            return resp

    @r.get("/api/print/info")
    async def print_info(_):
        from .status import file_usage
        return web.json_response({**bridge.preview.info(bridge.moon.status), "uses": file_usage(bridge)})

    @r.get("/api/print/preview.png")
    async def print_preview(_):
        png = await bridge.preview.render(bridge.moon.status)
        if png is None:
            return _err(404, "Keine Vorschau (" + bridge.preview.status + ")")
        return web.Response(body=png, content_type="image/png", headers={"Cache-Control": "no-store"})

    @r.get("/api/print/geometry.bin")
    async def print_geometry(request: web.Request):
        """Druckbahnen fuer die 3D-Ansicht (Format: render.geometry_bin), gepackt uebertragen."""
        data = await bridge.preview.geometry()
        if data is None:
            return _err(404, "Keine Druckdatei geladen (" + bridge.preview.status + ")")
        resp = web.Response(body=data, content_type="application/octet-stream",
                            headers={"Cache-Control": "no-store", "X-Geometry": bridge.preview.info(bridge.moon.status)["geometry"] or ""})
        resp.enable_compression()
        return resp

    @r.get("/api/print/thumbnail.png")
    async def print_thumbnail(_):
        m = bridge.preview.model
        if not m or not m.thumbnail:
            return _err(404, "Kein Vorschaubild in der Datei")
        return web.Response(body=m.thumbnail, content_type="image/png", headers={"Cache-Control": "no-store"})
