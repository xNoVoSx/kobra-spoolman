"""HTTP API, area Klipper modules and ACE: dryer, auto PA, resume, switches (incl. USB watchdog, purge log), clog
detection, ACE settings.

Added by web.build_app; shared helpers in webcommon.py."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiohttp import web

from . import acemodel, features
from .ace import AceError
from .clog import ClogError
from .i18n import tr
from .pa import PaError
from .resume import ResumeError
from .direct import DirectError
from .nozzle import NozzleError
from .switches import SwitchError
from .webcommon import Ctx, json_response, msg_of, _err

if TYPE_CHECKING:
    from .__main__ import Bridge

log = logging.getLogger("web")


def add_routes(r: web.RouteTableDef, bridge: "Bridge", ctx: Ctx) -> None:
    need_device = ctx.need_device

    # ---------------------------------------------------------------- dryer (ACE)
    async def _dryer_call(coro):
        try:
            res = await coro
        except ValueError as e:
            return _err(400, msg_of(e))
        except ConnectionError as e:
            return _err(503, tr("Printer not ready: {error}", error=msg_of(e)))
        except Exception as e:  # noqa: BLE001
            log.warning("Dryer: %s", e)
            return _err(502, msg_of(e))
        return json_response({"ok": True, "result": res, "dryer": bridge.dryer.state()})

    @r.get("/api/dryer")
    async def dryer_state(_):
        return json_response(bridge.dryer.state())

    @r.post("/api/dryer/start")
    @need_device
    async def dryer_start(request: web.Request):
        try:
            body = await request.json() if request.can_read_body else {}
            temp = float(body["temp"]) if body.get("temp") not in (None, "") else None
            hours = float(body["hours"]) if body.get("hours") not in (None, "") else None
        except Exception:  # noqa: BLE001
            return _err(400, tr("Expected JSON {\"temp\": <degC or null>, \"hours\": <h or null>}"))
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
            return _err(400, tr("Expected a JSON object"))

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
            return _err(400, tr("Expected JSON {\"at\": <ISO time or seconds>, \"temp\": <degC or null>, "
                                "\"hours\": <h or null>}"))

        async def apply():
            return bridge.dryer.set_schedule(at, temp, hours)
        return await _dryer_call(apply())

    @r.delete("/api/dryer/schedule")
    @need_device
    async def dryer_schedule_clear(_):
        async def apply():
            bridge.dryer.clear_schedule()
        return await _dryer_call(apply())

    # ---------------------------------------------------------------- auto PA (Klipper module kobra_pa)
    async def _pa_call(coro):
        try:
            await coro
            return json_response({"ok": True, **bridge.pa.view()})
        except PaError as e:
            return _err(e.status, msg_of(e))
        except Exception as e:  # noqa: BLE001
            log.warning("Auto-PA: %s", e)
            return _err(502, msg_of(e))

    @r.get("/api/pa")
    async def pa_state(_):
        return json_response(bridge.pa.view())

    @r.post("/api/pa/switch")
    @need_device
    async def pa_switch(request: web.Request):
        try:
            body = await request.json()
            assert isinstance(body, dict)
        except Exception:  # noqa: BLE001
            return _err(400, tr("Expected JSON {\"enabled\": true, \"auto\": false}"))
        en, au = body.get("enabled"), body.get("auto")
        if any(v is not None and not isinstance(v, bool) for v in (en, au)):
            return _err(400, tr("enabled/auto: true or false"))
        return await _pa_call(bridge.pa.switch(en, au))

    @r.post("/api/pa/calibrate")
    @need_device
    async def pa_calibrate(request: web.Request):
        try:
            slot = int((await request.json()).get("slot"))
        except Exception:  # noqa: BLE001
            return _err(400, tr("Expected JSON {\"slot\": 1}"))

        async def start():
            bridge.pa.calibrate(slot)
        return await _pa_call(start())

    @r.post("/api/pa/forget")
    @need_device
    async def pa_forget(request: web.Request):
        try:
            fid = int((await request.json()).get("filament_id"))
        except Exception:  # noqa: BLE001
            return _err(400, tr("Expected JSON {\"filament_id\": 5}"))
        return await _pa_call(bridge.pa.forget(fid))

    # ---------------------------------------------------------------- resume after power loss
    async def _resume_call(coro):
        try:
            await coro
            return json_response({"ok": True, **bridge.resume.view()})
        except ResumeError as e:
            return _err(e.status, msg_of(e))
        except Exception as e:  # noqa: BLE001
            log.warning("Resume: %s", e)
            return _err(502, msg_of(e))

    @r.get("/api/resume")
    async def resume_state(_):
        return json_response(bridge.resume.view())

    @r.post("/api/resume")
    @need_device
    async def resume_start(request: web.Request):
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        if body.get("confirm") is not True:
            return _err(409, tr("Check the part first – then resume with {\"confirm\": true}"))

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
            return _err(400, tr("Expected JSON {\"enabled\": true}"))
        return await _resume_call(bridge.resume.switch(en))

    # ---------------------------------------------------------------- switches of the Klipper modules (display, web, app)
    @r.get("/api/switches")
    async def switches_state(_):
        return json_response(bridge.switches.view())

    # ---------------------------------------------------------------- all features in one list (features.py)
    @r.get("/api/features")
    async def features_view(_):
        return json_response(features.view(bridge))

    @r.post("/api/features/{key}")
    @need_device
    async def feature_switch(request: web.Request):
        try:
            body = await request.json()
            on = body["on"]
        except Exception:  # noqa: BLE001
            return _err(400, tr("Expected JSON {\"on\": true}"))
        try:
            return json_response(await features.switch(bridge, request.match_info["key"], on))
        except features.FeatureError as e:
            return _err(e.status, msg_of(e))

    # ---------------------------------------------------------------- setup page (setup.py)
    @r.get("/api/setup")
    async def setup_view(_):
        """State of the first start and what the bridge found: setup, platform, ACE, Spoolman, printer modules."""
        fv = features.view(bridge)
        found = {
            "platform": getattr(bridge.moon, "platform", "klipper"),
            "printer": bool(bridge.moon.connected and bridge.moon.klippy_ready),
            "ace": acemodel.variant(bridge.moon.status),
            "spoolman": bool(bridge.sm.connected), "spoolman_version": bridge.sm.version,
            # camera: True = an image came, False = it failed, None = not asked yet (it runs only while someone watches)
            "camera": True if getattr(bridge.camera, "taken_wall", None) else (False if bridge.camera.error else None),
            "printer_modules": [i["key"] for i in fv["items"] if i["group"] == "printer" and i["available"]],
        }
        return json_response({**bridge.setup.view(), "found": found, "features": fv})

    @r.post("/api/setup/done")
    @need_device
    async def setup_done(_):
        bridge.setup.done()
        return json_response(bridge.setup.view())

    @r.get("/api/purge")
    async def purge_pairs(_):
        """Purge log per colour pair (colour/material before -> after): count, last purge lengths (Orca matrix)."""
        return json_response({"pairs": bridge.usage.purge_pairs()})

    @r.get("/api/usb")
    async def usb_state(_):
        """USB tunnel printer <-> Pi: watchdog state, switches, last events (switching through /api/switch)."""
        await bridge.usb.tick(force=True)
        return json_response(bridge.usb.view())

    @r.post("/api/switch")
    @need_device
    async def switch_set(request: web.Request):
        try:
            body = await request.json()
            key = body["key"]
            assert isinstance(key, str)
        except Exception:  # noqa: BLE001
            return _err(400, tr("Expected JSON {\"key\": \"pa\", \"value\": true}"))
        try:
            return json_response(await bridge.switches.set(key, body.get("value")))
        except SwitchError as e:
            return _err(e.status, msg_of(e))
        except Exception as e:  # noqa: BLE001
            log.warning("Switch %s: %s", key, e)
            return _err(502, msg_of(e))

    # ---------------------------------------------------------------- direct feed (direct.py)
    @r.get("/api/direct")
    async def direct_state(_):
        return json_response(bridge.direct.view())

    @r.post("/api/direct")
    @need_device
    async def direct_set(request: web.Request):
        """{"enable": true, "spool_id": 17, "unload": false} / {"enable": false}"""
        try:
            body = await request.json()
            enable = body["enable"]
            assert isinstance(enable, bool)
            spool_id = body.get("spool_id")
            assert spool_id is None or (isinstance(spool_id, int) and not isinstance(spool_id, bool))
            unload = bool(body.get("unload", False))
        except Exception:  # noqa: BLE001
            return _err(400, tr("Expected JSON {\"enable\": true, \"spool_id\": 17, \"unload\": false}"))
        try:
            return json_response(await bridge.direct.set(enable, spool_id, unload))
        except DirectError as e:
            return _err(e.status, msg_of(e))

    # ---------------------------------------------------------------- swappable hotends (nozzle.py)
    @r.get("/api/nozzle")
    async def nozzle_state(_):
        return json_response(bridge.hotends.view())

    @r.post("/api/nozzle")
    @need_device
    async def nozzle_set(request: web.Request):
        """{"hotend": "ceramic_06"} / {"check": false} / {"enabled": true} / {"z": 0.02} - any combination"""
        try:
            body = await request.json()
            assert isinstance(body, dict)
            hotend = body.get("hotend")
            assert hotend is None or isinstance(hotend, str)
            check, enabled = body.get("check"), body.get("enabled")
            assert check is None or isinstance(check, bool)
            assert enabled is None or isinstance(enabled, bool)
            z = body.get("z")
            assert z is None or (isinstance(z, (int, float)) and not isinstance(z, bool))
        except Exception:  # noqa: BLE001
            return _err(400, tr("Expected JSON {\"hotend\": \"ceramic_06\"}, {\"check\": true}, {\"enabled\": true} "
                                "or {\"z\": 0.02}"))
        try:
            return json_response(await bridge.hotends.set(hotend, check, enabled, None if z is None else float(z)))
        except NozzleError as e:
            return _err(e.status, msg_of(e))

    @r.post("/api/nozzle/pid")
    @need_device
    async def nozzle_pid(request: web.Request):
        """{"temp": 250} (optional) - measures the PID of the hotend in use, a few minutes"""
        temp = None
        if request.can_read_body:
            try:
                body = await request.json()
                temp = body.get("temp") if isinstance(body, dict) else None
                assert temp is None or (isinstance(temp, (int, float)) and not isinstance(temp, bool))
            except Exception:  # noqa: BLE001
                return _err(400, tr("Expected JSON {\"temp\": 250}"))
        try:
            return json_response(bridge.hotends.measure_pid(None if temp is None else float(temp)))
        except NozzleError as e:
            return _err(e.status, msg_of(e))

    # ---------------------------------------------------------------- clog detection
    @r.get("/api/clog")
    async def clog_state(_):
        return json_response(bridge.clog.view())

    @r.post("/api/clog/switch")
    @need_device
    async def clog_switch(request: web.Request):
        try:
            body = await request.json()
            en, act = body.get("enabled"), body.get("action")
            assert en is None or isinstance(en, bool)
            assert act is None or isinstance(act, str)
        except Exception:  # noqa: BLE001
            return _err(400, tr("Expected JSON {\"enabled\": true, \"action\": \"warn\"|\"pause\"}"))
        try:
            await bridge.clog.switch(en, act)
            return json_response({"ok": True, **bridge.clog.view()})
        except ClogError as e:
            return _err(e.status, msg_of(e))
        except Exception as e:  # noqa: BLE001
            log.warning("Clog: %s", e)
            return _err(502, msg_of(e))

    # ---------------------------------------------------------------- ACE settings
    async def _ace_call(coro):
        try:
            return json_response({"ok": True, "settings": await coro, "purge": bridge.ace.purge_preview()})
        except AceError as e:
            return _err(e.status, msg_of(e))
        except Exception as e:  # noqa: BLE001
            log.warning("ACE setting: %s", e)
            return _err(502, msg_of(e))

    @r.get("/api/ace")
    async def ace_state(request: web.Request):
        """Settings of the ACE per driver; under Rinkhals also the purge preview (?multiplier= for "what if")."""
        mult = request.query.get("multiplier")
        try:
            mult_f = float(mult) if mult not in (None, "") else None
        except ValueError:
            return _err(400, tr("Give the multiplier as a number"))
        return json_response({"settings": bridge.ace.state(), "purge": bridge.ace.purge_preview(mult_f)})

    @r.post("/api/ace/options")
    @need_device
    async def ace_options(request: web.Request):
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise TypeError
        except Exception:  # noqa: BLE001
            return _err(400, tr("Expected JSON {\"endless_spool\": true, \"endless_mode\": \"exact\"}"))
        # Rinkhals: a change during a print needs confirm_printing; ACEPRO ignores it
        confirm = bool(body.pop("confirm_printing", False))
        return await _ace_call(bridge.ace.set_options(body, confirm))

    @r.post("/api/ace/flush_multiplier")
    @need_device
    async def ace_flush_multiplier(request: web.Request):
        """Rinkhals: the firmware's purge multiplier {"value": 1.0, "confirm_printing": false} (as in bridge 2.x)."""
        try:
            body = await request.json()
            value = body["value"]
        except Exception:  # noqa: BLE001
            return _err(400, tr("Expected JSON {\"value\": 1.0}"))
        return await _ace_call(bridge.ace.set_options({"flush_multiplier": value}, bool(body.get("confirm_printing"))))
