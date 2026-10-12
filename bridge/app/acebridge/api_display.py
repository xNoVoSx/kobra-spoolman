"""HTTP API, area display: control (home, jog, load, macros), files on the printer, macro prompts, system.

Added by web.build_app; shared helpers in webcommon.py."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiohttp import web

from .auth import AuthError
from .files import FileError
from .i18n import tr
from .machine import MachineError
from .webcommon import Ctx, json_response, msg_of, _err

if TYPE_CHECKING:
    from .__main__ import Bridge

log = logging.getLogger("web")


def add_routes(r: web.RouteTableDef, bridge: "Bridge", ctx: Ctx) -> None:
    _body = ctx.body

    # ---------------------------------------------------------------- control (home, jog, load, macros)
    @r.get("/api/machine")
    async def machine_state(_):
        return json_response(await bridge.machine.view())

    @r.post("/api/machine/{action}")
    async def machine_action(request: web.Request):
        try:
            dev = bridge.devices.require(request.headers.get("Authorization"))
        except AuthError as e:
            return _err(e.status, msg_of(e))
        body = await _body(request)
        try:
            return json_response(await bridge.machine.run(request.match_info["action"], body,
                                                              source=dev.get("name") or "Display"))
        except MachineError as e:
            if e.confirm:
                return json_response({"error": msg_of(e), "confirm": True}, status=409)
            return _err(e.status, msg_of(e))

    async def _paired(request: web.Request):
        """Paired device, or the error response (second value)."""
        try:
            return bridge.devices.require(request.headers.get("Authorization")), None
        except AuthError as e:
            return None, _err(e.status, msg_of(e))

    def _confirm_or_err(e):
        if getattr(e, "confirm", None):
            return json_response({"error": msg_of(e), "confirm": True}, status=409)
        return _err(e.status, msg_of(e))

    @r.post("/api/machine-z/save")
    async def machine_zsave(request: web.Request):
        _, denied = await _paired(request)
        if denied is not None:
            return denied
        try:
            return json_response(await bridge.machine.save_z())
        except MachineError as e:
            return _err(e.status, msg_of(e))
        except Exception as e:  # noqa: BLE001
            return _err(502, tr("Spoolman: {error}", error=msg_of(e)))

    # ---------------------------------------------------------------- files on the printer (display)
    @r.get("/api/files")
    async def files_list(_):
        try:
            return json_response({"files": await bridge.files.list()})
        except Exception as e:  # noqa: BLE001
            return _err(502, tr("File list: {error}", error=msg_of(e)))

    @r.get("/api/files/thumb")
    async def files_thumb(request: web.Request):
        try:
            png = await bridge.files.thumbnail(request.query.get("path", ""))
        except Exception:  # noqa: BLE001
            png = None
        if not png:
            return _err(404, tr("No thumbnail"))
        return web.Response(body=png, content_type="image/png", headers={"Cache-Control": "max-age=3600"})

    @r.get("/api/files/check")
    async def files_check(request: web.Request):
        try:
            return json_response(await bridge.files.check(request.query.get("path", "")))
        except FileError as e:
            return _err(e.status, msg_of(e))

    @r.post("/api/files/start")
    async def files_start(request: web.Request):
        dev, denied = await _paired(request)
        if denied is not None:
            return denied
        body = await _body(request)
        try:
            return json_response(await bridge.files.start(str(body.get("path") or ""), body.get("confirm") is True,
                                                              source=dev.get("name") or "Display"))
        except FileError as e:
            return _confirm_or_err(e)
        except Exception as e:  # noqa: BLE001
            return _err(502, msg_of(e))

    # ---------------------------------------------------------------- macro prompts, system
    @r.post("/api/prompt")
    async def prompt_answer(request: web.Request):
        dev, denied = await _paired(request)
        if denied is not None:
            return denied
        body = await _body(request)
        try:
            cmd = bridge.moon.prompts.command(body.get("id"))
        except KeyError as e:
            return _err(409, msg_of(e))
        bridge.moon.prompts.close()
        try:
            await bridge.moon.gcode(cmd, source=dev.get("name") or "Display")
        except Exception as e:  # noqa: BLE001
            return _err(400, msg_of(e))
        return json_response({"ok": True})

    @r.post("/api/prompt/close")
    async def prompt_close(request: web.Request):
        _, denied = await _paired(request)
        if denied is not None:
            return denied
        bridge.moon.prompts.close()
        return json_response({"ok": True})

    @r.get("/api/system")
    async def system_info(_):
        return json_response(await bridge.machine.system())

    @r.post("/api/system/{what}")
    async def system_power(request: web.Request):
        dev, denied = await _paired(request)
        if denied is not None:
            return denied
        body = await _body(request)
        try:
            return json_response(await bridge.machine.power(request.match_info["what"], body.get("confirm") is True,
                                                                source=dev.get("name") or "Display"))
        except MachineError as e:
            return _confirm_or_err(e)
        except Exception as e:  # noqa: BLE001
            return _err(502, msg_of(e))
