"""HTTP API, area AI (kobra-vision): state, settings, feedback, image collection, export.

Added by web.build_app; shared helpers in webcommon.py."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from aiohttp import web

from .camera import CameraError
from .i18n import tr
from .webcommon import Ctx, json_response, msg_of, _err

if TYPE_CHECKING:
    from .__main__ import Bridge

log = logging.getLogger("web")


def add_routes(r: web.RouteTableDef, bridge: "Bridge", ctx: Ctx) -> None:
    paired = ctx.paired
    camera_allowed = ctx.camera_allowed
    camera_denied = ctx.camera_denied
    _body = ctx.body
    _int = ctx.int_

    # ---------------------------------------------------------------- AI (kobra-vision)
    @r.get("/api/vision")
    async def vision_state(_: web.Request):
        return json_response(bridge.vision.state())

    @r.post("/api/vision/settings")
    async def vision_settings(request: web.Request):
        """Change settings (paired): only the fields sent."""
        if (denied := paired(request)) is not None:
            return denied
        try:
            s = bridge.vision.update_settings(await _body(request))
        except ValueError as e:
            return _err(400, msg_of(e))
        return json_response({"ok": True, "settings": s.to_dict()})

    @r.post("/api/vision/mute")
    async def vision_mute(request: web.Request):
        """{"on": true} = do not watch this print (until the next print)."""
        if (denied := paired(request)) is not None:
            return denied
        bridge.vision.mute(bool((await _body(request)).get("on")))
        return json_response({"ok": True, "muted": bridge.vision.muted})

    @r.post("/api/vision/baseline/reset")
    async def vision_reset(request: web.Request):
        if (denied := paired(request)) is not None:
            return denied
        bridge.vision.reset_baseline()
        return json_response({"ok": True})

    @r.post("/api/vision/test")
    async def vision_test(request: web.Request):
        """Check now: without a body the current camera image, with a JPEG body (image/jpeg) your own image."""
        if (denied := paired(request)) is not None:
            return denied
        img = await request.read() if request.content_type == "image/jpeg" else None
        try:
            return json_response(await bridge.vision.test(img or None))
        except CameraError as e:
            return _err(503, tr("No camera image: {error}", error=msg_of(e)))
        except RuntimeError as e:
            return _err(503, msg_of(e))
        except Exception as e:  # noqa: BLE001
            return _err(503, tr("AI service not reachable: {error}", error=e.__class__.__name__))

    @r.get("/api/vision/event/{event_id}.jpg")
    async def vision_frame(request: web.Request):
        """Image of an AI event - like the camera, paired devices or the camera key only."""
        if not camera_allowed(request):
            return camera_denied()
        path = bridge.vision.frame_path(request.match_info["event_id"])
        if not path:
            return _err(404, tr("No image for this event"))
        return web.FileResponse(path, headers={"Cache-Control": "no-store"})

    @r.post("/api/vision/feedback")
    async def vision_feedback(request: web.Request):
        """{"id": <event>, "verdict": "false_alarm" | "confirmed" | null} - a false alarm mutes the AI for this print."""
        if (denied := paired(request)) is not None:
            return denied
        body = await _body(request)
        verdict = body.get("verdict")
        try:
            ev = bridge.vision.feedback(str(body.get("id") or ""), None if verdict is None else str(verdict))
        except KeyError:
            return _err(404, tr("Unknown event"))
        except ValueError as e:
            return _err(400, msg_of(e))
        return json_response({"ok": True, "event": ev})

    @r.get("/api/vision/jobs")
    async def vision_jobs(_: web.Request):
        return json_response({"jobs": bridge.vision.data.jobs(),
                                  "stats": bridge.vision.data.stats(bridge.vision.settings.dataset_gb)})

    @r.get("/api/vision/jobs/{job}")
    async def vision_job(request: web.Request):
        """?filter=all|event|suspect|startend|labelled|open&offset=0&limit=120"""
        q = request.query
        try:
            return json_response(bridge.vision.data.page(request.match_info["job"], q.get("filter", "all"),
                                                             _int(q.get("offset")), _int(q.get("limit"), 120)))
        except KeyError:
            return _err(404, tr("Unknown print"))
        except ValueError as e:
            return _err(400, msg_of(e))

    @r.get("/api/vision/jobs/{job}/{frame}")
    async def vision_job_frame(request: web.Request):
        if not camera_allowed(request):
            return camera_denied()
        path = bridge.vision.data.frame_path(request.match_info["job"], request.match_info["frame"])
        if not path:
            return _err(404, tr("Image not found"))
        return web.FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})

    @r.post("/api/vision/label")
    async def vision_label(request: web.Request):
        """{"job", "frame", "label": ok|spaghetti|detached|tower|plate_not_empty|plate_empty|null}"""
        if (denied := paired(request)) is not None:
            return denied
        b = await _body(request)
        try:
            bridge.vision.data.label(str(b.get("job") or ""), str(b.get("frame") or ""), b.get("label"))
        except KeyError:
            return _err(404, tr("Image not found"))
        except ValueError as e:
            return _err(400, msg_of(e))
        return json_response({"ok": True})

    @r.delete("/api/vision/jobs/{job}")
    async def vision_delete_job(request: web.Request):
        if (denied := paired(request)) is not None:
            return denied
        if request.match_info["job"] == bridge.vision.job and bridge.vision._print_state() in ("printing", "paused"):
            return _err(409, tr("The running print cannot be deleted"))
        try:
            bridge.vision.data.delete_job(request.match_info["job"])
        except KeyError:
            return _err(404, tr("Unknown print"))
        return json_response({"ok": True})

    @r.delete("/api/vision/jobs/{job}/{frame}")
    async def vision_delete_frame(request: web.Request):
        if (denied := paired(request)) is not None:
            return denied
        try:
            bridge.vision.data.delete_frame(request.match_info["job"], request.match_info["frame"])
        except KeyError:
            return _err(404, tr("Image not found"))
        return json_response({"ok": True})

    @r.get("/api/vision/export.zip")
    async def vision_export(request: web.Request):
        """Image collection as ZIP (?job= for one print) - streamed, images uncompressed."""
        if not camera_allowed(request):
            return camera_denied()
        job = request.query.get("job") or None
        name = f"kobra-ai-{job or 'all'}.zip"
        resp = web.StreamResponse(headers={"Content-Type": "application/zip",
                                           "Content-Disposition": f'attachment; filename="{name}"'})
        await resp.prepare(request)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=8)
        stop = {"cancel": False}

        class Pipe:                                   # non-seekable stream for zipfile in the thread
            def write(self, b):
                if stop["cancel"]:
                    raise OSError("cancelled")
                asyncio.run_coroutine_threadsafe(queue.put(bytes(b)), loop).result()
                return len(b)

            def flush(self):
                pass

        def work():
            try:
                bridge.vision.data.write_zip(Pipe(), job, lambda: stop["cancel"])
            except (OSError, KeyError) as e:
                log.info("AI export cancelled: %s", e)
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(None), loop).result()

        fut = loop.run_in_executor(None, work)
        try:
            while (chunk := await queue.get()) is not None:
                await resp.write(chunk)
        except (ConnectionError, asyncio.CancelledError):
            stop["cancel"] = True
            while not fut.done():                     # let the thread go
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                await asyncio.sleep(0.01)
            raise
        await fut
        await resp.write_eof()
        return resp
