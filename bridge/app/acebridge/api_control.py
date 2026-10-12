"""HTTP API, area print control (tuning, pause/resume/cancel/emergency stop), console, logs.

Added by web.build_app; shared helpers in webcommon.py."""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING

import aiohttp
from aiohttp import web

from .auth import AuthError
from .console import LOG_BUFFER, check_command
from .control import ControlError, check_action, tune_commands
from .i18n import tr
from .webcommon import Ctx, json_response, msg_of, _err

if TYPE_CHECKING:
    from .__main__ import Bridge

log = logging.getLogger("web")


def add_routes(r: web.RouteTableDef, bridge: "Bridge", ctx: Ctx) -> None:
    _body = ctx.body
    _int = ctx.int_

    # ---------------------------------------------------------------- print control
    @r.post("/api/print/tune")
    async def print_tune(request: web.Request):
        """Speed, flow, fans, temperatures (paired)."""
        try:
            dev = bridge.devices.require(request.headers.get("Authorization"))
        except AuthError as e:
            return _err(e.status, msg_of(e))
        body = await _body(request)
        try:
            cmds, confirm = tune_commands(body)
        except ControlError as e:
            return _err(e.status, msg_of(e))
        if confirm and not body.get("confirm"):
            return json_response({"error": confirm, "confirm": True}, status=409)
        try:
            await bridge.moon.gcode("\n".join(cmds), source=dev.get("name") or tr("Web UI"))
        except Exception as e:  # noqa: BLE001
            return _err(400 if isinstance(e, RuntimeError) else 503, msg_of(e) or tr("Command failed"))
        return json_response({"ok": True, "sent": cmds})

    @r.post("/api/print/{action}")
    async def print_action(request: web.Request):
        """pause, resume, cancel (confirm), emergency_stop (confirm), firmware_restart (confirm, not while printing -
        the way back after an emergency stop or shutdown)."""
        try:
            dev = bridge.devices.require(request.headers.get("Authorization"))
        except AuthError as e:
            return _err(e.status, msg_of(e))
        body = await _body(request)
        # Klipper shut down (emergency stop, error): print_stats still holds the old value, e.g. "printing"
        state = ((bridge.moon.status.get("print_stats") or {}).get("state")
                 if bridge.moon.klippy_ready else "shutdown")
        try:
            method, label = check_action(request.match_info["action"], state, bool(body.get("confirm")))
        except ControlError as e:
            if e.confirm:
                return json_response({"error": msg_of(e), "confirm": True}, status=409)
            return _err(e.status, msg_of(e))
        try:
            await bridge.moon.action(method, label, source=dev.get("name") or tr("Web UI"))
        except Exception as e:  # noqa: BLE001
            return _err(400 if isinstance(e, RuntimeError) else 503, msg_of(e) or tr("Action failed"))
        bridge.last_control = {"action": request.match_info["action"], "source": dev.get("name") or "",
                               "at": round(time.time(), 1)}
        return json_response({"ok": True})

    # ---------------------------------------------------------------- console and logs
    help_cache: dict = {"at": 0.0, "commands": {}}

    def printing() -> bool:
        return (bridge.moon.status.get("print_stats") or {}).get("state") in ("printing", "paused")

    @r.get("/api/console")
    async def console_lines(request: web.Request):
        return json_response({"lines": bridge.console.since(_int(request.query.get("after"))),
                                  "printing": printing()})

    @r.get("/api/console/commands")
    async def console_commands(_):
        """Commands with description for completion (printer/gcode/help, cached for 10 min)."""
        if time.monotonic() - help_cache["at"] > 600 or not help_cache["commands"]:
            try:
                help_cache["commands"] = await bridge.moon.get_json("/printer/gcode/help") or {}
                help_cache["at"] = time.monotonic()
            except Exception as e:  # noqa: BLE001
                if not help_cache["commands"]:
                    return _err(503, tr("Command list unreadable: {error}", error=msg_of(e)))
        return json_response({"commands": help_cache["commands"]})

    @r.post("/api/console")
    async def console_send(request: web.Request):
        """Send G-code (paired). Risky commands and moves during a print only with confirm=true."""
        try:
            dev = bridge.devices.require(request.headers.get("Authorization"))
        except AuthError as e:
            return _err(e.status, msg_of(e))
        try:
            body = await request.json()
            script = str(body.get("script") or "").strip()
        except Exception:  # noqa: BLE001
            return _err(400, tr("Expected JSON {\"script\": \"G28\", \"confirm\": false}"))
        if not script:
            return _err(400, tr("No command"))
        reason = check_command(script, printing())
        if reason and not body.get("confirm"):
            return json_response({"error": reason, "confirm": True}, status=409)
        try:
            await bridge.moon.gcode(script, timeout=120, source=dev.get("name") or tr("Web UI"))
        except Exception as e:  # noqa: BLE001
            return _err(400 if isinstance(e, RuntimeError) else 503, msg_of(e) or tr("Command failed"))
        return json_response({"ok": True})

    @r.get("/api/logs")
    async def logs(request: web.Request):
        return json_response({"lines": LOG_BUFFER.since(_int(request.query.get("after")),
                                                            request.query.get("level") or "DEBUG")})

    @r.get("/api/logs.txt")
    async def logs_text(_):
        return web.Response(text=LOG_BUFFER.text(), content_type="text/plain", headers={
            "Content-Disposition": f'attachment; filename="ace-lane-bridge-{time.strftime("%Y%m%d-%H%M")}.log"'})

    @r.get("/api/logs/printer")
    async def printer_logs(_):
        """Log files Moonraker serves (klippy.log, moonraker.log, ...)."""
        try:
            files = await bridge.moon.get_json("/server/files/list?root=logs") or []
        except Exception as e:  # noqa: BLE001
            return _err(503, tr("Printer logs unreadable: {error}", error=msg_of(e)))
        files = [{"name": f.get("path"), "size": f.get("size"), "modified": f.get("modified")}
                 for f in files if f.get("path") and "/" not in f["path"]]
        return json_response({"files": sorted(files, key=lambda f: -(f["modified"] or 0))})

    @r.get("/api/logs/printer/{name}")
    async def printer_log_tail(request: web.Request):
        """Only the end of a printer log file (HTTP range) - the files are many MB."""
        name = request.match_info["name"]
        if not re.fullmatch(r"[\w.\-]+", name):
            return _err(400, tr("Invalid file name"))
        kb = max(4, min(1024, _int(request.query.get("kb"), 200)))
        url = f"{bridge.cfg.moonraker_url}/server/files/logs/{name}"
        try:
            async with bridge.session.get(url, headers={**bridge.moon._headers(), "Range": f"bytes=-{kb * 1024}"},
                                          timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 404:
                    return _err(404, tr("File not found"))
                resp.raise_for_status()
                limit = kb * 1024
                if resp.status == 206:
                    data, partial = await resp.read(), True
                else:                                # server without range support: read through, keep the end
                    data, total = b"", 0
                    async for chunk in resp.content.iter_chunked(65536):
                        total += len(chunk)
                        data = (data + chunk)[-limit:]
                    partial = total > limit
        except Exception as e:  # noqa: BLE001
            return _err(503, tr("Printer log unreadable: {error}", error=msg_of(e)))
        text = data[-kb * 1024:].decode("utf-8", "replace")
        if partial and "\n" in text:
            text = text.split("\n", 1)[1]                         # drop the cut first line
        return web.Response(text=text, content_type="text/plain", headers={"X-Partial": "1" if partial else "0"})
