"""HTTP API (web UI, Android app, Orca plugin, display).

Reading is open. Everything that writes or triggers something on the printer needs the key of a paired device
(header "Authorization: Bearer <key>", see auth.py).

Here: app, language, CORS, health, slots, spools. The other areas are in api_*.py (one add_routes each), shared
helpers in webcommon.py, the Android app interface in appapi.py."""

from __future__ import annotations

import logging
import platform
import time
from typing import TYPE_CHECKING

from aiohttp import web

from . import (
    CHANGELOG,
    __app_name__,
    __description__,
    __version__,
    api_camera,
    api_control,
    api_data,
    api_display,
    api_modules,
    api_orca,
    api_vision,
    assets,
    i18n,
)
from .appapi import AppApi
from .i18n import tr
from .webcommon import Ctx, json_response, msg_of, _err

if TYPE_CHECKING:
    from .__main__ import Bridge

log = logging.getLogger("web")
STARTED = time.time()


@web.middleware
async def language(request: web.Request, handler):
    """Texts of this request in the language the device asked for (i18n.request_lang), else the bridge default."""
    token = i18n.use(i18n.request_lang(request.headers, request.query))
    try:
        return await handler(request)
    finally:
        i18n.reset(token)


@web.middleware
async def cors(request: web.Request, handler):
    if request.method == "OPTIONS":
        resp = web.Response()
    else:
        try:
            resp = await handler(request)
        except web.HTTPException as e:
            resp = e
    if getattr(resp, "prepared", False):   # stream: headers are already sent (the handler sets them itself)
        return resp
    if request.path.startswith("/static/"):
        resp.headers["Cache-Control"] = assets.NO_CACHE
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return resp


def build_app(bridge: "Bridge") -> web.Application:
    i18n.bind(lambda: getattr(bridge.cfg, "language", i18n.SOURCE_LANG))
    app = web.Application(middlewares=[language, cors])
    r = web.RouteTableDef()

    ctx = Ctx(bridge)
    need_device = ctx.need_device

    @r.get("/api/health")
    async def health(_):
        cfg = bridge.cfg
        return json_response({
            "app": __app_name__,
            "description": __description__,
            "version": __version__,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(STARTED)),
            "uptime_s": int(time.time() - STARTED),
            "python": platform.python_version(),
            "links": cfg.links(),
            "changelog": [{"version": v, "date": d, "items": i} for v, d, i in CHANGELOG[:10]],
            "settings": {
                "booking": cfg.book_usage, "book_interval_s": cfg.book_interval_s, "book_min_mm": cfg.book_min_mm,
                "gate_debounce_s": cfg.gate_debounce_s, "usage_tolerance": cfg.usage_tolerance,
                "auto_unassign_on_empty": cfg.auto_unassign_on_empty, "empty_debounce_s": cfg.empty_debounce_s,
                "write_lane_data": cfg.write_lane_data, "telemetry": cfg.telemetry,
                "telemetry_keep": cfg.telemetry_keep, "job_history": cfg.job_history,
                "slot_location_prefix": cfg.slot_location_prefix, "shelf_location": cfg.shelf_location,
                "template_vendor": cfg.template_vendor, "data_dir": cfg.data_dir, "log_level": cfg.log_level,
            },
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
        return json_response({"print_state": bridge.slots.print_state,
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
            return _err(400, tr("Expected JSON {\"spool_id\": <id or null>}"))
        spool_id = body.get("spool_id")
        if spool_id is not None:
            try:
                spool_id = int(spool_id)
            except (TypeError, ValueError):
                return _err(400, tr("spool_id must be a number or null"))
        try:
            await bridge.slots.assign(slot, spool_id)
        except ValueError as e:
            return _err(400, msg_of(e))
        except Exception as e:  # noqa: BLE001
            log.warning("Zuordnung fehlgeschlagen: %s", e)
            return _err(502, msg_of(e))
        return json_response({"ok": True, "slots": bridge.slots.slots_view()})

    @r.get("/api/spools")
    async def spools(request):
        try:
            slot = int(request.query["slot"]) if "slot" in request.query else None
        except ValueError:
            return _err(400, tr("slot must be a number"))
        return json_response({"spools": bridge.slots.assignable_spools(slot)})

    for mod in (api_modules, api_display, api_camera, api_data, api_vision, api_orca, api_control):
        mod.add_routes(r, bridge, ctx)
    app.add_routes(r)
    assets.add_routes(app)
    app.add_routes(AppApi(bridge).routes())   # Android app (docs/android-app.md)
    return app
