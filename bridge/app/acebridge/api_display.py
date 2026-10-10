"""HTTP-API, Bereich: Display: Steuerung (homen, joggen, laden, Makros), Dateien am Drucker, Rueckfragen von Makros, System.

Eingebunden von web.build_app; gemeinsame Hilfen in webcommon.py."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiohttp import web

from .auth import AuthError
from .files import FileError
from .machine import MachineError
from .webcommon import Ctx, _err

if TYPE_CHECKING:
    from .__main__ import Bridge

log = logging.getLogger("web")


def add_routes(r: web.RouteTableDef, bridge: "Bridge", ctx: Ctx) -> None:
    _body = ctx.body

    # ---------------------------------------------------------------- Steuerung (homen, joggen, laden, Makros)
    @r.get("/api/machine")
    async def machine_state(_):
        return web.json_response(await bridge.machine.view())

    @r.post("/api/machine/{action}")
    async def machine_action(request: web.Request):
        try:
            dev = bridge.devices.require(request.headers.get("Authorization"))
        except AuthError as e:
            return _err(e.status, str(e))
        body = await _body(request)
        try:
            return web.json_response(await bridge.machine.run(request.match_info["action"], body,
                                                              source=dev.get("name") or "Display"))
        except MachineError as e:
            if e.confirm:
                return web.json_response({"error": str(e), "confirm": True}, status=409)
            return _err(e.status, str(e))

    async def _paired(request: web.Request):
        """Gekoppeltes Geraet oder Fehlerantwort (zweiter Wert)."""
        try:
            return bridge.devices.require(request.headers.get("Authorization")), None
        except AuthError as e:
            return None, _err(e.status, str(e))

    def _confirm_or_err(e):
        if getattr(e, "confirm", None):
            return web.json_response({"error": str(e), "confirm": True}, status=409)
        return _err(e.status, str(e))

    @r.post("/api/machine-z/save")
    async def machine_zsave(request: web.Request):
        _, denied = await _paired(request)
        if denied is not None:
            return denied
        try:
            return web.json_response(await bridge.machine.save_z())
        except MachineError as e:
            return _err(e.status, str(e))
        except Exception as e:  # noqa: BLE001
            return _err(502, f"Spoolman: {e}")

    # ---------------------------------------------------------------- Dateien am Drucker (Display)
    @r.get("/api/files")
    async def files_list(_):
        try:
            return web.json_response({"files": await bridge.files.list()})
        except Exception as e:  # noqa: BLE001
            return _err(502, f"Dateiliste: {e}")

    @r.get("/api/files/thumb")
    async def files_thumb(request: web.Request):
        try:
            png = await bridge.files.thumbnail(request.query.get("path", ""))
        except Exception:  # noqa: BLE001
            png = None
        if not png:
            return _err(404, "Kein Vorschaubild")
        return web.Response(body=png, content_type="image/png", headers={"Cache-Control": "max-age=3600"})

    @r.get("/api/files/check")
    async def files_check(request: web.Request):
        try:
            return web.json_response(await bridge.files.check(request.query.get("path", "")))
        except FileError as e:
            return _err(e.status, str(e))

    @r.post("/api/files/start")
    async def files_start(request: web.Request):
        dev, denied = await _paired(request)
        if denied is not None:
            return denied
        body = await _body(request)
        try:
            return web.json_response(await bridge.files.start(str(body.get("path") or ""), body.get("confirm") is True,
                                                              source=dev.get("name") or "Display"))
        except FileError as e:
            return _confirm_or_err(e)
        except Exception as e:  # noqa: BLE001
            return _err(502, str(e))

    # ---------------------------------------------------------------- Rueckfragen von Makros, System
    @r.post("/api/prompt")
    async def prompt_answer(request: web.Request):
        dev, denied = await _paired(request)
        if denied is not None:
            return denied
        body = await _body(request)
        try:
            cmd = bridge.moon.prompts.command(body.get("id"))
        except KeyError as e:
            return _err(409, str(e))
        bridge.moon.prompts.close()
        try:
            await bridge.moon.gcode(cmd, source=dev.get("name") or "Display")
        except Exception as e:  # noqa: BLE001
            return _err(400, str(e))
        return web.json_response({"ok": True})

    @r.post("/api/prompt/close")
    async def prompt_close(request: web.Request):
        _, denied = await _paired(request)
        if denied is not None:
            return denied
        bridge.moon.prompts.close()
        return web.json_response({"ok": True})

    @r.get("/api/system")
    async def system_info(_):
        return web.json_response(await bridge.machine.system())

    @r.post("/api/system/{what}")
    async def system_power(request: web.Request):
        dev, denied = await _paired(request)
        if denied is not None:
            return denied
        body = await _body(request)
        try:
            return web.json_response(await bridge.machine.power(request.match_info["what"], body.get("confirm") is True,
                                                                source=dev.get("name") or "Display"))
        except MachineError as e:
            return _confirm_or_err(e)
        except Exception as e:  # noqa: BLE001
            return _err(502, str(e))
