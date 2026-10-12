"""HTTP API, area camera (snapshot, link, re-distributed stream) and print preview (info, image, 3D paths, thumbnail).

Added by web.build_app; shared helpers in webcommon.py."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

from aiohttp import web

from .camera import CameraError
from .i18n import tr
from .webcommon import BOUNDARY, Ctx, json_response, msg_of, send_mjpeg, _err

if TYPE_CHECKING:
    from .__main__ import Bridge

log = logging.getLogger("web")


def add_routes(r: web.RouteTableDef, bridge: "Bridge", ctx: Ctx) -> None:
    need_device = ctx.need_device
    camera_allowed = ctx.camera_allowed
    camera_denied = ctx.camera_denied

    # ---------------------------------------------------------------- camera and print preview
    @r.get("/api/camera")
    async def camera_state(_):
        return json_response(bridge.camera.state())

    @r.get("/api/camera/link")
    @need_device
    async def camera_link(_):
        """Camera key for links (Mainsail, web UI). Paired devices only."""
        return json_response({"key": bridge.camera_key.key})

    @r.post("/api/camera/link")
    @need_device
    async def camera_link_rotate(_):
        """Create a new camera key; old links (e.g. in Mainsail) stop working."""
        return json_response({"key": bridge.camera_key.rotate()})

    @r.get("/api/camera/snapshot.jpg")
    async def camera_snapshot(request: web.Request):
        """It is a picture from someone's home: paired devices or the camera key only."""
        if not camera_allowed(request):
            return camera_denied()
        try:
            data, taken = await bridge.camera.snapshot()
        except CameraError as e:
            return _err(503, msg_of(e))
        return web.Response(body=data, content_type="image/jpeg",
                            headers={"Cache-Control": "no-store", "X-Taken-At": str(int(taken))})

    @r.get("/api/camera/frame.jpg")
    async def camera_frame(request: web.Request):
        """The next image after ?after=<frame number> (header X-Frame) - the live view where an MJPEG stream does not get
        through (Home Assistant ingress): ask again with the X-Frame of the last answer."""
        if not camera_allowed(request):
            return camera_denied()
        try:
            after = int(request.query.get("after") or -1)
        except ValueError:
            return _err(400, tr("after must be a number"))
        try:
            data, no = await bridge.camera.next_frame(after)
        except CameraError as e:
            return _err(503, msg_of(e))
        return web.Response(body=data, content_type="image/jpeg",
                            headers={"Cache-Control": "no-store", "X-Frame": str(no)})

    @r.get("/api/camera/stream.mjpg")
    async def camera_stream(request: web.Request):
        """Re-distributed MJPEG stream: however many watch, there is one connection to the printer.
        ?fps=5 limits the frame rate for this viewer."""
        if not camera_allowed(request):
            return camera_denied()
        try:
            max_fps = float(request.query["fps"]) if request.query.get("fps") else None
        except ValueError:
            return _err(400, tr("fps must be a number"))
        async with contextlib.aclosing(bridge.camera.frames(max_fps)) as frames:
            try:
                first = await frames.__anext__()
            except CameraError as e:
                return _err(503, msg_of(e))
            resp = web.StreamResponse(headers={
                "Content-Type": f"multipart/x-mixed-replace; boundary={BOUNDARY}",
                "Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"})
            await resp.prepare(request)
            await send_mjpeg(resp, first, frames, request.remote)
            return resp

    @r.get("/api/print/info")
    async def print_info(_):
        from .status import file_usage
        return json_response({**bridge.preview.info(bridge.moon.status), "uses": file_usage(bridge)})

    @r.get("/api/print/preview.png")
    async def print_preview(_):
        png = await bridge.preview.render(bridge.moon.status)
        if png is None:
            return _err(404, tr("No preview ({status})", status=bridge.preview.status))
        return web.Response(body=png, content_type="image/png", headers={"Cache-Control": "no-store"})

    @r.get("/api/print/geometry.bin")
    async def print_geometry(request: web.Request):
        """Print paths for the 3D view (format: render.geometry_bin), sent compressed."""
        data = await bridge.preview.geometry()
        if data is None:
            return _err(404, tr("No print file loaded ({status})", status=bridge.preview.status))
        resp = web.Response(body=data, content_type="application/octet-stream",
                            headers={"Cache-Control": "no-store", "X-Geometry": bridge.preview.info(bridge.moon.status)["geometry"] or ""})
        resp.enable_compression()
        return resp

    @r.get("/api/print/thumbnail.png")
    async def print_thumbnail(_):
        m = bridge.preview.model
        if not m or not m.thumbnail:
            return _err(404, tr("No thumbnail in the file"))
        return web.Response(body=m.thumbnail, content_type="image/png", headers={"Cache-Control": "no-store"})
