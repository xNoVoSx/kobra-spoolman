"""HTTP-API, Bereich: KI (kobra-vision): Zustand, Einstellungen, Rueckmeldung, Bildersammlung, Export.

Eingebunden von web.build_app; gemeinsame Hilfen in webcommon.py."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from aiohttp import web

from .camera import CameraError
from .webcommon import Ctx, _err

if TYPE_CHECKING:
    from .__main__ import Bridge

log = logging.getLogger("web")


def add_routes(r: web.RouteTableDef, bridge: "Bridge", ctx: Ctx) -> None:
    paired = ctx.paired
    camera_allowed = ctx.camera_allowed
    camera_denied = ctx.camera_denied
    _body = ctx.body
    _int = ctx.int_

    # ---------------------------------------------------------------- KI (kobra-vision)
    @r.get("/api/vision")
    async def vision_state(_: web.Request):
        return web.json_response(bridge.vision.state())

    @r.post("/api/vision/settings")
    async def vision_settings(request: web.Request):
        """Einstellungen aendern (gekoppelt): nur die mitgeschickten Felder."""
        if (denied := paired(request)) is not None:
            return denied
        try:
            s = bridge.vision.update_settings(await _body(request))
        except ValueError as e:
            return _err(400, str(e))
        return web.json_response({"ok": True, "settings": s.to_dict()})

    @r.post("/api/vision/mute")
    async def vision_mute(request: web.Request):
        """{"on": true} = diesen Druck nicht ueberwachen (bis zum naechsten Druck)."""
        if (denied := paired(request)) is not None:
            return denied
        bridge.vision.mute(bool((await _body(request)).get("on")))
        return web.json_response({"ok": True, "muted": bridge.vision.muted})

    @r.post("/api/vision/baseline/reset")
    async def vision_reset(request: web.Request):
        if (denied := paired(request)) is not None:
            return denied
        bridge.vision.reset_baseline()
        return web.json_response({"ok": True})

    @r.post("/api/vision/test")
    async def vision_test(request: web.Request):
        """Jetzt pruefen: ohne Body das aktuelle Kamerabild, mit JPEG-Body (image/jpeg) ein eigenes Bild."""
        if (denied := paired(request)) is not None:
            return denied
        img = await request.read() if request.content_type == "image/jpeg" else None
        try:
            return web.json_response(await bridge.vision.test(img or None))
        except CameraError as e:
            return _err(503, f"Kein Kamerabild: {e}")
        except RuntimeError as e:
            return _err(503, str(e))
        except Exception as e:  # noqa: BLE001
            return _err(503, f"KI-Dienst nicht erreichbar: {e.__class__.__name__}")

    @r.get("/api/vision/event/{event_id}.jpg")
    async def vision_frame(request: web.Request):
        """Bild eines KI-Ereignisses - wie die Kamera nur gekoppelt oder mit Kamera-Schluessel."""
        if not camera_allowed(request):
            return camera_denied()
        path = bridge.vision.frame_path(request.match_info["event_id"])
        if not path:
            return _err(404, "Kein Bild zu diesem Ereignis")
        return web.FileResponse(path, headers={"Cache-Control": "no-store"})

    @r.post("/api/vision/feedback")
    async def vision_feedback(request: web.Request):
        """{"id": <ereignis>, "verdict": "false_alarm" | "confirmed" | null} - Fehlalarm schaltet die KI fuer den Druck still."""
        if (denied := paired(request)) is not None:
            return denied
        body = await _body(request)
        verdict = body.get("verdict")
        try:
            ev = bridge.vision.feedback(str(body.get("id") or ""), None if verdict is None else str(verdict))
        except KeyError:
            return _err(404, "Unbekanntes Ereignis")
        except ValueError as e:
            return _err(400, str(e))
        return web.json_response({"ok": True, "event": ev})

    @r.get("/api/vision/jobs")
    async def vision_jobs(_: web.Request):
        return web.json_response({"jobs": bridge.vision.data.jobs(),
                                  "stats": bridge.vision.data.stats(bridge.vision.settings.dataset_gb)})

    @r.get("/api/vision/jobs/{job}")
    async def vision_job(request: web.Request):
        """?filter=all|event|suspect|startend|labelled|open&offset=0&limit=120"""
        q = request.query
        try:
            return web.json_response(bridge.vision.data.page(request.match_info["job"], q.get("filter", "all"),
                                                             _int(q.get("offset")), _int(q.get("limit"), 120)))
        except KeyError:
            return _err(404, "Unbekannter Druck")
        except ValueError as e:
            return _err(400, str(e))

    @r.get("/api/vision/jobs/{job}/{frame}")
    async def vision_job_frame(request: web.Request):
        if not camera_allowed(request):
            return camera_denied()
        path = bridge.vision.data.frame_path(request.match_info["job"], request.match_info["frame"])
        if not path:
            return _err(404, "Bild nicht gefunden")
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
            return _err(404, "Bild nicht gefunden")
        except ValueError as e:
            return _err(400, str(e))
        return web.json_response({"ok": True})

    @r.delete("/api/vision/jobs/{job}")
    async def vision_delete_job(request: web.Request):
        if (denied := paired(request)) is not None:
            return denied
        if request.match_info["job"] == bridge.vision.job and bridge.vision._print_state() in ("printing", "paused"):
            return _err(409, "Der laufende Druck kann nicht gelöscht werden")
        try:
            bridge.vision.data.delete_job(request.match_info["job"])
        except KeyError:
            return _err(404, "Unbekannter Druck")
        return web.json_response({"ok": True})

    @r.delete("/api/vision/jobs/{job}/{frame}")
    async def vision_delete_frame(request: web.Request):
        if (denied := paired(request)) is not None:
            return denied
        try:
            bridge.vision.data.delete_frame(request.match_info["job"], request.match_info["frame"])
        except KeyError:
            return _err(404, "Bild nicht gefunden")
        return web.json_response({"ok": True})

    @r.get("/api/vision/export.zip")
    async def vision_export(request: web.Request):
        """Bildersammlung als ZIP (?job= fuer einen Druck) - gestreamt, Bilder unkomprimiert."""
        if not camera_allowed(request):
            return camera_denied()
        job = request.query.get("job") or None
        name = f"kobra-ki-{job or 'alle'}.zip"
        resp = web.StreamResponse(headers={"Content-Type": "application/zip",
                                           "Content-Disposition": f'attachment; filename="{name}"'})
        await resp.prepare(request)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=8)
        stop = {"cancel": False}

        class Pipe:                                   # nicht-seekbarer Strom fuer zipfile im Thread
            def write(self, b):
                if stop["cancel"]:
                    raise OSError("abgebrochen")
                asyncio.run_coroutine_threadsafe(queue.put(bytes(b)), loop).result()
                return len(b)

            def flush(self):
                pass

        def work():
            try:
                bridge.vision.data.write_zip(Pipe(), job, lambda: stop["cancel"])
            except (OSError, KeyError) as e:
                log.info("KI-Export abgebrochen: %s", e)
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(None), loop).result()

        fut = loop.run_in_executor(None, work)
        try:
            while (chunk := await queue.get()) is not None:
                await resp.write(chunk)
        except (ConnectionError, asyncio.CancelledError):
            stop["cancel"] = True
            while not fut.done():                     # Thread loslassen
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                await asyncio.sleep(0.01)
            raise
        await fut
        await resp.write_eof()
        return resp
