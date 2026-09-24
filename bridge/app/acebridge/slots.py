"""Slot-Verwaltung: ACE-Zustand + Spoolman-Zuordnung -> Slot-Sicht, Auto-Freigabe, lane_data.

Die Zuordnung Slot <-> Spule lebt ausschliesslich in Spoolman (Feld "Ort" der Spule,
z.B. "ACE Slot 1"). Die Bridge haelt nur einen Cache davon.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from .config import Config
from .moonraker import Moonraker
from .profiles import basic_info
from .spoolman import Spoolman

log = logging.getLogger("slots")

PRINTING_STATES = ("printing", "paused")

# Orca-Basistypen, laengste zuerst (fuer ACE-Materialnamen ohne Spoolman-Zuordnung)
KNOWN_TYPES = sorted(["PETG-CF", "PET-CF", "PLA-CF", "PA6-CF", "PA-CF", "ASA-CF", "ABS-GF", "PETG", "PET",
                      "PLA", "ABS", "ASA", "TPU", "PEBA", "PCTG", "PC", "PA", "PVA", "BVOH", "HIPS", "PPS"],
                     key=len, reverse=True)


def base_type(material: str) -> str:
    up = (material or "").upper().replace("_", "-")
    for t in KNOWN_TYPES:
        if t in up or t.replace("-", " ") in up:
            return t
    return (material or "").strip()


def _idx(container: Any, i: int, default=None):
    if isinstance(container, list):
        return container[i] if i < len(container) else default
    if isinstance(container, dict):
        return container.get(str(i), container.get(i, default))
    return default


def _hex6(c: Any) -> str:
    s = str(c or "").strip().lstrip("#").upper()
    return s[:6] if len(s) >= 6 and all(ch in "0123456789ABCDEF" for ch in s[:6]) else ""


def _color_distance(a: str, b: str) -> Optional[float]:
    if len(a) != 6 or len(b) != 6:
        return None
    ra, ga, ba = (int(a[i:i + 2], 16) for i in (0, 2, 4))
    rb, gb, bb = (int(b[i:i + 2], 16) for i in (0, 2, 4))
    return ((ra - rb) ** 2 + (ga - gb) ** 2 + (ba - bb) ** 2) ** 0.5


# Ab diesem RGB-Abstand gilt eine Farbe als "anders". Grosszuegig, weil Tag-Farben
# (ACE-RFID-App, Anycubic-Tags) selten exakt dem Shop-Hex entsprechen.
COLOR_TOLERANCE = 150


def ace_match(ace: Dict[str, Any], info: Dict[str, Any]) -> Dict[str, Any]:
    """Eine Regel fuer Karten-Hinweise und Spulenauswahl.

    material/color: True = passt, False = passt nicht, None = nicht pruefbar
    (Slot leer, kein Tag, keine Farbe hinterlegt). full = alles Pruefbare passt
    und mindestens das Material war pruefbar.
    """
    material = color = None
    if ace.get("present") and ace.get("material") and info.get("material"):
        material = base_type(ace["material"]).upper() == base_type(info["material"]).upper()
    if ace.get("present"):
        dist = _color_distance(ace.get("color") or "", info.get("color") or "")
        if dist is not None:
            color = dist <= COLOR_TOLERANCE
    return {"material": material, "color": color,
            "full": material is True and color is not False}


class SlotManager:
    def __init__(self, cfg: Config, moon: Moonraker, sm: Spoolman):
        self.cfg = cfg
        self.moon = moon
        self.sm = sm
        self._lock = asyncio.Lock()
        self._prev_present: Dict[int, bool] = {}      # letzter gesehener Zustand je Gate
        self._empty_since: Dict[int, float] = {}      # Gate beobachtet leer geworden seit
        self._pending_unassign: Dict[int, int] = {}   # Gate -> Spulen-ID, wartet auf Druckende
        self._lanes_written: Dict[str, Any] = {}
        self.warnings: List[str] = []

    # ------------------------------------------------------------ Zustand lesen
    @property
    def mmu(self) -> Dict[str, Any]:
        return self.moon.status.get("mmu", {}) or {}

    @property
    def print_state(self) -> str:
        return (self.moon.status.get("print_stats", {}) or {}).get("state", "") or ""

    @property
    def printing(self) -> bool:
        return self.print_state in PRINTING_STATES

    def num_gates(self) -> int:
        n = self.mmu.get("num_gates")
        try:
            return int(n) if n else 4
        except (TypeError, ValueError):
            return 4

    def ace_gate(self, gate: int) -> Dict[str, Any]:
        m = self.mmu
        status = _idx(m.get("gate_status"), gate)
        try:
            status = int(status) if status is not None else None
        except (TypeError, ValueError):
            status = None
        return {
            "status": status,
            "present": bool(self.moon.klippy_ready and status not in (None, 0)),
            "active": status == -1,
            "material": (_idx(m.get("gate_material"), gate) or "").strip(),
            "color": _hex6(_idx(m.get("gate_color"), gate)),
            "name": (_idx(m.get("gate_filament_name"), gate) or "").strip(),
            "vendor": (_idx(m.get("gate_vendor"), gate) or "").strip(),
            "temperature": _idx(m.get("gate_temperature"), gate) or None,
            "tag_id": _idx(m.get("gate_spool_id"), gate),
        }

    def assignments(self) -> Tuple[Dict[int, Dict[str, Any]], List[str]]:
        """Slot (1-basiert) -> Spule, plus Warnungen bei Doppelbelegung."""
        by_slot: Dict[int, List[Dict[str, Any]]] = {}
        for s in self.sm.spools:
            slot = self.cfg.slot_from_location(s.get("location"))
            if slot:
                by_slot.setdefault(slot, []).append(s)
        result, warnings = {}, []
        for slot, spools in by_slot.items():
            spools.sort(key=lambda s: s.get("id", 0))
            result[slot] = spools[0]
            if len(spools) > 1:
                warnings.append(f"Slot {slot} ist mehreren Spulen zugeordnet: "
                                + ", ".join(f"#{s['id']}" for s in spools) + f" - verwendet #{spools[0]['id']}")
        return result, warnings

    # ------------------------------------------------------------ Sicht fuer API/Handy
    def spool_info(self, spool: Dict[str, Any]) -> Dict[str, Any]:
        fil = spool.get("filament") or {}
        info = basic_info(fil, self.sm.templates()) if fil.get("id") else {}
        return {
            "spool_id": spool.get("id"),
            "location": spool.get("location"),
            "slot": self.cfg.slot_from_location(spool.get("location")),
            "remaining_weight": spool.get("remaining_weight"),
            "used_weight": spool.get("used_weight"),
            "initial_weight": spool.get("initial_weight") or fil.get("weight"),
            "lot_nr": spool.get("lot_nr"),
            "last_used": spool.get("last_used"),
            **info,
        }

    def slots_view(self) -> List[Dict[str, Any]]:
        assigned, _ = self.assignments()
        out = []
        for gate in range(self.num_gates()):
            slot = gate + 1
            ace = self.ace_gate(gate)
            spool = assigned.get(slot)
            info = self.spool_info(spool) if spool else None
            hints = []
            if info:
                m = ace_match(ace, info)
                if m["material"] is False:
                    hints.append(f"ACE meldet {ace['material']}, zugeordnet ist {info['material']}")
                if m["color"] is False:
                    hints.append(f"Farbe weicht ab (ACE #{ace['color']}, Spoolman #{info['color']})")
            if info and self.moon.klippy_ready and not ace["present"]:
                hints.append("ACE meldet den Slot als leer")
            if gate in self._pending_unassign:
                hints.append("wird nach Druckende ins Regal gebucht")
            out.append({"slot": slot, "gate": gate, "ace": ace, "spool": info, "hints": hints})
        return out

    def assignable_spools(self, slot: Optional[int] = None) -> List[Dict[str, Any]]:
        """Zuordenbare Spulen; mit slot zusaetzlich 'match' gegen das, was die ACE dort meldet."""
        ace = self.ace_gate(slot - 1) if slot and 1 <= slot <= self.num_gates() else None
        out = []
        for s in self.sm.spools:
            if not (s.get("filament") or {}).get("id") or self.sm.is_template(s["filament"]):
                continue
            info = self.spool_info(s)
            if ace is not None:
                info["match"] = ace_match(ace, info)
            out.append(info)
        return out

    # ------------------------------------------------------------ Zuordnen
    async def assign(self, slot: int, spool_id: Optional[int]) -> None:
        if not 1 <= slot <= self.num_gates():
            raise ValueError(f"Slot {slot} gibt es nicht")
        async with self._lock:
            if not await self.sm.refresh():
                raise RuntimeError("Spoolman nicht erreichbar")
            target_loc = self.cfg.slot_location(slot)
            if spool_id is not None:
                spool = self.sm.spool(spool_id)
                if not spool:
                    raise ValueError(f"Spule #{spool_id} nicht gefunden (archiviert?)")
                if self.sm.is_template(spool.get("filament") or {}):
                    raise ValueError("Auf Vorlagen duerfen keine Spulen liegen")
            for s in self.sm.spools:
                if s.get("location") == target_loc and s.get("id") != spool_id:
                    await self.sm.patch_spool(s["id"], {"location": self.cfg.shelf_location})
                    log.info("Slot %d: Spule #%s -> %s", slot, s["id"], self.cfg.shelf_location)
            if spool_id is not None:
                await self.sm.patch_spool(spool_id, {"location": target_loc})
                log.info("Slot %d: Spule #%s zugeordnet", slot, spool_id)
            self._pending_unassign.pop(slot - 1, None)
            await self.sm.refresh()
        await self.evaluate()

    # ------------------------------------------------------------ Kernlogik
    async def evaluate(self) -> None:
        async with self._lock:
            assigned, self.warnings = self.assignments()
            now = time.time()
            for gate in range(self.num_gates()):
                slot = gate + 1
                ace = self.ace_gate(gate)
                if self.moon.klippy_ready and "gate_status" in self.mmu:
                    await self._track_empty(gate, slot, ace["present"], assigned.get(slot), now)
            if self.cfg.write_lane_data and self.moon.connected:
                await self._write_lanes(assigned)

    async def _track_empty(self, gate: int, slot: int, present: bool, spool: Optional[Dict[str, Any]],
                           now: float) -> None:
        prev = self._prev_present.get(gate)
        self._prev_present[gate] = present
        if present:
            self._empty_since.pop(gate, None)
            if gate in self._pending_unassign:
                log.info("Slot %d wieder belegt - Rueckbuchung ins Regal verworfen", slot)
                self._pending_unassign.pop(gate, None)
            return
        if prev is True:  # gerade beobachtet leer geworden
            self._empty_since[gate] = now
        if not self.cfg.auto_unassign_on_empty or spool is None:
            return
        since = self._empty_since.get(gate)
        if since is None or now - since < self.cfg.empty_debounce_s:
            return
        if self.printing:
            if gate not in self._pending_unassign:
                log.info("Slot %d leer waehrend Druck - Spule #%s wird nach Druckende ins Regal gebucht",
                         slot, spool["id"])
            self._pending_unassign[gate] = spool["id"]
            return
        try:
            await self.sm.patch_spool(spool["id"], {"location": self.cfg.shelf_location})
            log.info("Slot %d leer - Spule #%s -> %s", slot, spool["id"], self.cfg.shelf_location)
            self._empty_since.pop(gate, None)
            self._pending_unassign.pop(gate, None)
            await self.sm.refresh()
        except Exception as e:  # noqa: BLE001
            log.warning("Rueckbuchung Slot %d fehlgeschlagen: %s", slot, e)

    def _lane_for(self, gate: int, spool: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        ace = self.ace_gate(gate)
        if spool and (spool.get("filament") or {}).get("id"):
            info = basic_info(spool["filament"], self.sm.templates())
            lane: Dict[str, Any] = {
                "lane": str(gate),
                "material": base_type(info["material"]) or info["material"],
                "color": info["color"],
                "name": info["display_name"],
                "vendor": info["vendor"],
                "filament_id": info["orca_filament_id"],
                "setting_id": info["orca_filament_id"],
                "spool_id": spool["id"],
                "source": "spoolman",
            }
            if info.get("nozzle_temp"):
                lane["nozzle_temp"] = int(info["nozzle_temp"])
            if info.get("bed_temp"):
                lane["bed_temp"] = int(info["bed_temp"])
            return lane
        if ace["present"] and ace["material"]:
            lane = {
                "lane": str(gate),
                "material": base_type(ace["material"]),
                "color": ace["color"],
                "name": ace["name"] or ace["material"],
                "source": "ace",
            }
            if ace["vendor"]:
                lane["vendor"] = ace["vendor"]
            if ace["temperature"]:
                try:
                    lane["nozzle_temp"] = int(ace["temperature"])
                except (TypeError, ValueError):
                    pass
            return lane
        return None

    async def _write_lanes(self, assigned: Dict[int, Dict[str, Any]]) -> None:
        ns = self.cfg.lane_namespace
        for gate in range(self.num_gates()):
            key = str(gate)
            lane = self._lane_for(gate, assigned.get(gate + 1))
            if key in self._lanes_written and self._lanes_written[key] == lane:
                continue
            try:
                if lane is None:
                    if self.cfg.empty_gate_mode != "delete":
                        continue
                    await self.moon.db_delete(ns, key)
                    log.info("lane_data %s entfernt (leer)", key)
                else:
                    await self.moon.db_post(ns, key, lane)
                    log.info("lane_data %s -> %s #%s %s%s", key, lane["material"], lane["color"] or "?",
                             lane.get("filament_id", ""), f" ({lane['name']})" if lane.get("name") else "")
                self._lanes_written[key] = lane
            except Exception as e:  # noqa: BLE001
                log.warning("lane_data %s schreiben fehlgeschlagen: %s", key, e)

    def reset_lane_cache(self) -> None:
        self._lanes_written.clear()

    async def on_print_state_change(self, old: str, new: str) -> None:
        if old in PRINTING_STATES and new not in PRINTING_STATES and self._pending_unassign:
            log.info("Druck beendet (%s) - fuehre aufgeschobene Rueckbuchungen aus", new)
            await self.evaluate()
