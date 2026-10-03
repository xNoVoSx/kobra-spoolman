"""HTTP-API (Weboberflaeche, Android-App, Orca-Plugin).

Lesen ist offen. Alles, was schreibt oder am Drucker etwas ausloest, braucht den Schluessel eines
gekoppelten Geraets (Header "Authorization: Bearer <schluessel>", siehe auth.py)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Optional

import aiohttp
from aiohttp import web

import platform
import re
import time

from . import CHANGELOG, __app_name__, __description__, __version__, assets
from .ace import AceError
from .camera import CameraError
from .console import LOG_BUFFER, check_command
from .control import ControlError, check_action, tune_commands
from .appapi import AppApi
from .auth import AuthError

if TYPE_CHECKING:
    from .__main__ import Bridge

log = logging.getLogger("web")
STARTED = time.time()
BOUNDARY = "kobraframe"


@web.middleware
async def cors(request: web.Request, handler):
    if request.method == "OPTIONS":
        resp = web.Response()
    else:
        try:
            resp = await handler(request)
        except web.HTTPException as e:
            resp = e
    if getattr(resp, "prepared", False):   # Stream: Kopfzeilen sind schon raus (setzt der Handler selbst)
        return resp
    if request.path.startswith("/static/"):
        resp.headers["Cache-Control"] = assets.NO_CACHE
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return resp


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


def build_app(bridge: "Bridge") -> web.Application:
    app = web.Application(middlewares=[cors])
    r = web.RouteTableDef()

    def need_device(fn):
        """Nur fuer gekoppelte Geraete (Weboberflaeche, App, Plugin)."""
        async def wrapped(request: web.Request):
            try:
                bridge.devices.require(request.headers.get("Authorization"))
            except AuthError as e:
                return _err(e.status, str(e))
            return await fn(request)
        return wrapped

    @r.get("/api/health")
    async def health(_):
        cfg = bridge.cfg
        return web.json_response({
            "app": __app_name__,
            "description": __description__,
            "version": __version__,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(STARTED)),
            "uptime_s": int(time.time() - STARTED),
            "python": platform.python_version(),
            "links": cfg.links(),
            "changelog": [{"version": v, "date": d, "items": i} for v, d, i in CHANGELOG[:5]],
            "settings": {
                "booking": cfg.book_usage, "book_interval_s": cfg.book_interval_s, "book_min_mm": cfg.book_min_mm,
                "gate_debounce_s": cfg.gate_debounce_s, "usage_tolerance": cfg.usage_tolerance,
                "auto_unassign_on_empty": cfg.auto_unassign_on_empty, "empty_debounce_s": cfg.empty_debounce_s,
                "write_lane_data": cfg.write_lane_data, "telemetry": cfg.telemetry,
                "telemetry_keep": cfg.telemetry_keep, "job_history": cfg.job_history,
                "slot_location_prefix": cfg.slot_location_prefix, "shelf_location": cfg.shelf_location,
                "template_vendor": cfg.template_vendor, "data_dir": cfg.data_dir, "log_level": cfg.log_level,
            },
            "firmware_spoolman_support": (bridge.moon.status.get("mmu", {}) or {}).get("spoolman_support"),
            "dry_run": bridge.cfg.dry_run,
            "moonraker": {"url": bridge.cfg.moonraker_url, "connected": bridge.moon.connected,
                          "klippy_ready": bridge.moon.klippy_ready},
            "spoolman": {"url": bridge.cfg.spoolman_url, "connected": bridge.sm.connected,
                         "version": bridge.sm.version,
                         "last_refresh_s": int(time.time() - bridge.sm.last_refresh) if bridge.sm.last_refresh else None,
                         "spools": len(bridge.sm.spools), "filaments": len(bridge.sm.filaments)},
            "print_state": bridge.slots.print_state,
            "booking": bridge.cfg.book_usage and not bridge.cfg.dry_run,
            "printing_job": (bridge.usage.job or {}).get("file"),
            "open_items": len(bridge.usage.open),
            "warnings": bridge.safety_warnings() + bridge.slots.warnings,
        })

    @r.get("/api/slots")
    async def slots(_):
        return web.json_response({"print_state": bridge.slots.print_state,
                                  "warnings": bridge.safety_warnings() + bridge.slots.warnings,
                                  "slots": bridge.slots.slots_view(),
                                  "dryer": bridge.dryer.state(),
                                  "usage": {"live": bridge.usage.live(),
                                            "last": bridge.usage.last_by_slot(),
                                            "open": bridge.usage.open}})

    @r.post("/api/slots/{slot}")
    @need_device
    async def assign(request: web.Request):
        try:
            slot = int(request.match_info["slot"])
            body = await request.json()
        except Exception:  # noqa: BLE001
            return _err(400, "Erwartet JSON {\"spool_id\": <id oder null>}")
        spool_id = body.get("spool_id")
        if spool_id is not None:
            try:
                spool_id = int(spool_id)
            except (TypeError, ValueError):
                return _err(400, "spool_id muss eine Zahl oder null sein")
        try:
            await bridge.slots.assign(slot, spool_id)
        except ValueError as e:
            return _err(400, str(e))
        except Exception as e:  # noqa: BLE001
            log.warning("Zuordnung fehlgeschlagen: %s", e)
            return _err(502, str(e))
        return web.json_response({"ok": True, "slots": bridge.slots.slots_view()})

    @r.get("/api/spools")
    async def spools(request):
        try:
            slot = int(request.query["slot"]) if "slot" in request.query else None
        except ValueError:
            return _err(400, "slot muss eine Zahl sein")
        return web.json_response({"spools": bridge.slots.assignable_spools(slot)})

    # ---------------------------------------------------------------- Trockner (ACE)
    async def _dryer_call(coro):
        try:
            res = await coro
        except ValueError as e:
            return _err(400, str(e))
        except ConnectionError as e:
            return _err(503, f"Drucker nicht bereit: {e}")
        except Exception as e:  # noqa: BLE001
            log.warning("Trockner: %s", e)
            return _err(502, str(e))
        return web.json_response({"ok": True, "result": res, "dryer": bridge.dryer.state()})

    @r.get("/api/dryer")
    async def dryer_state(_):
        return web.json_response(bridge.dryer.state())

    @r.post("/api/dryer/start")
    @need_device
    async def dryer_start(request: web.Request):
        try:
            body = await request.json() if request.can_read_body else {}
            temp = float(body["temp"]) if body.get("temp") not in (None, "") else None
            hours = float(body["hours"]) if body.get("hours") not in (None, "") else None
        except Exception:  # noqa: BLE001
            return _err(400, "Erwartet JSON {\"temp\": <degC oder null>, \"hours\": <h oder null>}")
        return await _dryer_call(bridge.dryer.start(temp, hours, source="hand"))

    @r.post("/api/dryer/stop")
    @need_device
    async def dryer_stop(_):
        return await _dryer_call(bridge.dryer.stop(source="hand"))

    @r.post("/api/dryer/config")
    @need_device
    async def dryer_config(request: web.Request):
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise TypeError
        except Exception:  # noqa: BLE001
            return _err(400, "JSON-Objekt erwartet")

        async def apply():
            return bridge.dryer.set_config(body).__dict__
        return await _dryer_call(apply())

    @r.post("/api/dryer/schedule")
    @need_device
    async def dryer_schedule(request: web.Request):
        try:
            body = await request.json()
            at = body.get("at")
            if isinstance(at, str):
                from datetime import datetime
                at = datetime.fromisoformat(at).timestamp()
            at = float(at)
            temp = float(body["temp"]) if body.get("temp") not in (None, "") else None
            hours = float(body["hours"]) if body.get("hours") not in (None, "") else None
        except Exception:  # noqa: BLE001
            return _err(400, "Erwartet JSON {\"at\": <ISO-Zeit oder Sekunden>, \"temp\": <degC oder null>, \"hours\": <h oder null>}")

        async def apply():
            return bridge.dryer.set_schedule(at, temp, hours)
        return await _dryer_call(apply())

    @r.delete("/api/dryer/schedule")
    @need_device
    async def dryer_schedule_clear(_):
        async def apply():
            bridge.dryer.clear_schedule()
        return await _dryer_call(apply())

    # ---------------------------------------------------------------- ACE-Einstellungen
    async def _ace_call(coro):
        try:
            return web.json_response({"ok": True, "settings": await coro, "purge": bridge.ace.purge_preview()})
        except AceError as e:
            return _err(e.status, str(e))
        except Exception as e:  # noqa: BLE001
            log.warning("ACE-Einstellung: %s", e)
            return _err(502, str(e))

    @r.get("/api/ace")
    async def ace_state(request: web.Request):
        mult = request.query.get("multiplier")
        try:
            mult_f = float(mult.replace(",", ".")) if mult else None
        except ValueError:
            return _err(400, "multiplier muss eine Zahl sein")
        return web.json_response({"settings": bridge.ace.state(), "purge": bridge.ace.purge_preview(mult_f)})

    @r.post("/api/ace/flush")
    @need_device
    async def ace_flush(request: web.Request):
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return _err(400, "Erwartet JSON {\"multiplier\": 1.0, \"confirm_printing\": false}")
        return await _ace_call(bridge.ace.set_flush_multiplier(body.get("multiplier"),
                                                                bool(body.get("confirm_printing"))))

    @r.post("/api/ace/options")
    @need_device
    async def ace_options(request: web.Request):
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise TypeError
        except Exception:  # noqa: BLE001
            return _err(400, "Erwartet JSON {\"auto_refill\": true, \"runout_detect\": true}")
        confirm = bool(body.pop("confirm_printing", False))
        return await _ace_call(bridge.ace.set_options(body, confirm))

    # ---------------------------------------------------------------- Kamera und Druckvorschau
    def camera_allowed(request: web.Request) -> bool:
        """Kamera: gekoppeltes Geraet (Header) oder der Kamera-Schluessel in der Adresse (Mainsail, <img>)."""
        return (bridge.camera_key.check(request.query.get("key"))
                or bridge.devices.identify(request.headers.get("Authorization")) is not None)

    def camera_denied() -> web.Response:
        return _err(401, "Kamera nur für gekoppelte Geräte oder mit dem Kamera-Link")

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

    # ---------------------------------------------------------------- KI (kobra-vision)
    def paired(request: web.Request) -> Optional[web.Response]:
        try:
            bridge.devices.require(request.headers.get("Authorization"))
        except AuthError as e:
            return _err(e.status, str(e))
        return None

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
        return web.json_response(bridge.preview.info(bridge.moon.status))

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

    # ---------------------------------------------------------------- Verbrauch (Etappe 2)
    @r.get("/api/usage")
    async def usage(_):
        return web.json_response({"live": bridge.usage.live(), "last": bridge.usage.last_by_slot(),
                                  "open": bridge.usage.open, "purge": bridge.usage.purge_stats()})

    @r.get("/api/jobs")
    async def jobs(request: web.Request):
        try:
            limit = max(1, min(200, int(request.query.get("limit", 20))))
        except ValueError:
            limit = 20
        return web.json_response({"jobs": bridge.usage.history[:limit]})

    @r.get("/api/open")
    async def open_items(_):
        return web.json_response({"open": bridge.usage.open})

    @r.post("/api/open/{item}")
    @need_device
    async def open_book(request: web.Request):
        try:
            body = await request.json()
            spool_id = int(body["spool_id"])
        except Exception:  # noqa: BLE001
            return _err(400, "Erwartet JSON {\"spool_id\": <id>}")
        try:
            res = await bridge.usage.resolve_open(request.match_info["item"], spool_id)
        except KeyError as e:
            return _err(404, str(e.args[0]))
        except ValueError as e:
            return _err(400, str(e))
        except Exception as e:  # noqa: BLE001
            return _err(502, str(e))
        return web.json_response({"ok": True, **res})

    @r.delete("/api/open/{item}")
    @need_device
    async def open_discard(request: web.Request):
        try:
            res = await bridge.usage.resolve_open(request.match_info["item"], None)
        except KeyError as e:
            return _err(404, str(e.args[0]))
        return web.json_response({"ok": True, **res})

    # ---------------------------------------------------------------- Orca (Etappe 3)
    def _orca_profiles():
        from .orca_profiles import build_profile
        from .slots import base_type
        sm = bridge.sm
        tpls = sm.templates()
        active_fil = {(s.get("filament") or {}).get("id") for s in sm.spools}
        out = []
        for fil in sm.filaments:
            if fil.get("id") in active_fil and not sm.is_template(fil):
                out.append(build_profile(fil, tpls, base_type, sm.spools, bridge.cfg.slot_from_location))
        out.sort(key=lambda p: p["orca_id"])
        import hashlib as _h
        digest = _h.sha1("|".join(p["hash"] for p in out).encode()).hexdigest()[:12]
        return out, digest

    def _find_filament(body):
        sm = bridge.sm
        if body.get("filament_id") is not None:
            fid = int(body["filament_id"])
        else:
            oid = str(body.get("orca_id") or "")
            if not re.fullmatch(r"SM\d{6}", oid):
                raise ValueError("orca_id (SM000010) oder filament_id angeben")
            fid = int(oid[2:])
        fil = sm.filament(fid)
        if not fil or sm.is_template(fil):
            raise LookupError(f"Filament {fid} nicht gefunden")
        return fil

    @r.get("/api/orca/profiles")
    async def orca_profiles(_):
        profiles, digest = _orca_profiles()
        return web.json_response({"hash": digest, "profiles": profiles,
                                  "spoolman_connected": bridge.sm.connected})

    @r.get("/api/orca/state")
    async def orca_state(_):
        """Alles, was das Orca-Panel braucht, unter einer festen Adresse."""
        profiles, digest = _orca_profiles()
        slots = []
        for sl in bridge.slots.slots_view():
            sp = sl["spool"]
            slots.append({"slot": sl["slot"], "active": sl["ace"]["active"], "present": sl["ace"]["present"],
                          "ace_material": sl["ace"]["material"], "ace_color": sl["ace"]["color"],
                          "spool_id": sp["spool_id"] if sp else None,
                          "orca_id": sp["orca_filament_id"] if sp else None,
                          "name": sp["display_name"] if sp else None,
                          "material": sp["material"] if sp else None,
                          "color": sp["color"] if sp else None,
                          "remaining_weight": sp["remaining_weight"] if sp else None,
                          "hints": sl["hints"]})
        return web.json_response({
            "version": __version__, "print_state": bridge.slots.print_state,
            "moonraker": bridge.moon.connected, "spoolman": bridge.sm.connected,
            "slots": slots, "profiles_hash": digest,
            "usage": {"live": bridge.usage.live(), "last": bridge.usage.last_by_slot(),
                      "open": len(bridge.usage.open), "purge": bridge.usage.purge_stats()},
            "warnings": bridge.safety_warnings() + bridge.slots.warnings,
        })

    @r.post("/api/orca/backsync")
    @need_device
    async def orca_backsync(request: web.Request):
        from .orca_profiles import backsync_patch
        try:
            body = await request.json()
            changes = body.get("changes") or {}
            if not isinstance(changes, dict) or not changes:
                raise ValueError("changes fehlt")
            fil = _find_filament(body)
        except LookupError as e:
            return _err(404, str(e))
        except Exception as e:  # noqa: BLE001
            return _err(400, str(e))
        patch, applied, ignored = backsync_patch(fil, changes)
        if patch:
            try:
                await bridge.sm.patch_filament(fil["id"], patch)
            except Exception as e:  # noqa: BLE001
                return _err(502, str(e))
            log.info("Ruecksync Filament #%s: %s", fil["id"], applied)
        return web.json_response({"ok": True, "filament_id": fil["id"], "applied": applied, "ignored": ignored})

    @r.post("/api/orca/reset")
    @need_device
    async def orca_reset(request: web.Request):
        from .orca_profiles import reset_patch
        try:
            body = await request.json()
            keys = [str(k) for k in (body.get("keys") or [])]
            if not keys:
                raise ValueError("keys fehlt")
            fil = _find_filament(body)
        except LookupError as e:
            return _err(404, str(e))
        except Exception as e:  # noqa: BLE001
            return _err(400, str(e))
        patch, done = reset_patch(fil, keys)
        if patch:
            try:
                await bridge.sm.patch_filament(fil["id"], patch)
            except Exception as e:  # noqa: BLE001
                return _err(502, str(e))
            log.info("Zuruecksetzen Filament #%s: %s", fil["id"], done)
        return web.json_response({"ok": True, "filament_id": fil["id"], "reset": done})

    @r.get("/api/telemetry")
    async def telemetry(_):
        return web.json_response({"files": bridge.recorder.list_files()})

    @r.get("/api/telemetry/{name}")
    async def telemetry_file(request: web.Request):
        path = bridge.recorder.path_for(request.match_info["name"])
        if not path:
            return _err(404, "nicht gefunden")
        return web.FileResponse(path, headers={"Content-Type": "application/x-ndjson"})

    # ---------------------------------------------------------------- Drucksteuerung
    async def _body(request: web.Request) -> dict:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return {}
        return body if isinstance(body, dict) else {}

    @r.post("/api/print/tune")
    async def print_tune(request: web.Request):
        """Tempo, Fluss, Luefter, Temperaturen (gekoppelt)."""
        try:
            dev = bridge.devices.require(request.headers.get("Authorization"))
        except AuthError as e:
            return _err(e.status, str(e))
        body = await _body(request)
        try:
            cmds, confirm = tune_commands(body)
        except ControlError as e:
            return _err(e.status, str(e))
        if confirm and not body.get("confirm"):
            return web.json_response({"error": confirm, "confirm": True}, status=409)
        try:
            await bridge.moon.gcode("\n".join(cmds), source=dev.get("name") or "Weboberfläche")
        except Exception as e:  # noqa: BLE001
            return _err(400 if isinstance(e, RuntimeError) else 503, str(e) or "Befehl fehlgeschlagen")
        return web.json_response({"ok": True, "sent": cmds})

    @r.post("/api/print/{action}")
    async def print_action(request: web.Request):
        """pause, resume, cancel (Rueckfrage), emergency_stop (Rueckfrage; danach Aus/An noetig)."""
        try:
            dev = bridge.devices.require(request.headers.get("Authorization"))
        except AuthError as e:
            return _err(e.status, str(e))
        body = await _body(request)
        state = (bridge.moon.status.get("print_stats") or {}).get("state")
        try:
            method, label = check_action(request.match_info["action"], state, bool(body.get("confirm")))
        except ControlError as e:
            if e.confirm:
                return web.json_response({"error": str(e), "confirm": True}, status=409)
            return _err(e.status, str(e))
        try:
            await bridge.moon.action(method, label, source=dev.get("name") or "Weboberfläche")
        except Exception as e:  # noqa: BLE001
            return _err(400 if isinstance(e, RuntimeError) else 503, str(e) or "Aktion fehlgeschlagen")
        bridge.last_control = {"action": request.match_info["action"], "source": dev.get("name") or "",
                               "at": round(time.time(), 1)}
        return web.json_response({"ok": True})

    # ---------------------------------------------------------------- Konsole und Logs
    help_cache: dict = {"at": 0.0, "commands": {}}

    def printing() -> bool:
        return (bridge.moon.status.get("print_stats") or {}).get("state") in ("printing", "paused")

    def _int(v, default=0) -> int:
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    @r.get("/api/console")
    async def console_lines(request: web.Request):
        return web.json_response({"lines": bridge.console.since(_int(request.query.get("after"))),
                                  "printing": printing()})

    @r.get("/api/console/commands")
    async def console_commands(_):
        """Befehle mit Beschreibung fuer die Vervollstaendigung (printer/gcode/help, 10 min gemerkt)."""
        if time.monotonic() - help_cache["at"] > 600 or not help_cache["commands"]:
            try:
                help_cache["commands"] = await bridge.moon.get_json("/printer/gcode/help") or {}
                help_cache["at"] = time.monotonic()
            except Exception as e:  # noqa: BLE001
                if not help_cache["commands"]:
                    return _err(503, f"Befehlsliste nicht lesbar: {e}")
        return web.json_response({"commands": help_cache["commands"]})

    @r.post("/api/console")
    async def console_send(request: web.Request):
        """G-Code senden (gekoppelt). Riskantes und Bewegungen im Druck erst mit confirm=true."""
        try:
            dev = bridge.devices.require(request.headers.get("Authorization"))
        except AuthError as e:
            return _err(e.status, str(e))
        try:
            body = await request.json()
            script = str(body.get("script") or "").strip()
        except Exception:  # noqa: BLE001
            return _err(400, "Erwartet JSON {\"script\": \"G28\", \"confirm\": false}")
        if not script:
            return _err(400, "Kein Befehl")
        reason = check_command(script, printing())
        if reason and not body.get("confirm"):
            return web.json_response({"error": reason, "confirm": True}, status=409)
        try:
            await bridge.moon.gcode(script, timeout=120, source=dev.get("name") or "Weboberfläche")
        except Exception as e:  # noqa: BLE001
            return _err(400 if isinstance(e, RuntimeError) else 503, str(e) or "Befehl fehlgeschlagen")
        return web.json_response({"ok": True})

    @r.get("/api/logs")
    async def logs(request: web.Request):
        return web.json_response({"lines": LOG_BUFFER.since(_int(request.query.get("after")),
                                                            request.query.get("level") or "DEBUG")})

    @r.get("/api/logs.txt")
    async def logs_text(_):
        return web.Response(text=LOG_BUFFER.text(), content_type="text/plain", headers={
            "Content-Disposition": f'attachment; filename="ace-lane-bridge-{time.strftime("%Y%m%d-%H%M")}.log"'})

    @r.get("/api/logs/printer")
    async def printer_logs(_):
        """Logdateien, die Moonraker herausgibt (am S1: moonraker.log, octoapp.log, ...)."""
        try:
            files = await bridge.moon.get_json("/server/files/list?root=logs") or []
        except Exception as e:  # noqa: BLE001
            return _err(503, f"Drucker-Logs nicht lesbar: {e}")
        files = [{"name": f.get("path"), "size": f.get("size"), "modified": f.get("modified")}
                 for f in files if f.get("path") and "/" not in f["path"]]
        return web.json_response({"files": sorted(files, key=lambda f: -(f["modified"] or 0))})

    @r.get("/api/logs/printer/{name}")
    async def printer_log_tail(request: web.Request):
        """Nur das Ende einer Drucker-Logdatei (HTTP-Range) - die Dateien sind viele MB gross."""
        name = request.match_info["name"]
        if not re.fullmatch(r"[\w.\-]+", name):
            return _err(400, "Ungültiger Dateiname")
        kb = max(4, min(1024, _int(request.query.get("kb"), 200)))
        url = f"{bridge.cfg.moonraker_url}/server/files/logs/{name}"
        try:
            async with bridge.session.get(url, headers={**bridge.moon._headers(), "Range": f"bytes=-{kb * 1024}"},
                                          timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 404:
                    return _err(404, "Datei nicht gefunden")
                resp.raise_for_status()
                limit = kb * 1024
                if resp.status == 206:
                    data, partial = await resp.read(), True
                else:                                # Server ohne Range: durchlesen, nur das Ende behalten
                    data, total = b"", 0
                    async for chunk in resp.content.iter_chunked(65536):
                        total += len(chunk)
                        data = (data + chunk)[-limit:]
                    partial = total > limit
        except Exception as e:  # noqa: BLE001
            return _err(503, f"Drucker-Log nicht lesbar: {e}")
        text = data[-kb * 1024:].decode("utf-8", "replace")
        if partial and "\n" in text:
            text = text.split("\n", 1)[1]                         # angeschnittene erste Zeile weg
        return web.Response(text=text, content_type="text/plain", headers={"X-Partial": "1" if partial else "0"})

    app.add_routes(r)
    assets.add_routes(app)
    app.add_routes(AppApi(bridge).routes())   # Android-App (docs/android-app.md)
    return app
