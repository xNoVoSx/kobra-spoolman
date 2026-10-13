"""Slot management: ACE state + Spoolman assignment -> slot view, auto release, lane_data.

The assignment slot <-> spool lives only in Spoolman (the spool's "location" field, e.g. "ACE Slot 1"). The bridge
keeps only a cache of it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from . import acemodel
from .config import Config
from .i18n import tr
from .moonraker import Moonraker
from .profiles import basic_info
from .spoolman import TAG_NR_FIELD, Spoolman, extra_value

log = logging.getLogger("slots")

PRINTING_STATES = ("printing", "paused")

# Orca base types, longest first (for ACE material names without a Spoolman assignment)
KNOWN_TYPES = sorted(["PETG-CF", "PET-CF", "PLA-CF", "PA6-CF", "PA-CF", "ASA-CF", "ABS-GF", "PETG", "PET",
                      "PLA", "ABS", "ASA", "TPU", "PEBA", "PCTG", "PC", "PA", "PVA", "BVOH", "HIPS", "PPS"],
                     key=len, reverse=True)


def base_type(material: str) -> str:
    up = (material or "").upper().replace("_", "-")
    for t in KNOWN_TYPES:
        if t in up or t.replace("-", " ") in up:
            return t
    return (material or "").strip()


def _hex6(c: Any) -> str:
    s = str(c or "").strip().lstrip("#").upper()
    return s[:6] if len(s) >= 6 and all(ch in "0123456789ABCDEF" for ch in s[:6]) else ""


def _color_distance(a: str, b: str) -> Optional[float]:
    if len(a) != 6 or len(b) != 6:
        return None
    ra, ga, ba = (int(a[i:i + 2], 16) for i in (0, 2, 4))
    rb, gb, bb = (int(b[i:i + 2], 16) for i in (0, 2, 4))
    return ((ra - rb) ** 2 + (ga - gb) ** 2 + (ba - bb) ** 2) ** 0.5


# from this RGB distance a colour counts as "different". Generous, because tag colours (ACE RFID app, Anycubic tags)
# rarely match the shop hex exactly.
COLOR_TOLERANCE = 150

# templates of tr() texts the bridge recognises again (tests/test_slot_hints.py checks they match the tr() calls)
UNKNOWN_TAG = "Slot {slot}: unknown tag {nr} – assign a spool, the number will be remembered"
HINT_ERROR = ("The ACE knows no material for this slot – assign the spool here again",
              "The ACE knows no material for this slot – assign a spool",
              # Rinkhals: GoKlipper cancels a print with an empty slot material ("index out of range", findings)
              "No material is set at the printer – a print with this slot gets cancelled (assign the spool here again "
              "or enter it at the display)",
              "No material is set at the printer – a print with this slot gets cancelled (enter it at the display at "
              "the slot)")
HINT_WARN = ("ACE reports {ace}, assigned is {spool}", "Colour differs (ACE #{ace}, Spoolman #{spool})",
             "ACE reports the slot as empty")


def hint_level(hint: Any) -> str:
    """error | warn | info of a slot hint (by its English template, so it works in every language)."""
    msg = getattr(hint, "msg", str(hint))
    return "error" if msg in HINT_ERROR else "warn" if msg in HINT_WARN else "info"


def is_unknown_tag_event(text: Any) -> bool:
    return getattr(text, "msg", None) == UNKNOWN_TAG


def ace_match(ace: Dict[str, Any], info: Dict[str, Any]) -> Dict[str, Any]:
    """One rule for card hints and spool selection.

    material/color: True = matches, False = does not match, None = cannot be checked (slot empty, no tag, no colour
    stored). full = everything checkable matches and at least the material was checkable.
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


def gate_has_tag(ace: Dict[str, Any]) -> bool:
    """Spool with an RFID tag: the ACE fills in material/colour itself from the tag (ACEPRO: slot field rfid; Rinkhals:
    GoKlipper's rfid flag or gate_spool_id)."""
    return bool(ace.get("rfid"))


def gate_needs_info(ace: Dict[str, Any]) -> bool:
    """The slot has filament but the ACE knows no material (no tag, nothing entered) - ACEPRO then knows no load/purge
    temperature for manual changes and Orca no type for the slot; under Rinkhals GoKlipper cancels a print with it
    ('index out of range [0] with length 0', docs/findings.md)."""
    return bool(ace.get("present")) and not ace.get("material")


def set_slot_command(gate: int, info: Dict[str, Any], status: Optional[Dict[str, Any]] = None,
                     spool_id: int = 0) -> Optional[str]:
    """Command for the slot data of a slot without a tag from the Spoolman data (acemodel.set_slot_command:
    ACE_SET_SLOT under ACEPRO, MMU_GATE_MAP under Rinkhals)."""
    material = base_type(info.get("material") or "").upper()
    try:
        temp = int(info.get("nozzle_temp") or 0)
    except (TypeError, ValueError):
        temp = 0
    return acemodel.set_slot_command(status or {}, gate, spool_id, material, _hex6(info.get("color")), temp,
                                     name=info.get("display_name") or "")


class SlotManager:
    def __init__(self, cfg: Config, moon: Moonraker, sm: Spoolman):
        self.cfg = cfg
        self.moon = moon
        self.sm = sm
        self._lock = asyncio.Lock()
        self._prev_present: Dict[int, bool] = {}      # last seen state per gate
        self._empty_since: Dict[int, float] = {}      # gate seen becoming empty since
        self._pending_unassign: Dict[int, int] = {}   # gate -> spool ID, waiting for the print to end
        self._lanes_written: Dict[str, Any] = {}
        self._gate_info_pending: Dict[int, Dict[str, int]] = {}   # gate -> {spool_id, tries}, from assign()
        self.warnings: List[str] = []
        # automatic RFID: last handled tag number per gate, waiting (number, since), unknown numbers,
        # gates whose assignment came from the tag, and events for the messages
        self._tag_seen: Dict[int, int] = {}
        self._kind_seen: Dict[int, str] = {}                 # original Anycubic tag: kind handled per insertion
        self._kind_pending: Dict[int, Tuple[str, float]] = {}
        self._tag_pending: Dict[int, Tuple[int, float]] = {}
        self._auto_lock = asyncio.Lock()
        self.unknown_tags: Dict[int, int] = {}
        self.by_tag: Dict[int, int] = {}
        self.tag_events: List[Dict[str, Any]] = []

    # ------------------------------------------------------------ reading state
    @property
    def print_state(self) -> str:
        return (self.moon.status.get("print_stats", {}) or {}).get("state", "") or ""

    @property
    def printing(self) -> bool:
        return self.print_state in PRINTING_STATES

    def num_gates(self) -> int:
        return acemodel.num_slots(self.moon.status)

    def ace_gate(self, gate: int) -> Dict[str, Any]:
        """Slot (0-based) according to the ACE driver (acemodel.slot)."""
        return acemodel.slot(self.moon.status, gate, self.moon.klippy_ready)

    @property
    def ace_connected(self) -> bool:
        return bool(self.moon.klippy_ready and acemodel.connected(self.moon.status))

    def assignments(self) -> Tuple[Dict[int, Dict[str, Any]], List[str]]:
        """Slot (1-based) -> spool, plus warnings for double assignments."""
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
                warnings.append(tr("Slot {slot} is assigned to several spools: {ids} - using #{used}", slot=slot,
                                   ids=", ".join(f"#{s['id']}" for s in spools), used=spools[0]["id"]))
        return result, warnings

    # ------------------------------------------------------------ view for API/phone
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
                    hints.append(tr("ACE reports {ace}, assigned is {spool}", ace=ace["material"], spool=info["material"]))
                if m["color"] is False:
                    hints.append(tr("Colour differs (ACE #{ace}, Spoolman #{spool})", ace=ace["color"], spool=info["color"]))
            pending = gate in self._gate_info_pending
            if pending:
                hints.append(tr("Material/colour go to the ACE as soon as the spool is inserted")
                             if not ace["present"] else tr("Material/colour go to the ACE after the print")
                             if self.printing else tr("Material/colour are being given to the ACE"))
            elif self.moon.klippy_ready and gate_needs_info(ace):
                again = info and self.cfg.set_ace_slot_info
                if acemodel.variant(self.moon.status) == acemodel.RINKHALS:
                    hints.append(tr("No material is set at the printer – a print with this slot gets cancelled (assign "
                                    "the spool here again or enter it at the display)") if again
                                 else tr("No material is set at the printer – a print with this slot gets cancelled "
                                         "(enter it at the display at the slot)"))
                else:
                    hints.append(tr("The ACE knows no material for this slot – assign the spool here again") if again
                                 else tr("The ACE knows no material for this slot – assign a spool"))
            if info and self.moon.klippy_ready and not ace["present"]:
                hints.append(tr("ACE reports the slot as empty"))
            if gate in self._pending_unassign:
                hints.append(tr("will be moved to the shelf after the print"))
            out.append({"slot": slot, "gate": gate, "ace": ace, "spool": info, "hints": hints,
                        "by_tag": self.by_tag.get(gate) is not None and info is not None})
        return out

    def assignable_spools(self, slot: Optional[int] = None) -> List[Dict[str, Any]]:
        """Assignable spools; with slot also 'match' against what the ACE reports there."""
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

    # ------------------------------------------------------------ automatic RFID
    def tag_of_gate(self, gate: int) -> Optional[int]:
        """Our tag number in the gate (>= TAG_NR_MIN), else None - smaller ones are original Anycubic kinds."""
        try:
            n = int(self.ace_gate(gate)["tag_id"] or 0)
        except (TypeError, ValueError):
            return None
        return n if n >= self.cfg.tag_nr_min else None

    def spool_by_tag(self, nr: int) -> Optional[Dict[str, Any]]:
        for s in self.sm.spools:
            try:
                if int(extra_value(s, "tag_nr") or 0) == nr:
                    return s
            except (TypeError, ValueError):
                continue
        return None

    def _event(self, text: str, now: float) -> None:
        self.tag_events = [e for e in self.tag_events if now - e["at"] < 1800][-9:] + [{"at": now, "text": text}]
        log.info(text)

    async def auto_by_tag(self, now: Optional[float] = None) -> None:
        """Spool with our tag in the slot -> assign automatically. Reacts when the number in the gate changes (also at
        start: then every number is new) - a deliberate manual assignment is not overwritten all the time."""
        if not (self.cfg.auto_assign_by_tag or self.cfg.auto_assign_by_kind) or not self.ace_connected:
            return
        # only with the spool list from Spoolman - otherwise every number would be "unknown" at start
        if not getattr(self.sm, "connected", True) or not self.sm.spools:
            return
        if self._auto_lock.locked():
            return
        async with self._auto_lock:
            now = time.time() if now is None else now
            for gate in range(self.num_gates()):
                slot = gate + 1
                ace = self.ace_gate(gate)
                nr = self.tag_of_gate(gate) if ace["present"] and self.cfg.auto_assign_by_tag else None
                if nr is None:
                    self._tag_pending.pop(gate, None)
                    self.unknown_tags.pop(gate, None)
                    if not ace["present"]:
                        self._tag_seen.pop(gate, None)     # inserted again = new
                        self.by_tag.pop(gate, None)
                    await self._auto_by_kind(gate, ace, now)
                    continue
                if self._tag_seen.get(gate) == nr:
                    # unknown number: look again every time (a spool may have the number by now)
                    if gate not in self.unknown_tags or self.spool_by_tag(nr) is None:
                        continue
                    self._tag_seen.pop(gate, None)
                    self._tag_pending[gate] = (nr, now - self.cfg.gate_debounce_s)   # already debounced
                pending = self._tag_pending.get(gate)
                if pending is None or pending[0] != nr:
                    self._tag_pending[gate] = (nr, now)          # loading flickers: only after debouncing
                    continue
                if now - pending[1] < self.cfg.gate_debounce_s:
                    continue
                self._tag_pending.pop(gate, None)
                self._tag_seen[gate] = nr
                spool = self.spool_by_tag(nr)
                if spool is None:
                    self.unknown_tags[gate] = nr
                    self._event(tr("Slot {slot}: unknown tag {nr} – assign a spool, the number will be remembered",
                                   slot=slot, nr=nr), now)
                    continue
                self.unknown_tags.pop(gate, None)
                assigned, _ = self.assignments()
                current = assigned.get(slot)
                self.by_tag[gate] = nr
                if current and current.get("id") == spool["id"]:
                    continue
                name = ((spool.get("filament") or {}).get("name") or f"#{spool['id']}")
                try:
                    await self.assign(slot, spool["id"], learn=False)
                    self._event(tr("Slot {slot}: {name} recognised by RFID (tag {nr})", slot=slot, name=name, nr=nr), now)
                except Exception as e:  # noqa: BLE001
                    self._tag_seen.pop(gate, None)           # the next run tries again
                    log.warning("Slot %d: RFID assignment failed: %s", slot, e)

    def spools_of_kind(self, ace: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Spools on the shelf (in no slot) that fit an original Anycubic tag: same material, colour within the
        tolerance and - when both are known - the same vendor."""
        vendor = (ace.get("vendor") or "").strip().lower()
        out = []
        for s in self.sm.spools:
            fil = s.get("filament") or {}
            if not fil.get("id") or self.sm.is_template(fil) or self.cfg.slot_from_location(s.get("location")):
                continue
            info = self.spool_info(s)
            m = ace_match(ace, info)
            v = (info.get("vendor") or "").strip().lower()
            if m["material"] is True and m["color"] is True and not (vendor and v and v != vendor):
                out.append(s)
        return out

    async def _auto_by_kind(self, gate: int, ace: Dict[str, Any], now: float) -> None:
        """Original Anycubic tag (no number of ours): it only names the kind (SKU, material, colour), not the spool. If
        exactly one spool on the shelf fits, it is the one - assign it once per insertion; several or none: a note,
        the choice stays with the user. Switch: AUTO_ASSIGN_BY_KIND."""
        own = self.tag_of_gate(gate) is not None              # our tags: auto_by_tag, also when that is off
        if not ace["present"] or not gate_has_tag(ace) or own or not self.cfg.auto_assign_by_kind:
            self._kind_pending.pop(gate, None)
            if not ace["present"]:
                self._kind_seen.pop(gate, None)
            return
        kind = f"{ace.get('sku') or ace.get('tag_id') or ''}|{ace['material']}|{ace['color']}"
        if self._kind_seen.get(gate) == kind:
            return
        pending = self._kind_pending.get(gate)
        if pending is None or pending[0] != kind:
            self._kind_pending[gate] = (kind, now)          # the tag is read while loading: only after debouncing
            return
        if now - pending[1] < self.cfg.gate_debounce_s:
            return
        self._kind_pending.pop(gate, None)
        self._kind_seen[gate] = kind
        slot = gate + 1
        assigned, _ = self.assignments()
        current = assigned.get(slot)
        if current and ace_match(ace, self.spool_info(current))["full"]:
            return                                           # already a fitting spool in the slot
        found = self.spools_of_kind(ace)
        what = f"{ace['material']} #{ace['color']}"
        if len(found) != 1:
            self._event(tr("Slot {slot}: Anycubic tag {what} – {n} spools on the shelf fit, please assign one",
                           slot=slot, what=what, n=len(found)), now)
            return
        spool = found[0]
        name = (spool.get("filament") or {}).get("name") or f"#{spool['id']}"
        try:
            await self.assign(slot, spool["id"], learn=False)
            self._event(tr("Slot {slot}: {name} recognised by the Anycubic tag (the only fitting spool)",
                           slot=slot, name=name), now)
        except Exception as e:  # noqa: BLE001
            self._kind_seen.pop(gate, None)
            log.warning("Slot %d: assignment by Anycubic tag failed: %s", slot, e)

    async def _learn_tag(self, slot: int, spool_id: int) -> None:
        """Manual assignment into a slot with an unknown tag: remember the number on the spool (if it has none yet)."""
        gate = slot - 1
        nr = self.tag_of_gate(gate)
        if nr is None or self.spool_by_tag(nr) is not None:
            return
        spool = self.sm.spool(spool_id) or {}
        if extra_value(spool, "tag_nr"):
            return
        await self.sm.ensure_field("spool", "tag_nr", TAG_NR_FIELD)
        await self.sm.patch_spool(spool_id, {"extra": {"tag_nr": str(nr)}})
        self.unknown_tags.pop(gate, None)
        self._tag_seen[gate] = nr
        self.by_tag[gate] = nr
        self._event(tr("Slot {slot}: tag {nr} remembered on spool #{id}", slot=slot, nr=nr, id=spool_id), time.time())

    # ------------------------------------------------------------ assigning
    async def assign(self, slot: int, spool_id: Optional[int], learn: bool = True) -> None:
        if not 1 <= slot <= self.num_gates():
            raise ValueError(tr("There is no slot {slot}", slot=slot))
        async with self._lock:
            if not await self.sm.refresh():
                raise RuntimeError(tr("Spoolman not reachable"))
            target_loc = self.cfg.slot_location(slot)
            if spool_id is not None:
                spool = self.sm.spool(spool_id)
                if not spool:
                    raise ValueError(tr("Spool #{id} not found (archived?)", id=spool_id))
                if self.sm.is_template(spool.get("filament") or {}):
                    raise ValueError(tr("Templates must not hold spools"))
            for s in self.sm.spools:
                if s.get("location") == target_loc and s.get("id") != spool_id:
                    await self.sm.patch_spool(s["id"], {"location": self.cfg.shelf_location})
                    log.info("Slot %d: spool #%s -> %s", slot, s["id"], self.cfg.shelf_location)
            if spool_id is not None:
                await self.sm.patch_spool(spool_id, {"location": target_loc})
                log.info("Slot %d: spool #%s assigned", slot, spool_id)
            self._pending_unassign.pop(slot - 1, None)
            # only assigning here writes material/colour to the ACE - never a restart, an input on the display or a
            # change in Spoolman.
            self._gate_info_pending.pop(slot - 1, None)
            if spool_id is not None and self.cfg.set_ace_slot_info:
                self._gate_info_pending[slot - 1] = {"spool_id": spool_id, "tries": 0}
            if spool_id is None or (learn and self.by_tag.get(slot - 1) is not None):
                self.by_tag.pop(slot - 1, None)          # manual assignment: drop the "by RFID" mark
            if learn and spool_id is not None and self.cfg.auto_assign_by_tag:
                try:
                    await self._learn_tag(slot, spool_id)
                except Exception as e:  # noqa: BLE001
                    log.warning("Remembering the tag number failed: %s", e)
            await self.sm.refresh()
        await self.evaluate()

    # ------------------------------------------------------------ core logic
    async def evaluate(self) -> None:
        await self.auto_by_tag()
        async with self._lock:
            assigned, self.warnings = self.assignments()
            now = time.time()
            gates = range(self.num_gates())
            present = {gate: self.ace_gate(gate)["present"] for gate in gates}
            # every slot empty at once: the ACE was switched off or lost (13.10.: Rinkhals reported all four slots empty
            # when the ACE was power-cycled and the bridge moved all spools to the shelf) - nobody took four spools
            # out in the same second, so nothing is moved; a slot emptied by hand still counts as before
            ace_gone = not any(present.values())
            for gate in gates:
                if self.ace_connected and not ace_gone:
                    await self._track_empty(gate, gate + 1, present[gate], assigned.get(gate + 1), now)
                elif ace_gone:
                    self._empty_since.pop(gate, None)
            # without Spoolman data (bridge start, Spoolman gone) overwrite nothing - otherwise the slots would briefly
            # stand without a profile (filament_id) and Orca's sync button would pick wrong
            if self.cfg.write_lane_data and self.moon.connected and getattr(self.sm, "connected", True):
                await self._write_lanes(assigned)
            if self._gate_info_pending and self.moon.klippy_ready and not self.printing:
                await self._push_gate_info(assigned)

    async def _track_empty(self, gate: int, slot: int, present: bool, spool: Optional[Dict[str, Any]],
                           now: float) -> None:
        prev = self._prev_present.get(gate)
        self._prev_present[gate] = present
        if present:
            self._empty_since.pop(gate, None)
            if gate in self._pending_unassign:
                log.info("Slot %d loaded again - move to the shelf dropped", slot)
                self._pending_unassign.pop(gate, None)
            return
        if prev is True:  # just seen becoming empty
            self._empty_since[gate] = now
        if not self.cfg.auto_unassign_on_empty or spool is None:
            return
        since = self._empty_since.get(gate)
        if since is None or now - since < self.cfg.empty_debounce_s:
            return
        if self.printing:
            if gate not in self._pending_unassign:
                log.info("Slot %d empty during a print - spool #%s goes to the shelf after the print",
                         slot, spool["id"])
            self._pending_unassign[gate] = spool["id"]
            return
        try:
            await self.sm.patch_spool(spool["id"], {"location": self.cfg.shelf_location})
            log.info("Slot %d empty - spool #%s -> %s", slot, spool["id"], self.cfg.shelf_location)
            self._empty_since.pop(gate, None)
            self._pending_unassign.pop(gate, None)
            await self.sm.refresh()
        except Exception as e:  # noqa: BLE001
            log.warning("Moving slot %d to the shelf failed: %s", slot, e)

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
        if not self._lanes_written:
            await self._drop_foreign_lanes(ns)
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
                    log.info("lane_data %s removed (empty)", key)
                else:
                    await self.moon.db_post(ns, key, lane)
                    log.info("lane_data %s -> %s #%s %s%s", key, lane["material"], lane["color"] or "?",
                             lane.get("filament_id", ""), f" ({lane['name']})" if lane.get("name") else "")
                self._lanes_written[key] = lane
            except Exception as e:  # noqa: BLE001
                log.warning("Writing lane_data %s failed: %s", key, e)

    async def _push_gate_info(self, assigned: Dict[int, Dict[str, Any]]) -> None:
        """Give material/colour/temperature of a spool assigned in the web UI or app to the ACE (ACE_SET_SLOT).
        Waits until the spool is inserted and no print is running; once per assignment. Slots with an RFID tag and
        slots for which the ACE already reports exactly these values stay untouched."""
        for gate, job in list(self._gate_info_pending.items()):
            spool = assigned.get(gate + 1)
            if not spool or spool.get("id") != job["spool_id"] or not (spool.get("filament") or {}).get("id"):
                self._gate_info_pending.pop(gate, None)      # assigned differently by now
                continue
            ace = self.ace_gate(gate)
            if not ace["present"]:
                continue                                     # spool not inserted yet
            if gate_has_tag(ace):
                # the tag defines the slot - never overwrite
                self._gate_info_pending.pop(gate, None)
                log.info("Slot %d: spool with RFID tag (%s) - material/colour come from the tag", gate + 1, ace["sku"] or ace["tag_id"])
                continue
            info = basic_info(spool["filament"], self.sm.templates())
            cmd = set_slot_command(gate, info, self.moon.status, spool["id"])
            same = (base_type(ace["material"]).upper() == base_type(info.get("material") or "").upper()
                    and ace["color"] == _hex6(info.get("color")))
            if not cmd or same:
                self._gate_info_pending.pop(gate, None)
                continue
            try:
                await self.moon.gcode(cmd, source=tr("Slot assignment"))
                self._gate_info_pending.pop(gate, None)
                log.info("Slot %d: material/colour given to the ACE (%s)", gate + 1, cmd)
            except Exception as e:  # noqa: BLE001
                job["tries"] += 1
                if job["tries"] >= 3:
                    self._gate_info_pending.pop(gate, None)
                    log.warning("Slot %d: slot data given up: %s", gate + 1, e)
                else:
                    log.warning("Slot %d: slot data failed (%s), retrying", gate + 1, e)

    async def _drop_foreign_lanes(self, ns: str) -> None:
        """After every full sync: remove entries that do not come from the bridge (e.g. ACEPRO's lane1..lane4 from before
        moonraker_lane_sync_enabled: False) - otherwise Orca sees every slot twice, partly without filament_id, and
        the sync button picks the wrong profile."""
        own = {str(g) for g in range(self.num_gates())}
        try:
            for key in await self.moon.db_keys(ns):
                if key not in own:
                    await self.moon.db_delete(ns, key)
                    log.info("lane_data %s removed (not from the bridge)", key)
        except Exception as e:  # noqa: BLE001
            log.warning("Cleaning up lane_data failed: %s", e)

    def reset_lane_cache(self) -> None:
        self._lanes_written.clear()

    async def on_print_state_change(self, old: str, new: str) -> None:
        if old in PRINTING_STATES and new not in PRINTING_STATES and self._pending_unassign:
            log.info("Print ended (%s) - doing the postponed moves to the shelf", new)
            await self.evaluate()
