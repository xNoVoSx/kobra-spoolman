"""HTTP-API (Weboberflaeche, Android-App, Orca-Plugin).

Lesen ist offen. Alles, was schreibt oder am Drucker etwas ausloest, braucht den Schluessel eines
gekoppelten Geraets (Header "Authorization: Bearer <schluessel>", siehe auth.py)."""

from __future__ import annotations

import contextlib
import logging
import os
from typing import TYPE_CHECKING

from aiohttp import web

import platform
import re
import time

from . import CHANGELOG, __app_name__, __description__, __version__
from .ace import AceError
from .camera import CameraError
from .appapi import AppApi
from .auth import AuthError

if TYPE_CHECKING:
    from .__main__ import Bridge

log = logging.getLogger("web")
STARTED = time.time()
STATIC = os.path.join(os.path.dirname(__file__), "static")
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
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return resp


def _err(status: int, msg: str) -> web.Response:
    return web.json_response({"error": msg}, status=status)


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

    @r.get("/")
    async def index(_):
        return web.FileResponse(os.path.join(STATIC, "index.html"))

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
            try:
                frame = first
                while True:
                    await resp.write(b"--" + BOUNDARY.encode() + b"\r\nContent-Type: image/jpeg\r\n"
                                     + f"Content-Length: {len(frame)}\r\n\r\n".encode() + frame + b"\r\n")
                    frame = await frames.__anext__()
            except (ConnectionResetError, CameraError, StopAsyncIteration):
                pass
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

    app.add_routes(r)
    app.router.add_static("/static", STATIC, append_version=False)
    app.add_routes(AppApi(bridge).routes())   # Android-App (docs/android-app.md)
    return app
