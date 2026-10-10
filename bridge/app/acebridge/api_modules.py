"""HTTP-API, Bereich: Klipper-Module und ACE: Trockner, Auto-PA, Fortsetzen, Schalter (inkl. USB-Waechter, Spuelprotokoll), Verstopfung, ACE-Einstellungen.

Eingebunden von web.build_app; gemeinsame Hilfen in webcommon.py."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiohttp import web

from .ace import AceError
from .clog import ClogError
from .pa import PaError
from .resume import ResumeError
from .switches import SwitchError
from .webcommon import Ctx, _err

if TYPE_CHECKING:
    from .__main__ import Bridge

log = logging.getLogger("web")


def add_routes(r: web.RouteTableDef, bridge: "Bridge", ctx: Ctx) -> None:
    need_device = ctx.need_device

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

    # ---------------------------------------------------------------- Auto-PA (Klipper-Modul kobra_pa)
    async def _pa_call(coro):
        try:
            await coro
            return web.json_response({"ok": True, **bridge.pa.view()})
        except PaError as e:
            return _err(e.status, str(e))
        except Exception as e:  # noqa: BLE001
            log.warning("Auto-PA: %s", e)
            return _err(502, str(e))

    @r.get("/api/pa")
    async def pa_state(_):
        return web.json_response(bridge.pa.view())

    @r.post("/api/pa/switch")
    @need_device
    async def pa_switch(request: web.Request):
        try:
            body = await request.json()
            assert isinstance(body, dict)
        except Exception:  # noqa: BLE001
            return _err(400, "Erwartet JSON {\"enabled\": true, \"auto\": false}")
        en, au = body.get("enabled"), body.get("auto")
        if any(v is not None and not isinstance(v, bool) for v in (en, au)):
            return _err(400, "enabled/auto: true oder false")
        return await _pa_call(bridge.pa.switch(en, au))

    @r.post("/api/pa/calibrate")
    @need_device
    async def pa_calibrate(request: web.Request):
        try:
            slot = int((await request.json()).get("slot"))
        except Exception:  # noqa: BLE001
            return _err(400, "Erwartet JSON {\"slot\": 1}")

        async def start():
            bridge.pa.calibrate(slot)
        return await _pa_call(start())

    @r.post("/api/pa/forget")
    @need_device
    async def pa_forget(request: web.Request):
        try:
            fid = int((await request.json()).get("filament_id"))
        except Exception:  # noqa: BLE001
            return _err(400, "Erwartet JSON {\"filament_id\": 5}")
        return await _pa_call(bridge.pa.forget(fid))

    # ---------------------------------------------------------------- Fortsetzen nach Stromausfall
    async def _resume_call(coro):
        try:
            await coro
            return web.json_response({"ok": True, **bridge.resume.view()})
        except ResumeError as e:
            return _err(e.status, str(e))
        except Exception as e:  # noqa: BLE001
            log.warning("Fortsetzen: %s", e)
            return _err(502, str(e))

    @r.get("/api/resume")
    async def resume_state(_):
        return web.json_response(bridge.resume.view())

    @r.post("/api/resume")
    @need_device
    async def resume_start(request: web.Request):
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        if body.get("confirm") is not True:
            return _err(409, "Erst das Teil prüfen – dann mit {\"confirm\": true} fortsetzen")

        async def go():
            bridge.resume.start()
        return await _resume_call(go())

    @r.post("/api/resume/discard")
    @need_device
    async def resume_discard(_):
        return await _resume_call(bridge.resume.discard())

    @r.post("/api/resume/switch")
    @need_device
    async def resume_switch(request: web.Request):
        try:
            en = (await request.json()).get("enabled")
            assert isinstance(en, bool)
        except Exception:  # noqa: BLE001
            return _err(400, "Erwartet JSON {\"enabled\": true}")
        return await _resume_call(bridge.resume.switch(en))

    # ---------------------------------------------------------------- Schalter der Klipper-Module (Display, Web, App)
    @r.get("/api/switches")
    async def switches_state(_):
        return web.json_response(bridge.switches.view())

    @r.get("/api/purge")
    async def purge_pairs(_):
        """Spuelprotokoll je Farbpaar (Farbe/Material vorher -> nachher): Anzahl, letzte Spuelmengen (Orca-Matrix)."""
        return web.json_response({"pairs": bridge.usage.purge_pairs()})

    @r.get("/api/usb")
    async def usb_state(_):
        """USB-Tunnel Drucker <-> Pi: Zustand des Waechters, Schalter, letzte Ereignisse (Schalten ueber /api/switch)."""
        await bridge.usb.tick(force=True)
        return web.json_response(bridge.usb.view())

    @r.post("/api/switch")
    @need_device
    async def switch_set(request: web.Request):
        try:
            body = await request.json()
            key = body["key"]
            assert isinstance(key, str)
        except Exception:  # noqa: BLE001
            return _err(400, "Erwartet JSON {\"key\": \"pa\", \"value\": true}")
        try:
            return web.json_response(await bridge.switches.set(key, body.get("value")))
        except SwitchError as e:
            return _err(e.status, str(e))
        except Exception as e:  # noqa: BLE001
            log.warning("Schalter %s: %s", key, e)
            return _err(502, str(e))

    # ---------------------------------------------------------------- Verstopfung erkennen
    @r.get("/api/clog")
    async def clog_state(_):
        return web.json_response(bridge.clog.view())

    @r.post("/api/clog/switch")
    @need_device
    async def clog_switch(request: web.Request):
        try:
            body = await request.json()
            en, act = body.get("enabled"), body.get("action")
            assert en is None or isinstance(en, bool)
            assert act is None or isinstance(act, str)
        except Exception:  # noqa: BLE001
            return _err(400, "Erwartet JSON {\"enabled\": true, \"action\": \"warn\"|\"pause\"}")
        try:
            await bridge.clog.switch(en, act)
            return web.json_response({"ok": True, **bridge.clog.view()})
        except ClogError as e:
            return _err(e.status, str(e))
        except Exception as e:  # noqa: BLE001
            log.warning("Verstopfung: %s", e)
            return _err(502, str(e))

    # ---------------------------------------------------------------- ACE-Einstellungen
    async def _ace_call(coro):
        try:
            return web.json_response({"ok": True, "settings": await coro})
        except AceError as e:
            return _err(e.status, str(e))
        except Exception as e:  # noqa: BLE001
            log.warning("ACE-Einstellung: %s", e)
            return _err(502, str(e))

    @r.get("/api/ace")
    async def ace_state(request: web.Request):
        return web.json_response({"settings": bridge.ace.state()})

    @r.post("/api/ace/options")
    @need_device
    async def ace_options(request: web.Request):
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise TypeError
        except Exception:  # noqa: BLE001
            return _err(400, "Erwartet JSON {\"endless_spool\": true, \"endless_mode\": \"exact\"}")
        body.pop("confirm_printing", None)            # aeltere Clients schicken es noch mit - wird nicht gebraucht
        return await _ace_call(bridge.ace.set_options(body))
