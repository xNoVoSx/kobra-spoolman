"""Consumption measuring and booking per slot.

Basis: print_stats.filament_used (Klipper/GoKlipper, mm) counts every extruder move in a print - also loading and
purging of the ACE: under ACEPRO they run through the nozzle (with ACEPRO patch 0003 at once, not only after the
change), under Rinkhals the firmware's purge is in the counter as well (real print 24.09.2026, within 1 mm). So:

- consumption = signed difference of filament_used. Retractions cancel out.
- every difference belongs to the slot that is consuming according to the ACE driver (acemodel.consuming_slot):
  the loaded slot, during a change after unloading the target slot. Moments without such a slot count for the last
  active slot.
- GoKlipper flickers while loading: there a new slot only counts after GATE_DEBOUNCE_S (acemodel.flickers).
- consumption before the first active slot goes to the first slot that becomes active.
- it is booked to the spool that was in the slot at the time of consumption ("bucket" = slot + spool). Booking at a
  slot change, at print end and in between every BOOK_INTERVAL_S.
- consumption without an assigned spool, or on a spool deleted meanwhile, becomes an open item and can be booked
  later in the web UI.
- everything is in data/usage/state.json; if the bridge restarts in the middle of a print, it continues at the
  saved counter.
- direct feed (direct.py, Klipper kobra_direct): the ACE is passed by - consumption goes to the tool the print uses
  (kobra_direct.tool, so the comparison with the G-code still fits) and is booked on the direct spool, not on the
  spool in that slot. The bucket is marked "direct".
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import time
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from . import acemodel
from .config import Config
from .purge import change_mm
from .i18n import tr
from .storage import save_json, save_lines

if TYPE_CHECKING:
    from .direct import DirectFeed
    from .purge import PurgeModel
    from .moonraker import Moonraker
    from .slots import SlotManager
    from .spoolman import Spoolman

log = logging.getLogger("usage")

PRINTING_STATES = ("printing", "paused")
SAVE_INTERVAL_S = 5.0
RETRY_BACKOFF_S = 30


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def targets_from_gcode(e_total: Dict[int, float]) -> Optional[Dict[str, Any]]:
    """Expected values per slot from the print file (render.py counts the extrusion per tool; T<n> = slot n+1).
    The ACE's purging is not in the G-code - so at least the expected value is always measured."""
    per_gate = {str(t): {"mm": round(mm, 1), "g": None} for t, mm in sorted(e_total.items()) if mm > 1}
    return {"source": "gcode", "per_gate": per_gate} if per_gate else None


# purge length Orca's change-filament G-code sets before every T (ACE_SET_PURGE_AMOUNT -> ACEPRO's answer)
PURGE_RX = re.compile(r"ACE: Purge settings updated - Length: ([0-9.]+)mm")
PURGE_LOG_KEEP = 2000          # lines in the purge log (across all prints)


def group_transitions(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge equal changes (from, to, colours): [{..., "count": n}]."""
    out: Dict[tuple, Dict[str, Any]] = {}
    for t in items:
        key = (t.get("from_slot"), t.get("to_slot"), t.get("from_color"), t.get("to_color"))
        if key in out:
            out[key]["count"] += 1
        else:
            out[key] = {**t, "count": 1}
    return list(out.values())


class UsageTracker:
    def __init__(self, cfg: Config, moon: "Moonraker", sm: "Spoolman", slots: "SlotManager"):
        self.cfg = cfg
        self.moon = moon
        self.sm = sm
        self.slots = slots
        self.dir = os.path.join(cfg.data_dir, "usage")
        os.makedirs(self.dir, exist_ok=True)
        self.state_path = os.path.join(self.dir, "state.json")
        self.history_path = os.path.join(self.dir, "jobs.json")
        self.journal_path = os.path.join(self.dir, "journal.jsonl")
        self.purge_path = os.path.join(self.dir, "purge.jsonl")   # every colour change with its purge length (to learn purge values)
        self._purge_set: Optional[float] = None                     # purge amount set last by Orca (mm)
        self._lock = asyncio.Lock()
        self._dirty = False
        self._last_save = 0.0
        self._backoff_until = 0.0
        self.job: Optional[Dict[str, Any]] = None
        self.open: List[Dict[str, Any]] = []
        self.history: List[Dict[str, Any]] = []
        self.purge: Optional["PurgeModel"] = None    # set by the bridge (purge model of the firmware, Rinkhals)
        self.direct: Optional["DirectFeed"] = None   # set by the bridge (direct feed, direct.py)
        self._load()

    # ================================================================== Persistenz
    def _load(self) -> None:
        try:
            with open(self.state_path, encoding="utf-8") as fh:
                st = json.load(fh)
            self.job = st.get("job")
            self.open = st.get("open") or []
        except FileNotFoundError:
            pass
        except Exception as e:  # noqa: BLE001
            log.error("usage/state.json unreadable (%s) - starting empty, the file stays as .broken", e)
            try:
                os.replace(self.state_path, self.state_path + ".broken")
            except OSError:
                pass
        try:
            with open(self.history_path, encoding="utf-8") as fh:
                self.history = json.load(fh)
        except FileNotFoundError:
            pass
        except Exception as e:  # noqa: BLE001
            log.warning("usage/jobs.json unreadable: %s", e)
        if self.job:
            log.info("Open print from the last run found: %s (counter %.1f mm)",
                     self.job.get("file"), self.job.get("last_used") or 0)

    # ================================================================== purge log (learning purge values, part 1)
    def on_console(self, entry: Dict[str, Any]) -> None:
        """Console listener: remembers the purge length Orca sets before the next change."""
        m = PURGE_RX.search(entry.get("text") or "")
        if m:
            self._purge_set = float(m.group(1))

    def _purge_of_change(self, src: Dict[str, Any], dst: Dict[str, Any]) -> Tuple[Optional[float], str]:
        """Purge length of a colour change and where it comes from: "orca" (the change G-code set it, ACEPRO),
        "firmware" (Rinkhals purges by itself - the firmware's formula, purge.py) or "other" (nothing set: the load
        of the print start, endless spool, a change by hand)."""
        if self._purge_set is not None:
            return self._purge_set, "orca"
        if acemodel.variant(self.moon.status) == acemodel.RINKHALS:
            mm = change_mm(src.get("color"), dst.get("color"), self.purge.flush, 0.0) if self.purge else None
            return (round(mm, 1) if mm is not None else None), "firmware"
        return None, "other"

    def _log_purge(self, rec: Dict[str, Any]) -> None:
        try:
            with open(self.purge_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if os.path.getsize(self.purge_path) > PURGE_LOG_KEEP * 400:     # rough: trim when too long
                with open(self.purge_path, encoding="utf-8") as fh:
                    lines = fh.readlines()[-PURGE_LOG_KEEP:]
                save_lines(self.purge_path, lines)
        except OSError as e:
            log.warning("Purge log: %s", e)

    def purge_pairs(self) -> List[Dict[str, Any]]:
        """Purge log per colour pair (colour + material before/after): count, purge lengths, last."""
        pairs: Dict[tuple, Dict[str, Any]] = {}
        try:
            with open(self.purge_path, encoding="utf-8") as fh:
                rows = [json.loads(line) for line in fh if line.strip()]
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as e:
            log.warning("Reading the purge log: %s", e)
            return []
        for r in rows:
            key = (r.get("from_color"), r.get("from_material"), r.get("to_color"), r.get("to_material"))
            p = pairs.setdefault(key, {"from_color": key[0], "from_material": key[1], "to_color": key[2],
                                       "to_material": key[3], "count": 0, "purge_mm": [], "last_at": None,
                                       "last_file": None, "sources": {}})
            p["count"] += 1
            # entries from before 3.18.2 carry no source: a length could only come from Orca
            source = r.get("purge_source") or ("orca" if r.get("purge_mm") is not None else "unknown")
            p["sources"][source] = p["sources"].get(source, 0) + 1
            if r.get("purge_mm") is not None:
                p["purge_mm"] = (p["purge_mm"] + [r["purge_mm"]])[-10:]
            p["last_at"], p["last_file"] = r.get("at"), r.get("file")
        return sorted(pairs.values(), key=lambda p: (-p["count"], p["last_at"] or ""))

    def save(self, force: bool = False) -> None:
        if not (self._dirty or force):
            return
        now = time.time()
        if not force and now - self._last_save < SAVE_INTERVAL_S:
            return
        try:
            save_json(self.state_path, {"job": self.job, "open": self.open}, indent=1)
            self._dirty = False
            self._last_save = now
        except OSError as e:
            log.error("Saving the state failed: %s", e)

    def _journal(self, event: str, **data: Any) -> None:
        try:
            if os.path.exists(self.journal_path) and os.path.getsize(self.journal_path) > 5_000_000:
                os.replace(self.journal_path, self.journal_path + ".1")
            with open(self.journal_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": _now_iso(), "event": event, **data}, ensure_ascii=False) + "\n")
        except OSError as e:
            log.error("Writing the journal failed: %s", e)

    # ================================================================== helpers
    @property
    def _direct_on(self) -> bool:
        return self.direct is not None and self.direct.active

    def _seen(self, status: Dict[str, Dict[str, Any]]) -> Optional[int]:
        """Consuming slot (0-based): the ACE driver's - in direct feed the tool the print uses."""
        if self._direct_on:
            return self.direct.tool
        return acemodel.consuming_slot(status)

    def _spool_for_gate(self, gate: int) -> Optional[int]:
        if self._direct_on:
            return self.direct.spool_id
        assigned, _ = self.slots.assignments()
        spool = assigned.get(gate + 1)
        return spool.get("id") if spool else None

    def _geometry(self, spool_id: Optional[int]) -> Tuple[float, float]:
        """(diameter mm, density g/cm3) of the spool, else default values."""
        fil = ((self.sm.spool(spool_id) or {}).get("filament") or {}) if spool_id else {}
        d = fil.get("diameter") or self.cfg.default_diameter
        rho = fil.get("density") or self.cfg.default_density
        return float(d), float(rho)

    def grams(self, mm: float, spool_id: Optional[int]) -> float:
        d, rho = self._geometry(spool_id)
        return mm * math.pi * (d / 2) ** 2 * rho / 1000.0

    def _spool_label(self, spool_id: Optional[int]) -> Optional[str]:
        if not spool_id:
            return None
        s = self.sm.spool(spool_id)
        if not s:
            return f"#{spool_id}"
        fil = s.get("filament") or {}
        vendor = (fil.get("vendor") or {}).get("name") or ""
        return f"#{spool_id} {vendor} {fil.get('name') or ''}".strip()

    def _ace_info(self, gate: int) -> Dict[str, Any]:
        if self._direct_on:
            fil = (self.direct.spool() or {}).get("filament") or {}
            return {"material": fil.get("material"), "color": fil.get("color_hex"), "name": self.direct.label(),
                    "direct": True}
        a = self.slots.ace_gate(gate)
        return {"material": a.get("material"), "color": a.get("color"), "name": a.get("name")}

    # ================================================================== Job-Lebenszyklus
    def _new_job(self, status: Dict[str, Dict[str, Any]]) -> None:
        ps = status.get("print_stats", {}) or {}
        used = ps.get("filament_used")
        self.job = {
            "id": time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4],
            "file": ps.get("filename") or "",
            "started": _now_iso(),
            "used_start": used if isinstance(used, (int, float)) else 0.0,
            "last_used": used if isinstance(used, (int, float)) else 0.0,
            "gate": None,              # slot the consumption currently belongs to (0-based)
            "pending_gate": None,      # new slot still in the debounce time (GoKlipper)
            "pending_since": None,
            "pending_mm": 0.0,
            "pre_mm": 0.0,             # consumption before the first active slot
            "buckets": {},             # "gate:spool" -> {gate, spool_id, mm, booked_mm, last_book}
            "loads": 0,                # how often a slot became active (first + changes)
            "changes": [],             # slot changes
            "transitions": [],         # every load with ACE colours (colour change statistics)
            "targets": None,           # arrives as soon as the bridge has read the print file (set_targets)
            # Rinkhals: the firmware's flush setting and the slicer, for calibrating the purge model (purge.py)
            "slicer": (status.get("virtual_sdcard", {}) or {}).get("slicer"),
            "flush": dict(self.purge.flush) if self.purge and self.purge.flush_source == "printer" else None,
        }
        self._dirty = True
        self._journal("job_start", job=self.job["id"], file=self.job["file"], used_start=self.job["used_start"])
        log.info("Print started: %s (counter %.1f mm)", self.job["file"], self.job["used_start"])
        seen = acemodel.consuming_slot(status)
        if seen is not None:
            self._confirm_gate(seen)

    def set_targets(self, file: str, e_total: Dict[int, float]) -> None:
        """The bridge has read the print file (render.py): expected values per slot for the check at print end."""
        if not self.job or self.job["file"] != file or self.job.get("targets"):
            return
        self.job["targets"] = targets_from_gcode(e_total)
        self._dirty = True
        self._journal("job_targets", job=self.job["id"], targets=self.job["targets"])

    def _bucket(self, gate: int) -> Dict[str, Any]:
        assert self.job is not None
        spool_id = self._spool_for_gate(gate)
        direct = self._direct_on
        key = f"{gate}:{spool_id or '-'}" + (":direct" if direct else "")
        b = self.job["buckets"].get(key)
        if b is None:
            b = {"gate": gate, "spool_id": spool_id, "mm": 0.0, "booked_mm": 0.0, "last_book": 0.0,
                 "ace": self._ace_info(gate), "direct": direct}
            self.job["buckets"][key] = b
        return b

    def _add(self, gate: int, mm: float) -> None:
        if mm:
            self._bucket(gate)["mm"] += mm
            self._dirty = True

    def _confirm_gate(self, gate: int) -> None:
        """gate is the active slot from now on."""
        job = self.job
        assert job is not None
        old = job["gate"]
        if old == gate:
            return
        job["gate"] = gate
        job["loads"] += 1
        src = self.slots.ace_gate(old) if old is not None else {}
        dst = self.slots.ace_gate(gate)
        # purge length only for a real change (the first load at print start purges by G9111, not by Orca)
        purge, source = self._purge_of_change(src, dst) if old is not None else (None, None)
        self._purge_set = None
        job.setdefault("transitions", []).append({
            "from_slot": old + 1 if old is not None else None, "to_slot": gate + 1,
            "from_color": src.get("color") if old is not None else None,
            "to_color": dst.get("color"), "purge_mm": purge, "purge_source": source})
        if old is not None:
            self._log_purge({"at": _now_iso(), "file": job.get("file"), "from_slot": old + 1, "to_slot": gate + 1,
                             "from_color": src.get("color"), "to_color": dst.get("color"),
                             "from_material": src.get("material"), "to_material": dst.get("material"),
                             "purge_mm": purge, "purge_source": source})
        if job["pre_mm"]:
            self._add(gate, job["pre_mm"])
            job["pre_mm"] = 0.0
        if old is not None:
            job["changes"].append({"ts": _now_iso(), "from": old, "to": gate, "used": job["last_used"]})
            log.info("Slot change %d -> %d at %.1f mm", old + 1, gate + 1, job["last_used"])
            self._book_due_gate = old  # after the change, book the old slot
        else:
            log.info("Slot %d active", gate + 1)
        self._dirty = True

    _book_due_gate: Optional[int] = None

    def _observe_gate(self, seen: Optional[int], now: float, debounce: bool = False) -> None:
        """New consuming slot of the ACE driver. ACEPRO reports it without flicker - taken over at once. GoKlipper
        (Rinkhals) flickers while loading: a new slot only counts once it stays GATE_DEBOUNCE_S; what is used in that
        time goes to the slot that wins in the end."""
        job = self.job
        assert job is not None
        if not debounce:
            if seen is None or seen == job["gate"]:
                return  # no slot: consumption keeps going to the previous one
            self._settle(now, force=True)
            self._confirm_gate(seen)
            return
        if seen is None:
            return  # no active slot: nothing changes, consumption goes to the previous/pending one
        if job["gate"] is None:
            self._confirm_gate(seen)
            return
        if seen == job["gate"]:
            if job["pending_gate"] is not None:
                # flicker: the pending slot did not win
                self._add(job["gate"], job["pending_mm"])
                log.debug("Flicker on slot %s discarded", job["pending_gate"] + 1)
                job["pending_gate"], job["pending_since"], job["pending_mm"] = None, None, 0.0
            return
        if job["pending_gate"] != seen:
            if job["pending_gate"] is not None:
                self._add(job["gate"], job["pending_mm"])
            job["pending_gate"], job["pending_since"], job["pending_mm"] = seen, now, 0.0
            self._dirty = True

    def _settle(self, now: float, force: bool = False) -> None:
        """Confirm the pending slot once it stayed long enough (debouncing for GoKlipper)."""
        job = self.job
        if not job or job["pending_gate"] is None:
            return
        if force or now - (job["pending_since"] or now) >= self.cfg.gate_debounce_s:
            gate, mm = job["pending_gate"], job["pending_mm"]
            job["pending_gate"], job["pending_since"], job["pending_mm"] = None, None, 0.0
            self._confirm_gate(gate)
            self._add(gate, mm)

    def _consume(self, used: float) -> None:
        job = self.job
        assert job is not None
        last = job["last_used"]
        job["last_used"] = used
        if not isinstance(last, (int, float)):
            return
        d = used - last
        if d == 0:
            return
        if job["pending_gate"] is not None:
            job["pending_mm"] += d
        elif job["gate"] is not None:
            self._add(job["gate"], d)
        else:
            job["pre_mm"] += d
        self._dirty = True

    # ================================================================== input
    async def on_status(self, delta: Dict[str, Any], full: bool, status: Dict[str, Dict[str, Any]]) -> None:
        async with self._lock:
            ps = status.get("print_stats", {}) or {}
            state = ps.get("state") or ""
            now = time.monotonic()

            if full:
                await self._on_snapshot(status)
                return

            if self.job is None:
                if state in PRINTING_STATES:
                    self._new_job(status)
                return

            ps_d = delta.get("print_stats") or {}
            # new print although the old one never ended cleanly (counter reset, other file)
            if "filename" in ps_d and ps_d["filename"] and ps_d["filename"] != self.job["file"] \
                    and state in PRINTING_STATES:
                log.warning("New print without an end of the old one - closing %s", self.job["file"])
                await self._finish("cancelled_unnoticed")
                self._new_job(status)
                return

            # order: first give the consumption to the slot known so far, then update the slot
            if "filament_used" in ps_d and isinstance(ps_d["filament_used"], (int, float)):
                self._consume(ps_d["filament_used"])
            if acemodel.touches(delta) or "kobra_direct" in delta or self._direct_on:
                self._observe_gate(self._seen(status), now, acemodel.flickers(status) and not self._direct_on)
            self._settle(now)

            if state not in PRINTING_STATES:
                await self._finish(state or "ended")
            else:
                await self._book(now, reason="tick")
            self.save()

    async def _on_snapshot(self, status: Dict[str, Dict[str, Any]]) -> None:
        """First status after a start or reconnect."""
        ps = status.get("print_stats", {}) or {}
        state = ps.get("state") or ""
        used = ps.get("filament_used")
        printing = state in PRINTING_STATES
        if self.job is None:
            if printing:
                self._new_job(status)
            return
        same_file = (ps.get("filename") or "") == self.job["file"]
        plausible = isinstance(used, (int, float)) and used >= (self.job["last_used"] or 0) - 100
        if same_file and plausible:
            gap = used - (self.job["last_used"] or 0)
            if abs(gap) > 0.05:
                log.info("Continuing print %s: %.1f mm since the last saved state",
                         self.job["file"], gap)
                self._journal("resume", job=self.job["id"], gap_mm=round(gap, 1))
            self._consume(used)
            self._observe_gate(self._seen(status), time.monotonic(),
                               acemodel.flickers(status) and not self._direct_on)
            if not printing:
                await self._finish(state or "ended")
        else:
            log.warning("Saved print %s does not match the printer (%s, %s) - closing with the last state",
                        self.job["file"], ps.get("filename"), state)
            await self._finish("interrupted")
            if printing:
                self._new_job(status)
        self.save(force=True)

    async def tick(self) -> None:
        """Regularly: debouncing without new updates, interim booking, retries."""
        async with self._lock:
            now = time.monotonic()
            if self.job:
                self._settle(now)
                await self._book(now, reason="tick")
            await self._retry_open()
            self.save()

    # ================================================================== booking
    async def _use(self, spool_id: int, mm: float) -> str:
        """Books mm onto a spool. Returns: 'ok', 'missing' (spool gone) or 'error'."""
        if time.monotonic() < self._backoff_until:
            return "error"  # Spoolman was just unreachable - do not retry on every tick
        if not self.cfg.book_usage or self.cfg.dry_run:
            log.info("[%s] %.1f mm on spool #%s", "dry-run" if self.cfg.dry_run else "booking off",
                     mm, spool_id)
            return "ok"
        try:
            await self.sm.use_length(spool_id, mm)
            return "ok"
        except LookupError:
            return "missing"
        except Exception as e:  # noqa: BLE001
            log.warning("Booking on spool #%s failed (%s) - retrying in %d s",
                        spool_id, e, RETRY_BACKOFF_S)
            self._backoff_until = time.monotonic() + RETRY_BACKOFF_S
            return "error"

    async def _book(self, now: float, reason: str, final: bool = False) -> None:
        job = self.job
        if not job:
            return
        due_gate = self._book_due_gate
        self._book_due_gate = None
        for b in list(job["buckets"].values()):
            spool_id = b.get("spool_id")
            todo = b["mm"] - b["booked_mm"]
            if spool_id is None:
                continue
            if final or b["gate"] == due_gate:
                # GoKlipper retracts and cuts at every unload (-53 mm, mostly counted back before the next slot):
                # a correction may only take back what this print booked on the spool, never more
                todo = max(todo, -b["booked_mm"])
            elif todo < self.cfg.book_min_mm or now - b.get("last_book", 0) < self.cfg.book_interval_s:
                continue  # interim bookings only forward - a retract in progress waits for the change or the end
            if abs(todo) < 0.05:
                continue
            res = await self._use(spool_id, todo)
            if res == "ok":
                b["booked_mm"] += todo
                b["last_book"] = now
                self._dirty = True
                self.save(force=True)  # save at once, otherwise a crash could book twice
                self._journal("book", job=job["id"], slot=b["gate"] + 1, spool=spool_id,
                              mm=round(todo, 1), g=round(self.grams(todo, spool_id), 2),
                              reason="final" if final else ("change" if b["gate"] == due_gate else reason))
                log.info("Booked: slot %d -> spool #%s %.1f mm (%.2f g)", b["gate"] + 1, spool_id, todo,
                         self.grams(todo, spool_id))
            elif res == "missing":
                log.warning("Spool #%s no longer exists - %.1f mm become an open item", spool_id, todo)
                self._add_open(job, b, todo, "spool_missing")
                b["booked_mm"] += todo  # is in the open item now
                self.save(force=True)
            # 'error': again next time
            self._dirty = True

    def _add_open(self, job: Dict[str, Any], b: Dict[str, Any], mm: float, reason: str) -> None:
        item = {
            "id": uuid.uuid4().hex[:8],
            "created": _now_iso(),
            "job": job["id"],
            "file": job["file"],
            "slot": b["gate"] + 1,
            "spool_id": b.get("spool_id") if reason == "retry" else None,
            "mm": round(mm, 1),
            "g_est": round(self.grams(mm, b.get("spool_id")), 2),
            "reason": reason,
            "ace": b.get("ace"),
        }
        self.open.append(item)
        self._journal("open", **item)
        self._dirty = True

    async def _retry_open(self) -> None:
        for item in list(self.open):
            if item.get("reason") != "retry" or not item.get("spool_id"):
                continue
            res = await self._use(item["spool_id"], item["mm"])
            if res == "ok":
                self.open.remove(item)
                self._dirty = True
                self.save(force=True)
                self._journal("book", job=item["job"], slot=item["slot"], spool=item["spool_id"],
                              mm=item["mm"], reason="retried")
                log.info("Retried: %.1f mm on spool #%s", item["mm"], item["spool_id"])
                self._dirty = True
            elif res == "missing":
                item["reason"], item["spool_id"] = "spool_missing", None
                self._dirty = True

    async def _finish(self, end_state: str) -> None:
        job = self.job
        if not job:
            return
        now = time.monotonic()
        self._settle(now, force=True)
        if job["pre_mm"]:
            # never a slot active (e.g. print without ACE): stays an open item without a slot
            job["buckets"].setdefault("x:-", {"gate": -1, "spool_id": None, "mm": 0.0, "booked_mm": 0.0,
                                              "last_book": 0.0, "ace": None})["mm"] += job["pre_mm"]
            job["pre_mm"] = 0.0
        await self._book(now, reason="end", final=True)
        await self.sm.refresh()  # update remaining weights for the page

        # what is not booked by now becomes an open item
        for b in job["buckets"].values():
            rest = b["mm"] - b["booked_mm"]
            if rest < 0.5:
                if rest <= -0.5:
                    log.info("Slot %d: %.1f mm net retract not booked back", b["gate"] + 1, -rest)
                continue
            reason = "no_spool" if b.get("spool_id") is None else "retry"
            self._add_open(job, b, rest, reason)
            b["booked_mm"] += rest if reason == "retry" else 0.0

        summary = self._summary(job, end_state)
        self.history.insert(0, summary)
        del self.history[self.cfg.job_history:]
        if self.purge is not None and summary.get("flush"):
            self.purge.learn(self.history)
        try:
            save_json(self.history_path, self.history, indent=1)
        except OSError as e:
            log.error("Saving the history failed: %s", e)
        self._journal("job_end", **{k: v for k, v in summary.items() if k != "slots"}, slots=summary["slots"])
        log.info("Print ended (%s): %s | total %.1f mm | %s", end_state, job["file"], summary["total_mm"],
                 ", ".join(f"Slot {s['slot']}: {s['mm']:.0f} mm/{s['g']:.1f} g" for s in summary["slots"]))
        for w in summary["warnings"]:
            log.warning("Check: %s", w)
        self.job = None
        self._book_due_gate = None
        self._dirty = True
        self.save(force=True)

    # ================================================================== evaluation
    def _summary(self, job: Dict[str, Any], end_state: str) -> Dict[str, Any]:
        per_slot: Dict[int, Dict[str, Any]] = {}
        for b in job["buckets"].values():
            s = per_slot.setdefault(b["gate"], {"slot": b["gate"] + 1, "gate": b["gate"], "mm": 0.0, "g": 0.0,
                                                "spools": [], "open_mm": 0.0})
            if b.get("direct"):
                s["direct"] = True             # direct feed: the ACE slot was passed by
            s["mm"] += b["mm"]
            s["g"] += self.grams(b["mm"], b.get("spool_id"))
            if b.get("spool_id"):
                s["spools"].append({"id": b["spool_id"], "label": self._spool_label(b["spool_id"]),
                                    "mm": round(b["mm"], 1)})
            else:
                s["open_mm"] += b["mm"]
        total = sum(b["mm"] for b in job["buckets"].values())
        targets = job.get("targets") or {}
        tgt = targets.get("per_gate") or {}
        warnings = []
        for s in per_slot.values():
            t = tgt.get(str(s["gate"]))
            s["target_mm"] = t["mm"] if t else None
            s["overhead_mm"] = round(s["mm"] - t["mm"], 1) if t else None
            s["mm"], s["g"], s["open_mm"] = round(s["mm"], 1), round(s["g"], 2), round(s["open_mm"], 1)
        target_total = sum(v["mm"] for v in tgt.values()) if tgt else None
        complete = end_state == "complete"
        if tgt and complete:
            for g, t in tgt.items():
                meas = per_slot.get(int(g), {}).get("mm", 0.0)
                if meas < t["mm"] * (1 - self.cfg.usage_tolerance):
                    warnings.append(tr("Slot {slot}: measured {meas:.0f} mm, the G-code says at least {want:.0f} mm "
                                       "(model)", slot=int(g) + 1, meas=float(meas), want=float(t["mm"])))
            for s in per_slot.values():
                if s["gate"] >= 0 and str(s["gate"]) not in tgt and s["mm"] > 50:
                    warnings.append(tr("Slot {slot}: {mm:.0f} mm used, not planned in the G-code (backup switch?)",
                                       slot=s["slot"], mm=float(s["mm"])))
        return {
            "job": job["id"],
            "file": job["file"],
            "started": job["started"],
            "ended": _now_iso(),
            "state": end_state,
            "total_mm": round(total, 1),
            "target_mm": round(target_total, 1) if target_total else None,
            "overhead_mm": round(total - target_total, 1) if target_total and complete else None,
            "loads": job["loads"],
            "changes": len(job["changes"]),
            "slots": sorted(per_slot.values(), key=lambda s: s["slot"]),
            "warnings": warnings,
            "flush": job.get("flush"),
            "slicer": job.get("slicer"),
            "transitions": group_transitions(job.get("transitions") or []),
        }

    def live(self) -> Optional[Dict[str, Any]]:
        """State of the running print for web UI, app and plugin."""
        job = self.job
        if not job:
            return None
        per: Dict[int, float] = {}
        for b in job["buckets"].values():
            per[b["gate"]] = per.get(b["gate"], 0.0) + b["mm"]
        if job["pending_gate"] is not None:
            per[job["pending_gate"]] = per.get(job["pending_gate"], 0.0) + job["pending_mm"]
        slots = []
        for gate, mm in sorted(per.items()):
            spool_id = self._spool_for_gate(gate) if gate >= 0 else None
            slots.append({"slot": gate + 1, "mm": round(mm, 1), "g": round(self.grams(mm, spool_id), 2)})
        return {"job": job["id"], "file": job["file"], "started": job["started"],
                "active_slot": (job["gate"] + 1) if job["gate"] is not None else None,
                "changes": len(job["changes"]), "slots": slots}

    def purge_stats(self) -> Dict[str, Any]:
        """Firmware purge for the plugin's usage forecast under Rinkhals: values and calibrated constants of the purge
        model (purge.py) - the plugin computes the purge per colour change with them. Empty under ACEPRO."""
        return {"model": self.purge.state()} if self.purge is not None else {}

    def last_by_slot(self) -> Dict[int, Dict[str, Any]]:
        """Consumption per slot in the last finished print."""
        if not self.history:
            return {}
        last = self.history[0]
        return {s["slot"]: {"mm": s["mm"], "g": s["g"], "file": last["file"], "ended": last["ended"]}
                for s in last["slots"] if s["slot"] > 0}

    # ================================================================== open items (API)
    async def resolve_open(self, item_id: str, spool_id: Optional[int]) -> Dict[str, Any]:
        async with self._lock:
            item = next((i for i in self.open if i["id"] == item_id), None)
            if not item:
                raise KeyError(tr("open item not found"))
            if spool_id is None:
                self.open.remove(item)
                self._journal("discard", **item)
                log.info("Open item %s discarded (%.1f mm)", item_id, item["mm"])
                self._dirty = True
                self.save(force=True)
                return {"discarded": item}
            if not self.sm.spool(spool_id):
                await self.sm.refresh()
                if not self.sm.spool(spool_id):
                    raise ValueError(tr("Spool #{id} not found", id=spool_id))
            self._backoff_until = 0.0  # manual action: try at once
            res = await self._use(spool_id, item["mm"])
            if res != "ok":
                raise RuntimeError(tr("Booking failed") if res == "error" else tr("Spool #{id} not found", id=spool_id))
            self.open.remove(item)
            self._journal("book", job=item["job"], slot=item["slot"], spool=spool_id, mm=item["mm"],
                          reason="booked later")
            log.info("Open item %s booked on spool #%s (%.1f mm)", item_id, spool_id, item["mm"])
            self._dirty = True
            self.save(force=True)
            return {"booked": {**item, "spool_id": spool_id}}
