"""Verbrauchsmessung und -buchung pro Slot (Etappe 2).

Grundlage: print_stats.filament_used (Klipper, mm) zaehlt jeden Extruder-Vorschub im Druck - auch Laden und
Spuelen der ACE, die unter ACEPRO ueber die Duese laufen (mit ACEPRO-Patch 0003 sofort, nicht erst nach dem
Wechsel). Daraus folgt:

- Verbrauch = vorzeichenrichtige Differenz von filament_used. Rueckzuege heben sich auf.
- Jede Differenz gehoert dem Slot, der laut ACE-Treiber gerade verbraucht (acemodel.consuming_slot):
  dem geladenen Slot, waehrend eines Wechsels nach dem Entladen dem Ziel-Slot. Momente ohne solchen Slot
  zaehlen zum zuletzt aktiven Slot.
- Verbrauch vor dem ersten aktiven Slot bekommt der erste Slot, der aktiv wird.
- Gebucht wird auf die Spule, die zum Zeitpunkt des Verbrauchs im Slot war
  ("Topf" = Slot + Spule). Buchung beim Slotwechsel, bei Druckende und zwischendurch
  alle BOOK_INTERVAL_S.
- Verbrauch ohne zugeordnete Spule, oder auf eine inzwischen geloeschte Spule, wird ein
  offener Posten und kann in der Weboberflaeche nachgebucht werden.
- Alles steht in data/usage/state.json; startet die Bridge mitten im Druck neu, geht es
  am gespeicherten Zaehlerstand weiter.
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

if TYPE_CHECKING:
    from .moonraker import Moonraker
    from .purge import PurgeModel
    from .slots import SlotManager
    from .spoolman import Spoolman

log = logging.getLogger("usage")

PRINTING_STATES = ("printing", "paused")
SAVE_INTERVAL_S = 5.0
RETRY_BACKOFF_S = 30


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _numbers(raw: Any) -> List[float]:
    if isinstance(raw, (list, tuple)):
        vals = raw
    else:
        vals = re.findall(r"-?\d+(?:\.\d+)?", str(raw or ""))
    out = []
    for v in vals:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(0.0)
    return out


def parse_targets(vsd: Dict[str, Any], diameter: float) -> Optional[Dict[str, Any]]:
    """Sollwerte aus dem G-code-Kopf, wie die Anycubic-Firmware sie in virtual_sdcard meldet.

    filament_used heisst dort "... m", enthaelt aber cm3 (11.61 cm3 = 4.83 m bei 1,75 mm).
    Die Einheit wird ueber das Verhaeltnis zu den Gramm bestimmt, damit eine spaetere
    Firmware mit echten Metern nicht falsch gelesen wird.
    """
    vols = _numbers(vsd.get("filament_used"))
    grams = _numbers(vsd.get("filament_used_g"))
    if not vols or not any(vols):
        return None
    area = math.pi * (diameter / 2) ** 2  # mm2
    per_gate = {}
    unit = "cm3"
    # Plausibilitaet: g / cm3 muss eine Dichte sein (0.8 - 2.2)
    pairs = [(v, g) for v, g in zip(vols, grams, strict=False) if v > 0 and g > 0]
    if pairs:
        ratio = sum(g for _, g in pairs) / sum(v for v, _ in pairs)
        if not 0.8 <= ratio <= 2.2:
            unit = "m"
    for i, v in enumerate(vols):
        if v <= 0:
            continue
        mm = v * 1000.0 / area if unit == "cm3" else v * 1000.0
        per_gate[str(i)] = {"mm": round(mm, 1), "g": grams[i] if i < len(grams) else None}
    types = str(vsd.get("filament_type") or "").split(";")
    return {"unit": unit, "per_gate": per_gate, "total_g": vsd.get("filament_total_g"),
            "types": types}


def group_transitions(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Gleiche Wechsel (von, nach, Farben) zusammenfassen: [{..., "count": n}]."""
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
        self._lock = asyncio.Lock()
        self._dirty = False
        self._last_save = 0.0
        self._backoff_until = 0.0
        self.job: Optional[Dict[str, Any]] = None
        self.open: List[Dict[str, Any]] = []
        self.history: List[Dict[str, Any]] = []
        self.purge: Optional["PurgeModel"] = None    # setzt die Bridge (Spuel-Modell, purge.py)
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
            log.error("usage/state.json nicht lesbar (%s) - starte leer, Datei bleibt als .broken liegen", e)
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
            log.warning("usage/jobs.json nicht lesbar: %s", e)
        if self.job:
            log.info("Offener Druck aus letztem Lauf gefunden: %s (Zaehler %.1f mm)",
                     self.job.get("file"), self.job.get("last_used") or 0)

    def _atomic_write(self, path: str, data: Any) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)

    def save(self, force: bool = False) -> None:
        if not (self._dirty or force):
            return
        now = time.time()
        if not force and now - self._last_save < SAVE_INTERVAL_S:
            return
        try:
            self._atomic_write(self.state_path, {"job": self.job, "open": self.open})
            self._dirty = False
            self._last_save = now
        except OSError as e:
            log.error("Zustand speichern fehlgeschlagen: %s", e)

    def _journal(self, event: str, **data: Any) -> None:
        try:
            if os.path.exists(self.journal_path) and os.path.getsize(self.journal_path) > 5_000_000:
                os.replace(self.journal_path, self.journal_path + ".1")
            with open(self.journal_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": _now_iso(), "event": event, **data}, ensure_ascii=False) + "\n")
        except OSError as e:
            log.error("Journal schreiben fehlgeschlagen: %s", e)

    # ================================================================== Hilfen
    def _spool_for_gate(self, gate: int) -> Optional[int]:
        assigned, _ = self.slots.assignments()
        spool = assigned.get(gate + 1)
        return spool.get("id") if spool else None

    def _geometry(self, spool_id: Optional[int]) -> Tuple[float, float]:
        """(Durchmesser mm, Dichte g/cm3) der Spule, sonst Standardwerte."""
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
        a = self.slots.ace_gate(gate)
        return {"material": a.get("material"), "color": a.get("color"), "name": a.get("name")}

    # ================================================================== Job-Lebenszyklus
    def _new_job(self, status: Dict[str, Dict[str, Any]]) -> None:
        ps = status.get("print_stats", {}) or {}
        vsd = status.get("virtual_sdcard", {}) or {}
        used = ps.get("filament_used")
        self.job = {
            "id": time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4],
            "file": ps.get("filename") or "",
            "started": _now_iso(),
            "used_start": used if isinstance(used, (int, float)) else 0.0,
            "last_used": used if isinstance(used, (int, float)) else 0.0,
            "gate": None,              # Slot, dem der Verbrauch gerade gehoert (0-basiert)
            "pending_gate": None,      # nur noch fuer gespeicherte Stände aus Bridge < 3.0 (Entprellung)
            "pending_since": None,
            "pending_mm": 0.0,
            "pre_mm": 0.0,             # Verbrauch vor dem ersten aktiven Slot
            "buckets": {},             # "gate:spool" -> {gate, spool_id, mm, booked_mm, last_book}
            "loads": 0,                # wie oft ein Slot aktiv wurde (erster + Wechsel)
            "changes": [],             # Slotwechsel
            "transitions": [],         # jedes Laden mit ACE-Farben (fuer das Spuel-Modell)
            "slicer": vsd.get("slicer"),
            "flush": dict(self.purge.flush) if self.purge and self.purge.flush_source == "printer" else None,
            "targets": parse_targets(vsd, self.cfg.default_diameter),
        }
        self._dirty = True
        self._journal("job_start", job=self.job["id"], file=self.job["file"], used_start=self.job["used_start"],
                      targets=self.job["targets"])
        log.info("Druck gestartet: %s (Zaehler %.1f mm)", self.job["file"], self.job["used_start"])
        seen = acemodel.consuming_slot(status)
        if seen is not None:
            self._confirm_gate(seen)

    def _bucket(self, gate: int) -> Dict[str, Any]:
        assert self.job is not None
        spool_id = self._spool_for_gate(gate)
        key = f"{gate}:{spool_id or '-'}"
        b = self.job["buckets"].get(key)
        if b is None:
            b = {"gate": gate, "spool_id": spool_id, "mm": 0.0, "booked_mm": 0.0, "last_book": 0.0,
                 "ace": self._ace_info(gate)}
            self.job["buckets"][key] = b
        return b

    def _add(self, gate: int, mm: float) -> None:
        if mm:
            self._bucket(gate)["mm"] += mm
            self._dirty = True

    def _confirm_gate(self, gate: int) -> None:
        """gate ist ab jetzt der aktive Slot."""
        job = self.job
        assert job is not None
        old = job["gate"]
        if old == gate:
            return
        job["gate"] = gate
        job["loads"] += 1
        job.setdefault("transitions", []).append({
            "from_slot": old + 1 if old is not None else None, "to_slot": gate + 1,
            "from_color": self.slots.ace_gate(old)["color"] if old is not None else None,
            "to_color": self.slots.ace_gate(gate)["color"]})
        if job["pre_mm"]:
            self._add(gate, job["pre_mm"])
            job["pre_mm"] = 0.0
        if old is not None:
            job["changes"].append({"ts": _now_iso(), "from": old, "to": gate, "used": job["last_used"]})
            log.info("Slotwechsel %d -> %d bei %.1f mm", old + 1, gate + 1, job["last_used"])
            self._book_due_gate = old  # nach dem Wechsel den alten Slot buchen
        else:
            log.info("Slot %d aktiv", gate + 1)
        self._dirty = True

    _book_due_gate: Optional[int] = None

    def _observe_gate(self, seen: Optional[int], now: float) -> None:
        """Der ACE-Treiber meldet den verbrauchenden Slot ohne Flackern - Wechsel sofort uebernehmen."""
        job = self.job
        assert job is not None
        if seen is None or seen == job["gate"]:
            return  # kein Slot: Verbrauch geht weiter an den bisherigen
        self._settle(now, force=True)
        self._confirm_gate(seen)

    def _settle(self, now: float, force: bool = False) -> None:
        """Nur fuer gespeicherte Staende aus Bridge < 3.0: ausstehenden Slot (Entprellung) bestaetigen."""
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

    # ================================================================== Eingang
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

            # Sollwerte kommen manchmal erst nach dem Start an und werden spaeter geleert
            vsd_d = delta.get("virtual_sdcard") or {}
            if vsd_d.get("slicer") and not self.job.get("slicer"):
                self.job["slicer"] = vsd_d["slicer"]
            if "filament_used" in vsd_d and not self.job.get("targets"):
                t = parse_targets(status.get("virtual_sdcard", {}) or {}, self.cfg.default_diameter)
                if t:
                    self.job["targets"] = t
                    self._dirty = True

            ps_d = delta.get("print_stats") or {}
            # Neuer Druck, obwohl der alte nie sauber endete (Zaehler zurueckgesetzt, andere Datei)
            if "filename" in ps_d and ps_d["filename"] and ps_d["filename"] != self.job["file"] \
                    and state in PRINTING_STATES:
                log.warning("Neuer Druck ohne Ende des alten erkannt - schliesse %s ab", self.job["file"])
                await self._finish("abgebrochen (unbemerkt)")
                self._new_job(status)
                return

            # Reihenfolge: erst den Verbrauch dem bisher bekannten Slot geben, dann den Slot aktualisieren
            if "filament_used" in ps_d and isinstance(ps_d["filament_used"], (int, float)):
                self._consume(ps_d["filament_used"])
            if "ace" in delta:
                self._observe_gate(acemodel.consuming_slot(status), now)
            self._settle(now)

            if state not in PRINTING_STATES:
                await self._finish(state or "beendet")
            else:
                await self._book(now, reason="tick")
            self.save()

    async def _on_snapshot(self, status: Dict[str, Dict[str, Any]]) -> None:
        """Erster Status nach Start oder Wiederverbindung."""
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
                log.info("Setze Druck %s fort: %.1f mm seit dem letzten gespeicherten Stand",
                         self.job["file"], gap)
                self._journal("resume", job=self.job["id"], gap_mm=round(gap, 1))
            self._consume(used)
            self._observe_gate(acemodel.consuming_slot(status), time.monotonic())
            if not printing:
                await self._finish(state or "beendet")
        else:
            log.warning("Gespeicherter Druck %s passt nicht zum Drucker (%s, %s) - schliesse mit letztem Stand ab",
                        self.job["file"], ps.get("filename"), state)
            await self._finish("unterbrochen")
            if printing:
                self._new_job(status)
        self.save(force=True)

    async def tick(self) -> None:
        """Regelmaessig: Entprellung ohne neue Updates, Zwischenbuchung, Wiederholungen."""
        async with self._lock:
            now = time.monotonic()
            if self.job:
                self._settle(now)
                await self._book(now, reason="tick")
            await self._retry_open()
            self.save()

    # ================================================================== Buchen
    async def _use(self, spool_id: int, mm: float) -> str:
        """Bucht mm auf eine Spule. Rueckgabe: 'ok', 'missing' (Spule weg) oder 'error'."""
        if time.monotonic() < self._backoff_until:
            return "error"  # Spoolman war eben nicht erreichbar - nicht bei jedem Tick neu versuchen
        if not self.cfg.book_usage or self.cfg.dry_run:
            log.info("[%s] %.1f mm auf Spule #%s", "dry-run" if self.cfg.dry_run else "Buchung aus",
                     mm, spool_id)
            return "ok"
        try:
            await self.sm.use_length(spool_id, mm)
            return "ok"
        except LookupError:
            return "missing"
        except Exception as e:  # noqa: BLE001
            log.warning("Buchung auf Spule #%s fehlgeschlagen (%s) - neuer Versuch in %d s",
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
            if spool_id is None or abs(todo) < 0.05:
                continue
            if final or b["gate"] == due_gate:
                pass
            elif abs(todo) < self.cfg.book_min_mm or now - b.get("last_book", 0) < self.cfg.book_interval_s:
                continue
            res = await self._use(spool_id, todo)
            if res == "ok":
                b["booked_mm"] += todo
                b["last_book"] = now
                self._dirty = True
                self.save(force=True)  # sofort sichern, sonst koennte ein Absturz doppelt buchen
                self._journal("book", job=job["id"], slot=b["gate"] + 1, spool=spool_id,
                              mm=round(todo, 1), g=round(self.grams(todo, spool_id), 2),
                              reason="final" if final else ("wechsel" if b["gate"] == due_gate else reason))
                log.info("Gebucht: Slot %d -> Spule #%s %.1f mm (%.2f g)", b["gate"] + 1, spool_id, todo,
                         self.grams(todo, spool_id))
            elif res == "missing":
                log.warning("Spule #%s gibt es nicht mehr - %.1f mm werden offener Posten", spool_id, todo)
                self._add_open(job, b, todo, "spool_missing")
                b["booked_mm"] += todo  # ist jetzt im offenen Posten
                self.save(force=True)
            # 'error': beim naechsten Mal erneut
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
                              mm=item["mm"], reason="nachgeholt")
                log.info("Nachgeholt: %.1f mm auf Spule #%s", item["mm"], item["spool_id"])
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
            # nie ein Slot aktiv (z.B. Druck ohne ACE): bleibt ein offener Posten ohne Slot
            job["buckets"].setdefault("x:-", {"gate": -1, "spool_id": None, "mm": 0.0, "booked_mm": 0.0,
                                              "last_book": 0.0, "ace": None})["mm"] += job["pre_mm"]
            job["pre_mm"] = 0.0
        await self._book(now, reason="ende", final=True)
        await self.sm.refresh()  # Restgewichte fuer die Seite aktualisieren

        # Was jetzt noch nicht gebucht ist, wird offener Posten
        for b in job["buckets"].values():
            rest = b["mm"] - b["booked_mm"]
            if abs(rest) < 0.5:
                continue
            reason = "no_spool" if b.get("spool_id") is None else "retry"
            self._add_open(job, b, rest, reason)
            b["booked_mm"] += rest if reason == "retry" else 0.0

        summary = self._summary(job, end_state)
        self.history.insert(0, summary)
        del self.history[self.cfg.job_history:]
        if self.purge is not None:
            self.purge.learn(self.history)
        try:
            self._atomic_write(self.history_path, self.history)
        except OSError as e:
            log.error("Historie speichern fehlgeschlagen: %s", e)
        self._journal("job_end", **{k: v for k, v in summary.items() if k != "slots"}, slots=summary["slots"])
        log.info("Druck beendet (%s): %s | gesamt %.1f mm | %s", end_state, job["file"], summary["total_mm"],
                 ", ".join(f"Slot {s['slot']}: {s['mm']:.0f} mm/{s['g']:.1f} g" for s in summary["slots"]))
        for w in summary["warnings"]:
            log.warning("Abgleich: %s", w)
        self.job = None
        self._book_due_gate = None
        self._dirty = True
        self.save(force=True)

    # ================================================================== Auswertung
    def _summary(self, job: Dict[str, Any], end_state: str) -> Dict[str, Any]:
        per_slot: Dict[int, Dict[str, Any]] = {}
        for b in job["buckets"].values():
            s = per_slot.setdefault(b["gate"], {"slot": b["gate"] + 1, "gate": b["gate"], "mm": 0.0, "g": 0.0,
                                                "spools": [], "open_mm": 0.0})
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
                    warnings.append(f"Slot {int(g) + 1}: gemessen {meas:.0f} mm, laut G-code mindestens "
                                    f"{t['mm']:.0f} mm (Modell)")
            for s in per_slot.values():
                if s["gate"] >= 0 and str(s["gate"]) not in tgt and s["mm"] > 50:
                    warnings.append(f"Slot {s['slot']}: {s['mm']:.0f} mm verbraucht, im G-code nicht vorgesehen "
                                    "(Backup-Umschaltung?)")
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
            "slicer": job.get("slicer"),
            "flush": job.get("flush"),
            "transitions": group_transitions(job.get("transitions") or []),
        }

    def live(self) -> Optional[Dict[str, Any]]:
        """Stand des laufenden Drucks fuer Weboberflaeche, App und Plugin."""
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

    def last_by_slot(self) -> Dict[int, Dict[str, Any]]:
        """Verbrauch pro Slot im letzten abgeschlossenen Druck."""
        if not self.history:
            return {}
        last = self.history[0]
        return {s["slot"]: {"mm": s["mm"], "g": s["g"], "file": last["file"], "ended": last["ended"]}
                for s in last["slots"] if s["slot"] > 0}

    def purge_stats(self) -> Dict[str, Any]:
        """Spuelen der Firmware fuer die Vorschau im Plugin.

        "model": Firmware-Werte und eingemessene Konstanten des Spuel-Modells (purge.py) - damit
        rechnet das Plugin pro Farbwechsel. "overhead_per_load_mm": alter Mittelwert pro Laden fuer
        aeltere Plugins; nur aus Drucken, bei denen "gemessen - G-Code-Soll" das Spuelen ist
        (AnycubicSlicer schreibt seine Spuelmenge ins Soll, das macht den Wert falsch)."""
        out: Dict[str, Any] = {"jobs": 0}
        rows = [h for h in self.history if h.get("overhead_mm") is not None and h.get("loads")
                and h.get("slicer") != "AnycubicSlicer"]
        if rows:
            per_load = [h["overhead_mm"] / h["loads"] for h in rows]
            out = {"jobs": len(rows), "overhead_per_load_mm": round(sum(per_load) / len(per_load), 1),
                   "last": [{"file": h["file"], "overhead_mm": h["overhead_mm"], "loads": h["loads"]}
                            for h in rows[:10]]}
        if self.purge is not None:
            out["model"] = self.purge.state()
        return out

    # ================================================================== offene Posten (API)
    async def resolve_open(self, item_id: str, spool_id: Optional[int]) -> Dict[str, Any]:
        async with self._lock:
            item = next((i for i in self.open if i["id"] == item_id), None)
            if not item:
                raise KeyError("offener Posten nicht gefunden")
            if spool_id is None:
                self.open.remove(item)
                self._journal("discard", **item)
                log.info("Offener Posten %s verworfen (%.1f mm)", item_id, item["mm"])
                self._dirty = True
                self.save(force=True)
                return {"discarded": item}
            if not self.sm.spool(spool_id):
                await self.sm.refresh()
                if not self.sm.spool(spool_id):
                    raise ValueError(f"Spule #{spool_id} nicht gefunden")
            self._backoff_until = 0.0  # Handaktion: sofort versuchen
            res = await self._use(spool_id, item["mm"])
            if res != "ok":
                raise RuntimeError("Buchung fehlgeschlagen" if res == "error" else f"Spule #{spool_id} nicht gefunden")
            self.open.remove(item)
            self._journal("book", job=item["job"], slot=item["slot"], spool=spool_id, mm=item["mm"],
                          reason="nachgebucht")
            log.info("Offener Posten %s auf Spule #%s gebucht (%.1f mm)", item_id, spool_id, item["mm"])
            self._dirty = True
            self.save(force=True)
            return {"booked": {**item, "spool_id": spool_id}}
