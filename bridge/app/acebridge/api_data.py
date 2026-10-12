"""HTTP API, area humidity, settings, consumption (prints, open items), print recordings.

Added by web.build_app; shared helpers in webcommon.py."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from aiohttp import web

from . import printlog
from .i18n import tr
from .webcommon import Ctx, json_response, msg_of, _err

if TYPE_CHECKING:
    from .__main__ import Bridge

log = logging.getLogger("web")


def add_routes(r: web.RouteTableDef, bridge: "Bridge", ctx: Ctx) -> None:
    need_device = ctx.need_device
    paired = ctx.paired
    _body = ctx.body
    _int = ctx.int_

    # ---------------------------------------------------------------- humidity
    @r.get("/api/humidity")
    async def humidity_view(request: web.Request):
        """History of the ACE (?hours=24, at most humidity_days) with drying runs, prints and automation thresholds."""
        try:
            hours = min(float(request.query.get("hours", 24)), bridge.cfg.humidity_days * 24)
        except ValueError:
            return _err(400, tr("hours must be a number"))
        since = time.time() - hours * 3600
        prints = []
        for j in bridge.usage.history:
            try:
                start = time.mktime(time.strptime(j["started"][:19], "%Y-%m-%dT%H:%M:%S"))
                end = time.mktime(time.strptime((j.get("ended") or j["started"])[:19], "%Y-%m-%dT%H:%M:%S"))
            except (KeyError, ValueError):
                continue
            if end >= since:
                prints.append({"start": round(start), "end": round(end), "file": j.get("file"), "state": j.get("state")})
        cfg = bridge.dryer.config
        return json_response({"hours": hours, "points": bridge.humidity.points(hours),
                                  "sessions": bridge.humidity.recent_sessions(hours), "prints": prints,
                                  "automation": {"enabled": cfg.enabled, "start_above": cfg.start_above,
                                                 "stop_below": cfg.stop_below}})

    @r.get("/api/spool/{spool_id}/moisture")
    async def spool_moisture(request: web.Request):
        sid = _int(request.match_info["spool_id"], -1)
        sp = bridge.sm.spool(sid)
        if not sp:
            return _err(404, tr("Unknown spool"))
        return json_response({**bridge.moisture.view(sp), "history": bridge.moisture.history(sid)})

    @r.post("/api/spool/{spool_id}/dried")
    async def spool_dried(request: web.Request):
        """Dried outside the ACE (own dryer): {"temp": 55, "minutes": 360}."""
        if (denied := paired(request)) is not None:
            return denied
        sid = _int(request.match_info["spool_id"], -1)
        if not bridge.sm.spool(sid):
            return _err(404, tr("Unknown spool"))
        b = await _body(request)
        bridge.moisture.note_dried(sid, float(b.get("temp") or 0), float(b.get("minutes") or 0))
        return json_response({"ok": True})

    # ---------------------------------------------------------------- settings
    @r.get("/api/settings")
    async def settings_view(_: web.Request):
        return json_response(bridge.settings.view())

    @r.post("/api/settings")
    async def settings_update(request: web.Request):
        """{"<name>": value, ...} - only the ones sent; on an error nothing is applied."""
        if (denied := paired(request)) is not None:
            return denied
        try:
            bridge.settings.update(await _body(request))
        except ValueError as e:
            return _err(400, msg_of(e))
        return json_response({"ok": True, **bridge.settings.view()})

    @r.post("/api/settings/reset")
    async def settings_reset(request: web.Request):
        """{"key": "<name>"} - back to the start value from the environment."""
        if (denied := paired(request)) is not None:
            return denied
        try:
            bridge.settings.reset(str((await _body(request)).get("key") or ""))
        except ValueError as e:
            return _err(400, msg_of(e))
        return json_response({"ok": True, **bridge.settings.view()})

    # ---------------------------------------------------------------- consumption
    @r.get("/api/usage")
    async def usage(_):
        return json_response({"live": bridge.usage.live(), "last": bridge.usage.last_by_slot(),
                                  "open": bridge.usage.open})

    @r.get("/api/jobs")
    async def jobs(request: web.Request):
        try:
            limit = max(1, min(200, int(request.query.get("limit", 20))))
        except ValueError:
            limit = 20
        return json_response({"jobs": bridge.usage.history[:limit]})

    @r.get("/api/open")
    async def open_items(_):
        return json_response({"open": bridge.usage.open})

    @r.post("/api/open/{item}")
    @need_device
    async def open_book(request: web.Request):
        try:
            body = await request.json()
            spool_id = int(body["spool_id"])
        except Exception:  # noqa: BLE001
            return _err(400, tr("Expected JSON {\"spool_id\": <id>}"))
        try:
            res = await bridge.usage.resolve_open(request.match_info["item"], spool_id)
        except KeyError as e:
            return _err(404, msg_of(e))
        except ValueError as e:
            return _err(400, msg_of(e))
        except Exception as e:  # noqa: BLE001
            return _err(502, msg_of(e))
        return json_response({"ok": True, **res})

    @r.delete("/api/open/{item}")
    @need_device
    async def open_discard(request: web.Request):
        try:
            res = await bridge.usage.resolve_open(request.match_info["item"], None)
        except KeyError as e:
            return _err(404, msg_of(e))
        return json_response({"ok": True, **res})

    @r.get("/api/telemetry")
    async def telemetry(_):
        return json_response({"files": bridge.recorder.list_files()})

    @r.get("/api/telemetry/{name}/log")
    async def telemetry_log(request: web.Request):
        """Readable print log of a recording (console + important state changes)."""
        path = bridge.recorder.path_for(request.match_info["name"])
        if not path:
            return _err(404, tr("not found"))
        with open(path, encoding="utf-8", errors="replace") as f:
            text = printlog.render(f)
        name = request.match_info["name"].removesuffix(".jsonl") + ".txt"
        return web.Response(text=text, content_type="text/plain", charset="utf-8",
                            headers={"Content-Disposition": f'inline; filename="{name}"'})

    @r.get("/api/telemetry/{name}")
    async def telemetry_file(request: web.Request):
        path = bridge.recorder.path_for(request.match_info["name"])
        if not path:
            return _err(404, tr("not found"))
        return web.FileResponse(path, headers={"Content-Type": "application/x-ndjson"})
