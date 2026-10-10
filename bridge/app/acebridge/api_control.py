"""HTTP-API, Bereich: Drucksteuerung (Nachjustieren, Pause/Weiter/Abbrechen/Not-Aus), Konsole, Logs.

Eingebunden von web.build_app; gemeinsame Hilfen in webcommon.py."""

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
from .webcommon import Ctx, _err

if TYPE_CHECKING:
    from .__main__ import Bridge

log = logging.getLogger("web")


def add_routes(r: web.RouteTableDef, bridge: "Bridge", ctx: Ctx) -> None:
    _body = ctx.body
    _int = ctx.int_

    # ---------------------------------------------------------------- Drucksteuerung
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
        """pause, resume, cancel (Rueckfrage), emergency_stop (Rueckfrage), firmware_restart (Rueckfrage, nicht im
        Druck - der Weg zurueck nach Not-Aus/Abschaltung)."""
        try:
            dev = bridge.devices.require(request.headers.get("Authorization"))
        except AuthError as e:
            return _err(e.status, str(e))
        body = await _body(request)
        # Klipper abgeschaltet (Not-Aus, Fehler): print_stats steht noch auf dem alten Wert, z.B. "printing"
        state = ((bridge.moon.status.get("print_stats") or {}).get("state")
                 if bridge.moon.klippy_ready else "shutdown")
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
