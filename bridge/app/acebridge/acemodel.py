"""Sicht auf die ACE unter Klipper mit dem ACEPRO-Treiber (Kobra-S1/ACEPRO).

Einzige Stelle, die die Moonraker-Objekte des Treibers liest. Alle anderen Teile der Bridge (Slots, Verbrauch,
Trockner, Web, App, MQTT) arbeiten mit den Woerterbuechern von hier.

Objekte (Stand ACEPRO dev c89fe17, Beispiel: tests/data/acepro_status_2026-10-09.json):
- `ace`:            current_index (geladenes Werkzeug, -1 = keins), target_index, endless_spool_enabled/_match_mode,
                    toolhead_sensor, rdm_sensor
- `ace_instance_0`: slots[] (status "ready"/"empty"/"shifting"…, color [R,G,B], material, temp, rfid, sku),
                    dryer_status (remain_time/duration in Sekunden), temp, humidity, connection_state, firmware
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

# Abo bei Moonraker (Felder: None = alle)
SUBSCRIBE = {
    "ace": None,
    "ace_instance_0": None,
    "filament_switch_sensor filament_runout_nozzle": ["filament_detected"],
    "filament_tracker filament_runout_rdm": ["filament_detected", "encoder_pulse", "filament_distance"],
}

SLOTS_PER_ACE = 4
EMPTY_STATES = ("empty", "")


def _instance(status: Dict[str, Any], n: int = 0) -> Dict[str, Any]:
    return status.get(f"ace_instance_{n}") or {}


def connected(status: Dict[str, Any]) -> bool:
    """Treiber geladen und ACE verbunden."""
    inst = _instance(status)
    return bool(inst) and inst.get("connection_state", "connected") == "connected"


def num_slots(status: Dict[str, Any]) -> int:
    slots = _instance(status).get("slots")
    return len(slots) if isinstance(slots, list) and slots else SLOTS_PER_ACE


def color_hex(rgb: Any) -> str:
    """[R, G, B] (ACEPRO) -> "RRGGBB"; Schwarz [0,0,0] eines leeren Slots -> ""."""
    if isinstance(rgb, (list, tuple)) and len(rgb) >= 3:
        try:
            r, g, b = (max(0, min(255, int(v))) for v in rgb[:3])
        except (TypeError, ValueError):
            return ""
        return f"{r:02X}{g:02X}{b:02X}"
    s = str(rgb or "").strip().lstrip("#").upper()
    return s[:6] if len(s) >= 6 and all(c in "0123456789ABCDEF" for c in s[:6]) else ""


def tag_number(sku: Any) -> Optional[int]:
    """Tag-Nummer aus der SKU: Zahl hinter dem letzten Bindestrich (AHPEBK-34532 -> 34532)."""
    m = re.search(r"-(\d+)\s*$", str(sku or ""))
    return int(m.group(1)) if m else None


def active_slot(status: Dict[str, Any]) -> Optional[int]:
    """Geladenes Werkzeug (0-basiert) laut Treiber, None = keins. Kein Flackern beim Laden wie bei GoKlipper."""
    try:
        idx = int((status.get("ace") or {}).get("current_index", -1))
    except (TypeError, ValueError):
        return None
    return idx if idx >= 0 else None


def target_slot(status: Dict[str, Any]) -> Optional[int]:
    """Ziel eines laufenden Werkzeugwechsels (0-basiert), sonst None."""
    try:
        idx = int((status.get("ace") or {}).get("target_index", -1))
    except (TypeError, ValueError):
        return None
    return idx if idx >= 0 else None


def consuming_slot(status: Dict[str, Any]) -> Optional[int]:
    """Slot, dem Filamentverbrauch gerade gehoert.

    Werkzeugwechsel unter ACEPRO (mit Patch 0003 zaehlt filament_used jede Bewegung sofort):
    alter Slot noch geladen (current = alt, target = neu): Schneiden/Zurueckziehen -> alter Slot;
    nach dem Entladen (current = -1, target = neu): Laden bis zur Duese -> neuer Slot;
    danach current = neu (Spuelen, Druck)."""
    cur = active_slot(status)
    return cur if cur is not None else target_slot(status)


def slot(status: Dict[str, Any], index: int, ready: bool = True) -> Dict[str, Any]:
    """Ein Slot (0-basiert) in der Form, mit der die Bridge arbeitet.

    ready: Klipper bereit - sonst gilt kein Slot als belegt (Werte waeren veraltet)."""
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
    """Trockner, Feuchte und Temperatur der ACE."""
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


def sensors(status: Dict[str, Any]) -> Dict[str, Any]:
    """Kopf-Sensor und RDM (Ruecklauf-Modul) am Drucker."""
    nozzle = status.get("filament_switch_sensor filament_runout_nozzle") or {}
    rdm = status.get("filament_tracker filament_runout_rdm") or {}
    return {"toolhead": nozzle.get("filament_detected"), "rdm": rdm.get("filament_detected"),
            "rdm_pulses": rdm.get("encoder_pulse"), "rdm_distance_mm": rdm.get("filament_distance")}
