"""HTTP API for the Android app "Kobra Spoolman" (docs/android-app.md).

The app (and the web UI) talks only to the bridge. Reading is open like the rest of the API; everything that writes
to Spoolman needs the key of a paired device (header "Authorization: Bearer <key>", see auth.py).

Inheritance principle: the app sends only fields the user really sets. Empty Orca fields on the filament mean "from
the template or the Orca base profile" - the bridge never copies template values into the filament (exception:
density/diameter, which Spoolman requires).
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import re
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, List, Optional, Tuple

from aiohttp import web

from . import __version__, acemodel, appupdate, phase
from .assets import TAG as UI_TAG
from .orca_profiles import FIELD_MAP
from .profiles import basic_info, color_hex, find_template, orca_filament_id
from .slots import base_type
from .auth import AuthError
from .i18n import msg_of, tr
from .spoolman import NFC_UID_FIELD, TAG_NR_FIELD, extra_value
from .status import file_usage, notices
from .storage import save_json
from .webcommon import json_response

if TYPE_CHECKING:
    from .__main__ import Bridge

log = logging.getLogger("appapi")

# Spoolman standard fields the app may set on the filament: key -> conversion
FILAMENT_NATIVE: Dict[str, Callable[[Any], Any]] = {
    "name": str, "material": str, "article_number": str, "comment": str,
    "price": float, "density": float, "diameter": float, "weight": float, "spool_weight": float,
    "settings_extruder_temp": int, "settings_bed_temp": int,
    "color_hex": "color", "multi_color_hexes": "colors", "multi_color_direction": "direction",  # type: ignore[dict-item]
}
SPOOL_NATIVE: Dict[str, Callable[[Any], Any]] = {
    "initial_weight": float, "spool_weight": float, "price": float, "lot_nr": str, "comment": str,
}
# extra fields the bridge manages itself (never directly from the app)

# Orca key per Spoolman field (for the labels in the app)
ORCA_KEY = {src.split(":", 1)[1]: orca for src, orca, _ in FIELD_MAP}
ORCA_KEY.update({"color_hex": "default_filament_colour", "density": "filament_density",
                 "diameter": "filament_diameter", "material": "filament_type"})



class AppError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


# ====================================================================== conversion and checks
def _num(value: Any, typ: Callable[[Any], Any], key: str) -> Any:
    try:
        if typ is int:
            return int(round(float(value)))
        return float(value)
    except (TypeError, ValueError):
        raise AppError(400, tr("{key}: number expected, got {value}", key=key, value=repr(value))) from None


def convert_native(key: str, value: Any, spec: Any) -> Any:
    """Check and convert a standard field. None/"" = clear the field."""
    if value is None or value == "":
        return None
    if spec in (int, float):
        v = _num(value, spec, key)
        if v < 0:
            raise AppError(400, tr("{key}: must not be negative", key=key))
        return v
    if spec == "color":
        hexv = str(value).strip().lstrip("#").upper()
        if not re.fullmatch(r"[0-9A-F]{6}", hexv):
            raise AppError(400, tr("{key}: colour as RRGGBB expected", key=key))
        return hexv
    if spec == "colors":
        parts = [p.strip().lstrip("#").upper() for p in str(value).split(",") if p.strip()]
        if not parts or not all(re.fullmatch(r"[0-9A-F]{6}", p) for p in parts):
            raise AppError(400, tr("{key}: colours as RRGGBB,RRGGBB expected", key=key))
        return ",".join(parts)
    if spec == "direction":
        if value not in ("coaxial", "longitudinal"):
            raise AppError(400, tr("{key}: coaxial or longitudinal", key=key))
        return value
    return str(value).strip()


def convert_extra(field: Dict[str, Any], value: Any) -> Optional[str]:
    """Convert an extra field the Spoolman way (JSON text). None = clear the field."""
    key, ftype = field["key"], field.get("field_type")
    if value is None or value == "":
        return None
    if ftype == "integer":
        return json.dumps(_num(value, int, key))
    if ftype == "float":
        return json.dumps(_num(value, float, key))
    if ftype == "boolean":
        if isinstance(value, str):
            value = value.strip().lower() in ("1", "true", "ja", "yes", "on")
        return json.dumps(bool(value))
    if ftype == "choice":
        choices = field.get("choices") or []
        if value not in choices:
            raise AppError(400, tr("{key}: allowed are {choices}", key=key, choices=", ".join(choices)))
        return json.dumps(value)
    return json.dumps(str(value))


def build_filament_body(payload: Dict[str, Any], fields: List[Dict[str, Any]], vendors: List[Dict[str, Any]],
                        templates: List[Dict[str, Any]], creating: bool) -> Dict[str, Any]:
    """App data -> Spoolman body for POST (creating) or PATCH /filament.

    Only fields in the payload end up in the body. When creating, name and material are required; density/diameter
    come from the template if needed (Spoolman requires them)."""
    by_key = {f["key"]: f for f in fields}
    body: Dict[str, Any] = {}
    for key, value in payload.items():
        if key in FILAMENT_NATIVE:
            body[key] = convert_native(key, value, FILAMENT_NATIVE[key])
        elif key == "vendor_id":
            if value is None:
                body["vendor_id"] = None
                continue
            vid = int(_num(value, int, key))
            if not any(v.get("id") == vid for v in vendors):
                raise AppError(400, tr("There is no vendor {id}", id=vid))
            body["vendor_id"] = vid
        elif key == "extra":
            extra = {}
            for k, v in (value or {}).items():
                if k not in by_key:
                    raise AppError(400, tr("There is no extra field {key} in Spoolman", key=k))
                extra[k] = convert_extra(by_key[k], v)
            if extra:
                body["extra"] = extra
        elif key not in ("id",):
            raise AppError(400, tr("The app cannot set the field {key}", key=key))

    if creating:
        if not body.get("name"):
            raise AppError(400, tr("name missing"))
        if not body.get("material"):
            raise AppError(400, tr("material missing"))
        probe = {"material": body["material"], "extra": body.get("extra") or {}}
        tpl = find_template(probe, templates)
        for key, default in (("density", None), ("diameter", 1.75)):
            if body.get(key) is None:
                body[key] = (tpl or {}).get(key) or default
            if body.get(key) is None:
                raise AppError(400, tr("{key} missing (no template for {material})", key=key, material=body["material"]))
        body = {k: v for k, v in body.items() if v is not None}
        if "extra" in body:
            body["extra"] = {k: v for k, v in body["extra"].items() if v is not None}
    return body


# not taken over when copying a product line
COPY_SKIP = {"id", "registered", "name", "color_hex", "multi_color_hexes", "multi_color_direction",
             "external_id", "article_number", "vendor"}


def copy_filament_body(src: Dict[str, Any], overrides: Dict[str, Any], fields: List[Dict[str, Any]],
                       vendors: List[Dict[str, Any]], templates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """New colour of a product line: all values of src except name/colour/IDs, then overrides."""
    payload: Dict[str, Any] = {k: v for k, v in src.items() if k in FILAMENT_NATIVE and k not in COPY_SKIP
                               and v is not None}
    if (src.get("vendor") or {}).get("id"):
        payload["vendor_id"] = src["vendor"]["id"]
    known = {f["key"] for f in fields}
    extra = {k: extra_value(src, k) for k in (src.get("extra") or {}) if k in known}
    extra.update((overrides.get("extra") or {}))
    payload.update({k: v for k, v in overrides.items() if k != "extra"})
    payload["extra"] = extra
    return build_filament_body(payload, fields, vendors, templates, creating=True)


def build_spool_body(payload: Dict[str, Any], filament: Dict[str, Any], shelf: str) -> Dict[str, Any]:
    body: Dict[str, Any] = {"filament_id": filament["id"], "location": shelf}
    for key, value in payload.items():
        if key in SPOOL_NATIVE:
            v = convert_native(key, value, SPOOL_NATIVE[key])
            if v is not None:
                body[key] = v
        elif key not in ("filament_id", "slot"):
            raise AppError(400, tr("The app cannot set the field {key} on the spool", key=key))
    if "initial_weight" not in body and filament.get("weight"):
        body["initial_weight"] = filament["weight"]
    if "spool_weight" not in body and filament.get("spool_weight"):
        body["spool_weight"] = filament["spool_weight"]
    return body


SPOOL_PATCH = {**SPOOL_NATIVE, "remaining_weight": float}


def build_spool_patch(payload: Dict[str, Any], spool: Dict[str, Any],
                      slot_from_location: Callable[[Optional[str]], Optional[int]]) -> Dict[str, Any]:
    """Changes to a spool (weights, lot, note, storage location on the shelf).

    Slots never go through the location but through the assignment (spool/{id}/location), so bridge, ACE and Orca keep
    the same view."""
    body: Dict[str, Any] = {}
    for key, value in payload.items():
        if key in SPOOL_PATCH:
            body[key] = convert_native(key, value, SPOOL_PATCH[key])
        elif key == "location":
            loc = str(value or "").strip()
            if not loc:
                raise AppError(400, tr("location must not be empty"))
            if slot_from_location(loc) or slot_from_location(spool.get("location")):
                raise AppError(400, tr("Change slots through the assignment, not through the location"))
            body["location"] = loc
        else:
            raise AppError(400, tr("The field {key} cannot be changed on the spool", key=key))
    if body.get("remaining_weight") is None:
        body.pop("remaining_weight", None)
    return body


# ====================================================================== tags
def choose_tag_nr(used: Iterable[int], lo: int, hi: int, rng: random.Random) -> int:
    """Random, still free tag number in the range lo..hi."""
    taken = set(used)
    if hi < lo or hi - lo + 1 <= len([u for u in taken if lo <= u <= hi]):
        raise AppError(409, tr("No free tag number left between {lo} and {hi}", lo=lo, hi=hi))
    for _ in range(1000):
        n = rng.randint(lo, hi)
        if n not in taken:
            return n
    return next(n for n in range(lo, hi + 1) if n not in taken)


def normalize_uid(uid: Any) -> str:
    """NFC UID as hex without separators, upper case. Empty if it is not a UID."""
    s = re.sub(r"[\s:\-]", "", str(uid or "")).upper()
    return s if re.fullmatch(r"[0-9A-F]{8,20}", s) else ""


MAX_TAGS = 2      # ACE 2 Pro: one tag per spool side, both with the same content


def uids_of(spool: Dict[str, Any]) -> List[str]:
    """NFC IDs of a spool (field nfc_uid, several separated by commas; old entries: one)."""
    raw = extra_value(spool, "nfc_uid") or ""
    out: List[str] = []
    for part in str(raw).split(","):
        u = normalize_uid(part)
        if u and u not in out:
            out.append(u)
    return out


def tag_content(spool: Dict[str, Any], templates: List[Dict[str, Any]], tag_nr: int, prefix: str) -> Dict[str, Any]:
    """What the app writes onto the tag in the ACE format (the app does the encoding).

    Temperatures: range of print and first-layer value (filament, else template). The ACE takes the minimum as the
    slot temperature."""
    fil = spool.get("filament") or {}
    info = basic_info(fil, templates)
    tpl = None if extra_value(fil, "orca_basis") else find_template(fil, templates)

    def pick(native: Optional[str], extra: Optional[str]) -> Optional[int]:
        for obj in (fil, tpl):
            if not obj:
                continue
            v = obj.get(native) if native else extra_value(obj, extra)
            if v not in (None, ""):
                return int(round(float(v)))
        return None

    def span(*vals: Optional[int]) -> Tuple[Optional[int], Optional[int]]:
        vs = [v for v in vals if v]
        return (min(vs), max(vs)) if vs else (None, None)

    nozzle = span(pick("settings_extruder_temp", None), pick(None, "nozzle_temp_first_layer"))
    bed = span(pick("settings_bed_temp", None), pick(None, "bed_temp_first_layer"))
    diameter = float(fil.get("diameter") or 1.75)
    density = float(fil.get("density") or 1.24)
    weight = spool.get("initial_weight") or fil.get("weight")
    length_m = None
    if weight:
        length_m = round(float(weight) / density / (math.pi * (diameter / 2) ** 2), 1)   # g/(g/cm3)/mm2 = m
    return {
        "tag_nr": tag_nr,
        "sku": f"{prefix}-{tag_nr}",
        "brand": info["vendor"],
        "material": base_type(info["material"]) or info["material"],
        "color": info["color"] or color_hex(fil),
        "nozzle_min": nozzle[0], "nozzle_max": nozzle[1],
        "bed_min": bed[0], "bed_max": bed[1],
        "diameter_mm": diameter,
        "weight_g": float(weight) if weight else None,
        "length_m": length_m,
    }


# ====================================================================== printer state
def printer_state(status: Dict[str, Dict[str, Any]], connected: bool, klippy_ready: bool,
                  active_slot: Optional[int], steps: Optional[phase.ChangeSteps] = None) -> Dict[str, Any]:
    """State for the app from the bridge's Moonraker subscription (no extra load on the printer)."""
    ps = status.get("print_stats") or {}
    vsd = status.get("virtual_sdcard") or {}
    if not connected or not klippy_ready:
        state = "offline"
    else:
        state = ps.get("state") or "standby"
    running = state in ("printing", "paused")
    progress = vsd.get("progress") if running else None
    duration = ps.get("print_duration") if running else None
    eta = None
    if progress and duration and 0.01 < progress < 1:
        eta = int(duration * (1 - progress) / progress)
    # a tool change of the ACE driver is running (ACEPRO: target set, not loaded yet; Rinkhals: mmu action)
    action = (acemodel.changing(status) if running else None) or ""
    shows_file = running or state in ("complete", "cancelled", "error")
    info = ps.get("info") or {}
    ph = phase.describe(status, steps) if state != "offline" else None
    return {
        "state": state,
        "file": (ps.get("filename") or None) if shows_file else None,
        "progress": round(float(progress), 4) if progress is not None else None,
        "print_duration_s": int(duration) if duration else None,
        "eta_s": eta,
        "message": ps.get("message") or None,
        # Moonraker reachable but Klipper not ready (emergency stop, error): web/app offer "reload Klipper"
        "moonraker_connected": bool(connected),
        "klippy_ready": bool(connected and klippy_ready),
        "active_slot": active_slot,
        "mmu_action": action or None,
        "changing_filament": bool(action),
        "layer": info.get("current_layer") if running and info.get("total_layer") else None,
        "layers": info.get("total_layer") if running and info.get("total_layer") else None,
        # what is happening right now ("Heat soak 5/15 min", "Change to slot 2 · loading" ...), None = state only
        "phase": ph["text"] if ph else None,
        "phase_key": ph["key"] if ph else None,
        **machine_state(status),
    }


def _heater(h: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not h or h.get("temperature") is None:
        return None
    return {"temp": round(float(h["temperature"]), 1), "target": round(float(h.get("target") or 0), 1),
            "power": round(float(h.get("power") or 0), 2)}


FANS = (("part", tr("Part"), "fan"), ("box", tr("Enclosure"), "fan_generic box_fan"),
        ("filter", tr("Air filter"), "fan_generic air_filter_fan"))


def machine_state(status: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Temperatures, fans, speed and flow from the subscription (only what the printer reports)."""
    gm = status.get("gcode_move") or {}
    fans = []
    for key, name, obj in FANS:
        f = status.get(obj)
        if f and f.get("speed") is not None:
            fan = {"key": key, "name": name, "speed": round(float(f["speed"]), 2)}
            if f.get("rpm") is not None:
                fan["rpm"] = int(f["rpm"])
            fans.append(fan)
    def factor(k: str) -> Optional[float]:
        return round(float(gm[k]), 2) if gm.get(k) is not None else None
    return {
        "nozzle": _heater(status.get("extruder")),
        "bed": _heater(status.get("heater_bed")),
        "fans": fans,
        "speed_factor": factor("speed_factor"),
        "flow_factor": factor("extrude_factor"),
        "speed_mode": gm.get("speed_mode"),
    }


# ====================================================================== routes
class AppApi:
    def __init__(self, bridge: "Bridge", rng: Optional[random.Random] = None):
        self.bridge = bridge
        self.rng = rng or random.SystemRandom()
        self.bases_file = os.path.join(bridge.cfg.data_dir, "orca_bases.json")
        self.update = appupdate.load()

    # ------------------------------------------------------------ helpers
    def _device(self, request: web.Request) -> Optional[Dict[str, Any]]:
        return self.bridge.devices.identify(request.headers.get("Authorization"))

    def _check_token(self, request: web.Request) -> None:
        self.bridge.devices.require(request.headers.get("Authorization"))

    async def _json(self, request: web.Request) -> Dict[str, Any]:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            raise AppError(400, tr("JSON body expected")) from None
        if not isinstance(body, dict):
            raise AppError(400, tr("Expected a JSON object"))
        return body

    def _filament(self, fid: int) -> Dict[str, Any]:
        fil = self.bridge.sm.filament(fid)
        if not fil or self.bridge.sm.is_template(fil):
            raise AppError(404, tr("Filament {id} not found", id=fid))
        return fil

    def _spool(self, sid: int) -> Dict[str, Any]:
        sp = self.bridge.sm.spool(sid)
        if not sp:
            raise AppError(404, tr("Spool {id} not found (archived?)", id=sid))
        return sp

    def orca_bases(self) -> List[str]:
        try:
            with open(self.bases_file, encoding="utf-8") as fh:
                return json.load(fh).get("names") or []
        except Exception:  # noqa: BLE001
            return []

    def filament_view(self, fil: Dict[str, Any]) -> Dict[str, Any]:
        sm = self.bridge.sm
        info = basic_info(fil, sm.templates())
        spools = [s for s in sm.spools if (s.get("filament") or {}).get("id") == fil["id"]]
        return {
            **info,
            "vendor_id": (fil.get("vendor") or {}).get("id"),
            "orca_id": orca_filament_id(fil["id"]),
            "density": fil.get("density"), "diameter": fil.get("diameter"),
            "weight": fil.get("weight"), "spool_weight": fil.get("spool_weight"), "price": fil.get("price"),
            "native": {k: fil.get(k) for k in FILAMENT_NATIVE if fil.get(k) is not None},
            "extra": {k: extra_value(fil, k) for k in (fil.get("extra") or {})},
            "spools": len(spools),
        }

    def spool_view(self, sp: Dict[str, Any]) -> Dict[str, Any]:
        out = self.bridge.slots.spool_info(sp)
        out["archived"] = bool(sp.get("archived"))
        for k in ("comment", "spool_weight", "price", "remaining_length", "first_used", "registered"):
            out[k] = sp.get(k)
        out["tag_nr"] = extra_value(sp, "tag_nr")
        uids = uids_of(sp)
        out["nfc_uid"] = uids[0] if uids else None       # older apps know only one ID
        out["nfc_uids"] = uids
        return out

    def _with_tag(self, info: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Add tag number and NFC ID to the spool info of the slot view."""
        if not info:
            return info
        raw = self.bridge.sm.spool(info["spool_id"]) or {}
        uids = uids_of(raw)
        return {**info, "tag_nr": extra_value(raw, "tag_nr"), "nfc_uid": uids[0] if uids else None, "nfc_uids": uids}

    async def _ensure_spool_fields(self) -> None:
        sm = self.bridge.sm
        await sm.ensure_field("spool", "nfc_uid", NFC_UID_FIELD)
        await sm.ensure_field("spool", "tag_nr", TAG_NR_FIELD)

    async def _patch_spool_extra(self, sid: int, extra: Dict[str, Optional[str]]) -> Dict[str, Any]:
        sm = self.bridge.sm
        await self._ensure_spool_fields()
        res = await sm.patch_spool(sid, {"extra": extra})
        await sm.refresh()
        return res

    # ------------------------------------------------------------ handlers
    def routes(self) -> web.RouteTableDef:
        r = web.RouteTableDef()
        b = self.bridge

        def handler(write: bool):
            def deco(fn):
                async def wrapped(request: web.Request):
                    try:
                        if write:
                            self._check_token(request)
                        return await fn(request)
                    except (AppError, AuthError) as e:
                        return json_response({"error": msg_of(e)}, status=e.status)
                    except LookupError as e:
                        return json_response({"error": msg_of(e)}, status=404)
                    except Exception as e:  # noqa: BLE001
                        log.warning("App API %s %s: %s", request.method, request.path, e)
                        return json_response({"error": msg_of(e)}, status=502)
                return wrapped
            return deco

        # ------------------------------------------------ app update (APK in the image, see appupdate.py)
        @r.get("/api/app/update")
        @handler(write=False)
        async def app_update(_):
            return json_response(appupdate.public(self.update))

        @r.get("/api/app/update/apk")
        async def app_update_apk(_):
            if not self.update:
                return json_response({"error": tr("This bridge does not include an app")}, status=404)
            return web.FileResponse(self.update["path"], headers={
                "Content-Type": "application/vnd.android.package-archive",
                "Content-Disposition": f'attachment; filename="kobra-spoolman-app-{self.update["version"]}.apk"'})

        # ------------------------------------------------ pairing devices
        @r.get("/api/auth/status")
        @handler(write=False)
        async def auth_status(request):
            me = self._device(request)
            return json_response({"setup_required": b.devices.setup_required, "devices": len(b.devices.devices),
                                      "device": b.devices.public(me) if me else None})

        @r.post("/api/auth/pair")
        @handler(write=False)
        async def auth_pair(request):
            body = await self._json(request)
            res = b.devices.pair(str(body.get("code") or ""), str(body.get("name") or ""), str(body.get("kind") or ""))
            return json_response(res, status=201)

        @r.post("/api/auth/code")
        @handler(write=True)
        async def auth_code(_):
            return json_response(b.devices.new_code())

        @r.get("/api/auth/devices")
        @handler(write=True)
        async def auth_devices(request):
            me = self._device(request) or {}
            return json_response({"devices": [{**b.devices.public(d), "me": d["id"] == me.get("id")}
                                                  for d in b.devices.devices]})

        @r.delete("/api/auth/devices/{did}")
        @handler(write=True)
        async def auth_remove(request):
            b.devices.remove(request.match_info["did"])
            return json_response({"ok": True})

        @r.get("/api/app/state")
        @handler(write=False)
        async def state(request):
            slots = b.slots.slots_view()
            active = next((s["slot"] for s in slots if s["ace"]["active"]), None)
            in_slot = {s["spool"]["spool_id"] for s in slots if s["spool"]}
            shelf = [self.spool_view(sp) for sp in b.sm.spools if sp.get("id") not in in_slot
                     and not b.sm.is_template(sp.get("filament") or {})]
            shelf.sort(key=lambda s: (s.get("remaining_weight") is None, -(s.get("remaining_weight") or 0)))
            return json_response({
                "version": __version__,
                "ui": UI_TAG,
                "printer": printer_state(b.moon.status, b.moon.connected, b.moon.klippy_ready, active,
                                         getattr(b, "phase_steps", None)),
                "spoolman": b.sm.connected,
                "can_write": self._device(request) is not None,
                "slots": [{"slot": s["slot"], "ace": s["ace"], "hints": s["hints"], "by_tag": s.get("by_tag", False),
                           "spool": self._with_tag(s["spool"])} for s in slots],
                "shelf": shelf,
                "dryer": b.dryer.state(),
                "ace": b.ace.state(),
                "pa": b.pa.view() if getattr(b, "pa", None) else None,
                "resume": b.resume.view() if getattr(b, "resume", None) else None,
                "clog": b.clog.view() if getattr(b, "clog", None) else None,
                # USB tunnel watchdog (usb.py) - None without a watchdog
                "usb": b.usb.view() if getattr(b, "usb", None) and b.usb.available() else None,
                "prompt": b.moon.prompts.view() if getattr(b.moon, "prompts", None) else None,
                "usage": {"live": b.usage.live(), "open": b.usage.open},
                "uses": file_usage(b),                    # slots the running print file uses
                "warnings": b.safety_warnings() + b.slots.warnings,
                "notices": notices(b),
                "last_control": getattr(b, "last_control", None),
                "vision": b.vision.summary() if getattr(b, "vision", None) else None,
                # moisture estimate per spool (id -> score, state, needs_drying, hours_needed)
                "moisture": {str(sp.get("id")): {k: v for k, v in b.moisture.view(sp).items() if k in
                                                 ("score", "state", "needs_drying", "hours_needed", "out_since")}
                             for sp in b.sm.spools if sp.get("id") is not None and not b.sm.is_template(sp.get("filament") or {})}
                if getattr(b, "moisture", None) else None,
            })

        @r.get("/api/app/catalog")
        @handler(write=False)
        async def catalog(_):
            sm = b.sm
            fields = await sm.fields("filament")
            tpls = sm.templates()
            return json_response({
                "vendors": [{"id": v["id"], "name": v["name"], "empty_spool_weight": v.get("empty_spool_weight")}
                            for v in sm.vendors if v.get("name") != b.cfg.template_vendor],
                "templates": [{"id": t["id"], "name": t.get("name"), "material": t.get("material"),
                               "native": {k: t.get(k) for k in FILAMENT_NATIVE if t.get(k) is not None},
                               "extra": {k: extra_value(t, k) for k in (t.get("extra") or {})}} for t in tpls],
                "filaments": sorted((self.filament_view(f) for f in sm.filaments if not sm.is_template(f)),
                                    key=lambda f: f["display_name"].lower()),
                "fields": [{"key": f["key"], "name": f.get("name"), "type": f.get("field_type"),
                            "unit": f.get("unit"), "order": f.get("order"), "choices": f.get("choices"),
                            "orca_key": ORCA_KEY.get(f["key"])} for f in sorted(fields, key=lambda f: f.get("order") or 0)],
                "native_fields": [{"key": k, "orca_key": ORCA_KEY.get(k)} for k in FILAMENT_NATIVE],
                "orca_bases": self.orca_bases(),
                "shelf_location": b.cfg.shelf_location,
            })

        @r.get("/api/app/spools")
        @handler(write=False)
        async def spools(request):
            q = (request.query.get("q") or "").strip().lower()
            out = [self.spool_view(s) for s in b.sm.spools if not b.sm.is_template(s.get("filament") or {})]
            if q:
                out = [s for s in out if q in f"{s.get('display_name', '')} {s.get('material', '')}".lower()]
            return json_response({"spools": out})

        @r.get("/api/app/spool/{sid}")
        @handler(write=False)
        async def spool_detail(request):
            sid = int(request.match_info["sid"])
            sp = self._spool(sid)
            jobs = []
            for h in b.usage.history:
                mm = sum(x["mm"] for s in h.get("slots", []) for x in s.get("spools", []) if x.get("id") == sid)
                if mm:
                    jobs.append({"file": h.get("file"), "ended": h.get("ended"), "state": h.get("state"),
                                 "mm": round(mm, 1), "g": round(b.usage.grams(mm, sid), 1)})
            return json_response({"spool": self.spool_view(sp),
                                      "filament": self.filament_view(sp["filament"]) if sp.get("filament") else None,
                                      "jobs": jobs[:10]})

        @r.post("/api/app/vendor")
        @handler(write=True)
        async def vendor_create(request):
            body = await self._json(request)
            name = str(body.get("name") or "").strip()
            if not name:
                raise AppError(400, tr("name missing"))
            if name == b.cfg.template_vendor:
                raise AppError(400, tr("“{name}” is reserved for templates", name=name))
            existing = next((v for v in b.sm.vendors if (v.get("name") or "").lower() == name.lower()), None)
            if existing:
                raise AppError(409, tr("Vendor “{name}” already exists (id {id})", name=existing["name"], id=existing["id"]))
            data = {"name": name}
            if body.get("empty_spool_weight") not in (None, ""):
                data["empty_spool_weight"] = convert_native("empty_spool_weight", body["empty_spool_weight"], float)
            res = await b.sm.create("vendor", data)
            await b.sm.refresh()
            return json_response({"vendor": res}, status=201)

        @r.post("/api/app/filament")
        @handler(write=True)
        async def filament_create(request):
            payload = await self._json(request)
            sm = b.sm
            data = build_filament_body(payload, await sm.fields("filament"), sm.vendors, sm.templates(), creating=True)
            res = await sm.create("filament", data)
            await sm.refresh()
            fil = sm.filament(res.get("id")) or res
            return json_response({"filament": self.filament_view(fil) if fil.get("id") else res}, status=201)

        @r.post("/api/app/filament/{fid}/copy")
        @handler(write=True)
        async def filament_copy(request):
            src = self._filament(int(request.match_info["fid"]))
            overrides = await self._json(request)
            if not overrides.get("name"):
                raise AppError(400, tr("name missing (e.g. “PETG 2.0 Mint green”)"))
            sm = b.sm
            data = copy_filament_body(src, overrides, await sm.fields("filament"), sm.vendors, sm.templates())
            res = await sm.create("filament", data)
            await sm.refresh()
            fil = sm.filament(res.get("id")) or res
            return json_response({"filament": self.filament_view(fil) if fil.get("id") else res}, status=201)

        @r.patch("/api/app/filament/{fid}")
        @handler(write=True)
        async def filament_update(request):
            fil = self._filament(int(request.match_info["fid"]))
            payload = await self._json(request)
            sm = b.sm
            data = build_filament_body(payload, await sm.fields("filament"), sm.vendors, sm.templates(), creating=False)
            if not data:
                raise AppError(400, tr("Nothing to change"))
            await sm.patch_filament(fil["id"], data)
            await sm.refresh()
            return json_response({"filament": self.filament_view(sm.filament(fil["id"]) or fil)})

        @r.post("/api/app/spool")
        @handler(write=True)
        async def spool_create(request):
            payload = await self._json(request)
            try:
                fil = self._filament(int(payload.get("filament_id")))
            except (TypeError, ValueError):
                raise AppError(400, tr("filament_id missing")) from None
            slot = payload.get("slot")
            if slot is not None and not 1 <= int(slot) <= b.slots.num_gates():
                raise AppError(400, tr("There is no slot {slot}", slot=slot))
            data = build_spool_body(payload, fil, b.cfg.shelf_location)
            res = await b.sm.create("spool", data)
            await b.sm.refresh()
            if slot is not None and res.get("id"):
                await b.slots.assign(int(slot), res["id"])
            sp = b.sm.spool(res.get("id"))
            return json_response({"spool": self.spool_view(sp) if sp else res}, status=201)

        @r.patch("/api/app/spool/{sid}")
        @handler(write=True)
        async def spool_update(request):
            sp = self._spool(int(request.match_info["sid"]))
            payload = await self._json(request)
            data = build_spool_patch(payload, sp, b.cfg.slot_from_location)
            if not data:
                raise AppError(400, tr("Nothing to change"))
            await b.sm.patch_spool(sp["id"], data)
            await b.sm.refresh()
            return json_response({"spool": self.spool_view(b.sm.spool(sp["id"]) or sp)})

        @r.post("/api/app/spool/{sid}/location")
        @handler(write=True)
        async def spool_location(request):
            sp = self._spool(int(request.match_info["sid"]))
            body = await self._json(request)
            slot = body.get("slot")
            current = b.cfg.slot_from_location(sp.get("location"))
            if slot is None:
                if current:
                    await b.slots.assign(current, None)
                elif sp.get("location") != b.cfg.shelf_location:
                    await b.sm.patch_spool(sp["id"], {"location": b.cfg.shelf_location})
                    await b.sm.refresh()
            else:
                await b.slots.assign(int(slot), sp["id"])
            return json_response({"spool": self.spool_view(b.sm.spool(sp["id"]) or sp)})

        @r.post("/api/app/spool/{sid}/archive")
        @handler(write=True)
        async def spool_archive(request):
            sp = self._spool(int(request.match_info["sid"]))
            current = b.cfg.slot_from_location(sp.get("location"))
            if current:
                await b.slots.assign(current, None)
            await b.sm.patch_spool(sp["id"], {"archived": True, "location": b.cfg.shelf_location})
            await b.sm.refresh()
            return json_response({"ok": True, "spool_id": sp["id"]})

        @r.post("/api/app/tag/issue")
        @handler(write=True)
        async def tag_issue(request):
            body = await self._json(request)
            sp = self._spool(int(body.get("spool_id") or 0))
            nr = extra_value(sp, "tag_nr")
            if not nr:
                used = [int(extra_value(s, "tag_nr")) for s in b.sm.spools if extra_value(s, "tag_nr")]
                nr = choose_tag_nr(used, b.cfg.tag_nr_min, b.cfg.tag_nr_max, self.rng)
                await self._patch_spool_extra(sp["id"], {"tag_nr": json.dumps(nr)})
                sp = b.sm.spool(sp["id"]) or sp
                log.info("Spool #%s: tag number %s assigned", sp["id"], nr)
            return json_response({"spool_id": sp["id"],
                                      "tag": tag_content(sp, b.sm.templates(), int(nr), b.cfg.tag_sku_prefix)})

        @r.post("/api/app/tag/link")
        @handler(write=True)
        async def tag_link(request):
            body = await self._json(request)
            sp = self._spool(int(body.get("spool_id") or 0))
            uid = normalize_uid(body.get("uid"))
            if not uid:
                raise AppError(400, tr("uid missing or not an NFC ID (hex)"))
            other = next((s for s in b.sm.spools if s["id"] != sp["id"] and uid in uids_of(s)), None)
            if other and not body.get("force"):
                raise AppError(409, tr("This tag already belongs to spool #{id}", id=other["id"]))
            if other:
                rest = [u for u in uids_of(other) if u != uid]
                await self._patch_spool_extra(other["id"], {"nfc_uid": json.dumps(",".join(rest)) if rest else None})
            # reset (default, like older apps): this ID replaces all; else added as another tag (second spool side),
            # at most MAX_TAGS - the oldest drops out
            uids = [uid] if body.get("reset", True) else ([u for u in uids_of(sp) if u != uid] + [uid])[-MAX_TAGS:]
            await self._patch_spool_extra(sp["id"], {"nfc_uid": json.dumps(",".join(uids))})
            log.info("Spool #%s: NFC tag %s linked (%d of %d)", sp["id"], uid, len(uids), MAX_TAGS)
            return json_response({"spool": self.spool_view(b.sm.spool(sp["id"]) or sp)})

        @r.get("/api/app/tag/{uid}")
        @handler(write=False)
        async def tag_lookup(request):
            uid = normalize_uid(request.match_info["uid"])
            if not uid:
                raise AppError(400, tr("no NFC ID"))
            sp = next((s for s in b.sm.spools if uid in uids_of(s)), None)
            if not sp:
                raise AppError(404, tr("Unknown tag"))
            return json_response({"spool": self.spool_view(sp)})

        @r.post("/api/orca/bases")
        @handler(write=True)
        async def orca_bases(request):
            """The Orca plugin reports the names of the Orca filament base profiles (for the selection in the app)."""
            body = await self._json(request)
            names = sorted({str(n) for n in body.get("names") or [] if isinstance(n, str) and n.strip()})
            if not names:
                raise AppError(400, tr("names missing"))
            save_json(self.bases_file, {"names": names})
            return json_response({"ok": True, "count": len(names)})

        return r
