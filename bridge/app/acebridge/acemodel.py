"""View of the ACE under Klipper with the ACEPRO driver (Kobra-S1/ACEPRO).

The only place that reads the driver's Moonraker objects. Every other part of the bridge (slots, consumption, dryer,
web, app, MQTT) works with the dictionaries from here.

Objects (ACEPRO dev c89fe17, example: tests/data/acepro_status_2026-10-09.json):
- `ace`:            current_index (loaded tool, -1 = none), target_index, endless_spool_enabled/_match_mode
- `ace_instance_0`: slots[] (status "ready"/"empty"/"shifting"…, color [R,G,B], material, temp, rfid, sku),
                    dryer_status (remain_time/duration in seconds), temp, humidity, connection_state, firmware
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

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

SLOTS_PER_ACE = 4
EMPTY_STATES = ("empty", "")


def _instance(status: Dict[str, Any], n: int = 0) -> Dict[str, Any]:
    return status.get(f"ace_instance_{n}") or {}


def connected(status: Dict[str, Any]) -> bool:
    """Driver loaded and ACE connected."""
    inst = _instance(status)
    return bool(inst) and inst.get("connection_state", "connected") == "connected"


def num_slots(status: Dict[str, Any]) -> int:
    slots = _instance(status).get("slots")
    return len(slots) if isinstance(slots, list) and slots else SLOTS_PER_ACE


def color_hex(rgb: Any) -> str:
    """[R, G, B] (ACEPRO) -> "RRGGBB"; black [0,0,0] of an empty slot -> ""."""
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


def active_slot(status: Dict[str, Any]) -> Optional[int]:
    """Loaded tool (0-based) according to the driver, None = none. No flicker while loading (unlike GoKlipper)."""
    try:
        idx = int((status.get("ace") or {}).get("current_index", -1))
    except (TypeError, ValueError):
        return None
    return idx if idx >= 0 else None


def target_slot(status: Dict[str, Any]) -> Optional[int]:
    """Target of a running tool change (0-based), else None."""
    try:
        idx = int((status.get("ace") or {}).get("target_index", -1))
    except (TypeError, ValueError):
        return None
    return idx if idx >= 0 else None


def consuming_slot(status: Dict[str, Any]) -> Optional[int]:
    """Slot the filament consumption currently belongs to.

    Tool change under ACEPRO (with patch 0003 filament_used counts every move at once):
    old slot still loaded (current = old, target = new): cutting/retracting -> old slot;
    after unloading (current = -1, target = new): loading to the nozzle -> new slot;
    then current = new (purging, printing)."""
    cur = active_slot(status)
    return cur if cur is not None else target_slot(status)


def slot(status: Dict[str, Any], index: int, ready: bool = True) -> Dict[str, Any]:
    """One slot (0-based) in the shape the bridge works with.

    ready: Klipper ready - otherwise no slot counts as loaded (values would be stale)."""
    slots = _instance(status, index // SLOTS_PER_ACE).get("slots")
    raw = slots[index % SLOTS_PER_ACE] if isinstance(slots, list) and index % SLOTS_PER_ACE < len(slots) else {}
    raw = raw or {}
    state = str(raw.get("status") or "")
    present = bool(ready and connected(status) and state not in EMPTY_STATES)
    material = str(raw.get("material") or "").strip()
    try:
        temp = int(raw.get("temp") or 0) or None
    except (TypeError, ValueError):
        temp = None
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


def dryer(status: Dict[str, Any]) -> Dict[str, Any]:
    """Dryer, humidity and temperature of the ACE."""
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


def endless_spool(status: Dict[str, Any]) -> Dict[str, Any]:
    ace = status.get("ace") or {}
    return {"enabled": bool(ace.get("endless_spool_enabled")),
            "mode": ace.get("endless_spool_match_mode") or "exact"}

