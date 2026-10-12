"""View of the ACE - the only place that reads the printer's ACE objects. Two drivers, recognised by the status:

ACEPRO (Klipper + the ACEPRO driver, example: tests/data/acepro_status_2026-10-09.json):
- `ace`:            current_index (loaded tool, -1 = none), target_index, endless_spool_enabled/_match_mode
- `ace_instance_0`: slots[] (status "ready"/"empty"/"shifting"…, color [R,G,B], material, temp, rfid, sku),
                    dryer_status (remain_time/duration in seconds), temp, humidity, connection_state, firmware

Rinkhals (Anycubic firmware with GoKlipper, Rinkhals' Moonraker component mmu_ace.py; docs/findings.md):
- `mmu`:            Happy-Hare-like view Rinkhals adds to every status: gate_status[] (1 = filament, 0 = empty,
                    -1 = the loaded gate), gate_material/_color ("RRGGBBAA")/_filament_name/_vendor/_temperature/
                    _spool_id (number after the dash of a tag's SKU), num_gates, ttg_map, action
- `filament_hub`:   GoKlipper's raw ACE state (subscribable, not listed): filament_hubs[0] with humidity, temp,
                    filament_model, dryer_status (duration in minutes, remain_time in seconds), slots[].rfid (2 = tag)
GoKlipper reports the loaded gate with short flickers while loading - usage.py debounces it (flickers()).

Every other part of the bridge (slots, consumption, dryer, web, app, MQTT) works with the dictionaries from here;
the write commands for slot data and the dryer are built here too.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from .i18n import tr

ACEPRO = "acepro"
RINKHALS = "rinkhals"

# Moonraker subscription. Fields named explicitly, never None ("all"): with None Klipper freezes the field list at the
# first query (webhooks.py: subscription[obj] = list(res.keys())). If the bridge subscribes while the ACE is not yet
# connected after a restart, humidity/firmware would otherwise never arrive (2026-10-10: humidity "–" after a restart).
SUBSCRIBE = {
    "ace": ["ace_instances", "ace_pro_enabled", "current_index", "target_index", "endless_spool_enabled",
            "endless_spool_match_mode"],
    "ace_instance_0": ["status", "status_code", "connection_state", "slots", "dryer_status", "temp", "humidity",
                       "feed_assist_count", "feed_assist_slot", "cont_assist_time", "rfid_sync_enabled", "firmware",
                       "model", "protocol", "instance", "usb_port", "usb_path"],
}
# Rinkhals: mmu is added to every status by Rinkhals anyway; filament_hub is GoKlipper's own object (not in
# objects/list, but subscribable - bridge 2.x ran with it for weeks)
SUBSCRIBE_RINKHALS = {"mmu": None, "filament_hub": None}
OBJECTS = ("ace", "ace_instance_0", "mmu", "filament_hub")

SLOTS_PER_ACE = 4
EMPTY_STATES = ("empty", "")
MMU_IDLE = {"", "idle", "none", "ready"}


def variant(status: Dict[str, Any]) -> Optional[str]:
    """Which driver the status comes from: ACEPRO, RINKHALS or None (no ACE objects yet)."""
    if status.get("ace_instance_0") or status.get("ace"):
        return ACEPRO
    if status.get("mmu") or status.get("filament_hub"):
        return RINKHALS
    return None


def touches(delta: Dict[str, Any]) -> bool:
    """Does a status delta concern the ACE?"""
    return any(k in delta for k in OBJECTS)


def flickers(status: Dict[str, Any]) -> bool:
    """GoKlipper reports the loaded gate with short gaps and jumps while loading: debounce it (usage.py)."""
    return variant(status) == RINKHALS


# ====================================================================== helpers
def _instance(status: Dict[str, Any], n: int = 0) -> Dict[str, Any]:
    return status.get(f"ace_instance_{n}") or {}


def _mmu(status: Dict[str, Any]) -> Dict[str, Any]:
    return status.get("mmu") or {}


def _hub(status: Dict[str, Any]) -> Dict[str, Any]:
    hubs = (status.get("filament_hub") or {}).get("filament_hubs") or []
    return hubs[0] if hubs and isinstance(hubs[0], dict) else {}


def _idx(container: Any, i: int, default: Any = None) -> Any:
    if isinstance(container, list):
        return container[i] if 0 <= i < len(container) else default
    if isinstance(container, dict):
        return container.get(str(i), container.get(i, default))
    return default


def _int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def color_hex(rgb: Any) -> str:
    """[R, G, B] (ACEPRO) or "RRGGBB[AA]" (Rinkhals) -> "RRGGBB"; black [0,0,0] of an empty slot -> ""."""
    if isinstance(rgb, (list, tuple)) and len(rgb) >= 3:
        try:
            r, g, b = (max(0, min(255, int(v))) for v in rgb[:3])
        except (TypeError, ValueError):
            return ""
        return f"{r:02X}{g:02X}{b:02X}"
    s = str(rgb or "").strip().lstrip("#").upper()
    return s[:6] if len(s) >= 6 and all(c in "0123456789ABCDEF" for c in s[:6]) else ""


def tag_number(sku: Any) -> Optional[int]:
    """Tag number from the SKU: number after the last hyphen (AHPEBK-34532 -> 34532)."""
    m = re.search(r"-(\d+)\s*$", str(sku or ""))
    return int(m.group(1)) if m else None


# ====================================================================== reading
def connected(status: Dict[str, Any]) -> bool:
    """Driver loaded and ACE connected."""
    if variant(status) == RINKHALS:
        hub = _hub(status)
        if hub:
            return str(hub.get("status") or "ready") not in ("disconnect", "disconnected", "offline")
        return bool(_mmu(status).get("gate_status"))
    inst = _instance(status)
    return bool(inst) and inst.get("connection_state", "connected") == "connected"


def num_slots(status: Dict[str, Any]) -> int:
    if variant(status) == RINKHALS:
        n = _int(_mmu(status).get("num_gates"))
        return n if n and n > 0 else SLOTS_PER_ACE
    slots = _instance(status).get("slots")
    return len(slots) if isinstance(slots, list) and slots else SLOTS_PER_ACE


def active_slot(status: Dict[str, Any]) -> Optional[int]:
    """Loaded tool (0-based) according to the driver, None = none.

    ACEPRO: current_index, no flicker. Rinkhals: the gate with gate_status -1 (the field 'gate' flickers and only
    counts when there is no gate_status)."""
    if variant(status) == RINKHALS:
        m = _mmu(status)
        st = m.get("gate_status")
        if isinstance(st, list):
            return next((i for i, v in enumerate(st) if _int(v) == -1), None)
        g = _int(m.get("gate"))
        return g if g is not None and g >= 0 else None
    idx = _int((status.get("ace") or {}).get("current_index", -1))
    return idx if idx is not None and idx >= 0 else None


def target_slot(status: Dict[str, Any]) -> Optional[int]:
    """Target of a running tool change (0-based), else None. GoKlipper does not report one."""
    if variant(status) == RINKHALS:
        return None
    idx = _int((status.get("ace") or {}).get("target_index", -1))
    return idx if idx is not None and idx >= 0 else None


def consuming_slot(status: Dict[str, Any]) -> Optional[int]:
    """Slot the filament consumption currently belongs to.

    Tool change under ACEPRO (with patch 0003 filament_used counts every move at once):
    old slot still loaded (current = old, target = new): cutting/retracting -> old slot;
    after unloading (current = -1, target = new): loading to the nozzle -> new slot;
    then current = new (purging, printing).
    Rinkhals: the loaded gate (GoKlipper's counter includes the firmware purge of the new gate)."""
    cur = active_slot(status)
    return cur if cur is not None else target_slot(status)


def changing(status: Dict[str, Any]) -> Optional[str]:
    """A tool change is running: text for the printer card ("Change to slot 3"), else None."""
    if variant(status) == RINKHALS:
        action = str(_mmu(status).get("action") or "")
        return action if action.strip().lower() not in MMU_IDLE else None
    target = target_slot(status)
    return tr("Change to slot {slot}", slot=target + 1) if target is not None else None


def tool_slot(status: Dict[str, Any], tool: int) -> int:
    """Slot (0-based) a tool T<n> of the print file uses. ACEPRO: T<n> = slot n; Rinkhals: its ttg_map."""
    if variant(status) == RINKHALS:
        ttg = _mmu(status).get("ttg_map") or []
        g = _idx(ttg, tool)
        if isinstance(g, int) and g >= 0:
            return g
    return tool


def slot(status: Dict[str, Any], index: int, ready: bool = True) -> Dict[str, Any]:
    """One slot (0-based) in the shape the bridge works with.

    ready: Klipper ready - otherwise no slot counts as loaded (values would be stale)."""
    if variant(status) == RINKHALS:
        return _slot_rinkhals(status, index, ready)
    slots = _instance(status, index // SLOTS_PER_ACE).get("slots")
    raw = slots[index % SLOTS_PER_ACE] if isinstance(slots, list) and index % SLOTS_PER_ACE < len(slots) else {}
    raw = raw or {}
    state = str(raw.get("status") or "")
    present = bool(ready and connected(status) and state not in EMPTY_STATES)
    material = str(raw.get("material") or "").strip()
    temp = _int(raw.get("temp")) or None
    bed = raw.get("hotbed_temp") or {}
    rfid = bool(raw.get("rfid"))
    return {
        "status": state,
        "present": present,
        "active": present and active_slot(status) == index,
        "material": material if present else "",
        "color": color_hex(raw.get("color")) if present else "",
        "name": material if present else "",
        "vendor": str(raw.get("brand") or "").strip() if present else "",
        "temperature": temp if present else None,
        "bed_temperature": (bed.get("max") or bed.get("min")) if present and isinstance(bed, dict) else None,
        "rfid": rfid and present,
        "sku": str(raw.get("sku") or "") if present and rfid else "",
        "tag_id": tag_number(raw.get("sku")) if present and rfid else None,
    }


def _slot_rinkhals(status: Dict[str, Any], index: int, ready: bool) -> Dict[str, Any]:
    m = _mmu(status)
    gs = _int(_idx(m.get("gate_status"), index))
    present = bool(ready and gs not in (None, 0))
    material = str(_idx(m.get("gate_material"), index) or "").strip()
    if material.lower() == "unknown":
        material = ""
    name = str(_idx(m.get("gate_filament_name"), index) or "").strip()
    temp = _int(_idx(m.get("gate_temperature"), index))
    tag = _int(_idx(m.get("gate_spool_id"), index)) or 0
    hub_slot = _idx(_hub(status).get("slots"), index) or {}
    # rfid per slot from GoKlipper (2 = tag) is more reliable than gate_spool_id > 0
    rfid = (_int(hub_slot.get("rfid")) == 2) if isinstance(hub_slot, dict) and "rfid" in hub_slot else tag > 0
    return {
        "status": str(gs) if gs is not None else "",
        "present": present,
        "active": present and gs == -1,
        "material": material if present else "",
        "color": color_hex(_idx(m.get("gate_color"), index)) if present else "",
        "name": (name if name.lower() != "unknown" else "") or material if present else "",
        "vendor": str(_idx(m.get("gate_vendor"), index) or "").strip() if present else "",
        "temperature": temp if present and temp and temp > 0 else None,
        "bed_temperature": None,
        "rfid": rfid and present,
        "sku": "",
        "tag_id": tag if present and rfid and tag > 0 else None,
    }


def dryer(status: Dict[str, Any]) -> Dict[str, Any]:
    """Dryer, humidity and temperature of the ACE."""
    if variant(status) == RINKHALS:
        return _dryer_rinkhals(status)
    inst = _instance(status)
    ds = inst.get("dryer_status") or {}
    st = ds.get("status") or "stop"

    def minutes(v: Any) -> Optional[float]:
        try:
            return round(float(v) / 60.0, 1)
        except (TypeError, ValueError):
            return None

    return {
        "present": connected(status),
        "humidity": inst.get("humidity"),
        "temp": inst.get("temp"),
        "status": st,
        "drying": st == "drying",
        "target_temp": ds.get("target_temp") or 0,
        "remaining_min": minutes(ds.get("remain_time")) if st == "drying" else 0,
        "duration_min": minutes(ds.get("duration")) if st == "drying" else 0,
        "firmware": inst.get("firmware"),
        "model": inst.get("model"),
    }


def _dryer_rinkhals(status: Dict[str, Any]) -> Dict[str, Any]:
    """GoKlipper's filament_hub (duration in minutes, remain_time in seconds). Rinkhals' own mmu_machine view reports
    humidity/remaining as 0 (it reads the wrong fields), so it is only the fallback without filament_hub."""
    h = _hub(status)
    if h:
        ds = h.get("dryer_status") or {}
        st = ds.get("status") or "stop"
        remain_s = ds.get("remain_time") or 0
        return {"present": True, "humidity": h.get("humidity"), "temp": h.get("temp"), "status": st,
                "drying": st == "drying", "target_temp": ds.get("target_temp") or 0,
                "remaining_min": round(remain_s / 60.0, 1) if st == "drying" and remain_s else 0,
                "duration_min": float(ds.get("duration") or 0) if st == "drying" else 0,
                "firmware": None, "model": h.get("filament_model")}
    unit = (status.get("mmu_machine") or {}).get("unit_0") or {}
    st = unit.get("dryer_status") or "stop"
    return {"present": bool(_mmu(status).get("gate_status")), "humidity": unit.get("dryer_humidity") or None,
            "temp": unit.get("dryer_temp"), "status": st, "drying": st == "drying",
            "target_temp": unit.get("dryer_target_temp") or 0,
            "remaining_min": float(unit.get("dryer_remaining") or 0) if st == "drying" else 0,
            "duration_min": 0, "firmware": None, "model": None}


def endless_spool(status: Dict[str, Any]) -> Dict[str, Any]:
    """ACEPRO: from the driver's object. Rinkhals keeps it in GoKlipper's config (auto_refill, read by ace.py)."""
    ace = status.get("ace") or {}
    return {"enabled": bool(ace.get("endless_spool_enabled")),
            "mode": ace.get("endless_spool_match_mode") or "exact"}


# ====================================================================== write commands
def _gcode_text(s: Any) -> str:
    """Text for the MAP of MMU_GATE_MAP: no quotes/brackets (Rinkhals reads the MAP with ast.literal_eval, the value
    stands in MAP=\"...\")."""
    return re.sub(r"\s+", " ", re.sub(r"[\"'{}\\:=;]", " ", str(s or ""))).strip()[:40]


def set_slot_command(status: Dict[str, Any], gate: int, spool_id: int, material: str, color: str,
                     temp: int, name: str = "") -> Optional[str]:
    """Material/colour/temperature of a slot without a tag (material: base type in capitals, colour RRGGBB).

    ACEPRO: ACE_SET_SLOT T= MATERIAL= COLOR=R,G,B TEMP=1-300.
    Rinkhals: Happy Hare's MMU_GATE_MAP, which Rinkhals forwards to GoKlipper as filament_hub/set_filament_info
    (refused by Rinkhals for slots with a tag)."""
    if not material or not re.fullmatch(r"[A-Z0-9-]+", material):
        return None
    color = color_hex(color) or "FFFFFF"
    if variant(status) == RINKHALS:
        entry = {"status": 1, "name": _gcode_text(name) or material, "material": material, "color": color + "FF",
                 "temp": int(temp) if temp and temp > 0 else -1, "spool_id": int(spool_id), "speed_override": 100}
        return f'MMU_GATE_MAP MAP="{repr({gate: entry})}"'
    if not 1 <= int(temp or 0) <= 300:
        return None
    r, g, b = (int(color[i:i + 2], 16) for i in (0, 2, 4))
    return f"ACE_SET_SLOT T={gate} MATERIAL={material} COLOR={r},{g},{b} TEMP={int(temp)}"


def dryer_start_command(status: Dict[str, Any], temp: int, minutes: int) -> str:
    if variant(status) == RINKHALS:
        return f"MMU_DRYER_START UNIT=0 DURATION={int(minutes)} TEMP={int(temp)}"
    return f"ACE_START_DRYING TEMP={int(temp)} DURATION={int(minutes)}"


def dryer_stop_command(status: Dict[str, Any]) -> str:
    return "MMU_DRYER_STOP UNIT=0" if variant(status) == RINKHALS else "ACE_STOP_DRYING"
