"""HTTP-API, Bereich: Orca-Plugin: Profile, Panel-Stand, Ruecksync, Zuruecksetzen.

Eingebunden von web.build_app; gemeinsame Hilfen in webcommon.py."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from aiohttp import web

from . import __version__
from .webcommon import Ctx, _err

if TYPE_CHECKING:
    from .__main__ import Bridge

log = logging.getLogger("web")


def add_routes(r: web.RouteTableDef, bridge: "Bridge", ctx: Ctx) -> None:
    need_device = ctx.need_device

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
                      "open": len(bridge.usage.open)},
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
