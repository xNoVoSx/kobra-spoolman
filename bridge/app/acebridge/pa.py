"""Auto PA: pressure advance between Spoolman and the Klipper module kobra_pa (Kobra S1, load cell).

The Klipper module measures PA per speed and applies it; the values belong to the filament in Spoolman though:
- extra field `pa_table` (text, JSON), one table per nozzle (swappable hotends, kobra_nozzle):
  {"nozzles": {"0.4": {"speeds": [100, 200, 300], "k": [...], "temp", "kind", "date"}, "0.6": {...}}}
  The older single table {"speeds", "k", "nozzle", ...} still reads - as the table of its nozzle (none: 0.4).
- extra field `pressure_advance` (Orca value): K at 200 mm/s of the last measurement - so Orca prints with it too.
Only values on the filament itself count, not ones inherited from the template (otherwise it would never measure).
The nozzle in use comes from kobra_nozzle (Klipper); without it 0.4. A filament with tables but none for this nozzle
counts as "not measured yet" - Klipper measures it at the next print (pressure_advance is then the value of another
nozzle, not one set by hand).

Per slot the bridge gives Klipper the state (KOBRA_PA_SET): table, fixed PA (pressure_advance set by hand only) or
NONE=1 = "not measured yet" - then Klipper measures at the next print with this slot (when switched on there).
New results (status `kobra_pa.result`) are written back to the filament. Result messages come from the Klipper module.

Can be switched off: setting `pa_sync` (the bridge passes nothing on, writes nothing back); the switches in Klipper
(KOBRA_PA ENABLE/AUTO) are set by POST /api/pa/switch.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .gcodepush import GcodePush
from .i18n import tr
from .spoolman import extra_value
from .storage import save_json

if TYPE_CHECKING:
    from .direct import DirectFeed
    from .config import Config
    from .moonraker import Moonraker
    from .slots import SlotManager
    from .spoolman import Spoolman

log = logging.getLogger("pa")

OBJ = "kobra_pa"
SUBSCRIBE = {OBJ: ["enabled", "auto", "patched", "measuring", "active_t", "slots", "result", "result_seq"]}
FIELD = "pa_table"
FIELD_DEF = {"name": "PA table (auto PA)", "field_type": "text", "order": 43}
SPEED_REF = 200.0           # mm/s: K for Orca's field and the global PA (like kobra_pa.SPEED_REF)
NOZZLE_DEFAULT = 0.4        # without kobra_nozzle (and for tables measured before 4.3.0 without a nozzle)
RECENT_S = 12 * 3600        # a measurement message stays in the overview this long


class PaError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


def k_at(speeds: List[float], ks: List[float], v: float = SPEED_REF) -> float:
    """K at speed v like the Klipper module: edge value outside, linear in between; if K rises between two steps,
    the lower value applies (like GoKlipper)."""
    if len(ks) == 1:
        return ks[0]
    v = min(max(v, speeds[0]), speeds[-1])
    for i in range(1, len(speeds)):
        if v <= speeds[i]:
            x1, y1, x2, y2 = speeds[i - 1], ks[i - 1], speeds[i], ks[i]
            return y1 if y1 < y2 else y1 + (y2 - y1) * (v - x1) / (x2 - x1)
    return ks[-1]


def nozzle_key(nozzle: Any) -> str:
    """Nozzle diameter as the key of the table: 0.4 -> "0.4", 0.25 -> "0.25"."""
    try:
        return f"{float(nozzle):g}"
    except (TypeError, ValueError):
        return f"{NOZZLE_DEFAULT:g}"


def _json(raw: Any) -> Any:
    """Text with JSON, maybe encoded twice (Spoolman text field)."""
    for _ in range(2):
        if not isinstance(raw, str):
            break
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    return raw


def _table(raw: Any) -> Optional[Dict[str, Any]]:
    """One table {"speeds", "k", ...} -> sorted and checked, or None."""
    raw = _json(raw)
    if not isinstance(raw, dict):
        return None
    try:
        pairs = sorted((float(v), float(k)) for v, k in zip(raw["speeds"], raw["k"], strict=True))
    except (KeyError, TypeError, ValueError):
        return None
    if not pairs or any(not 0 < k < 1 or v <= 0 for v, k in pairs):
        return None
    return {**raw, "speeds": [v for v, _ in pairs], "k": [k for _, k in pairs]}


def tables(fil: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """All PA tables of a filament by nozzle ("0.4" -> table); the older single table under its own nozzle."""
    raw = _json(extra_value(fil, FIELD))
    if not isinstance(raw, dict):
        return {}
    if isinstance(raw.get("nozzles"), dict):
        out = {}
        for key, tbl in raw["nozzles"].items():
            t = _table(tbl)
            if t:
                out[nozzle_key(key)] = {**t, "nozzle": float(nozzle_key(key))}
        return out
    t = _table(raw)
    return {nozzle_key(t.get("nozzle") or NOZZLE_DEFAULT): t} if t else {}


def filament_pa(fil: Dict[str, Any], nozzle: Any = None) -> Optional[Dict[str, Any]]:
    """PA of a filament for a nozzle (own values only): its table, else fixed pressure_advance (set by hand - only
    when the filament has no measured table at all), else None = measure."""
    tbls = tables(fil)
    tbl = tbls.get(nozzle_key(nozzle if nozzle is not None else NOZZLE_DEFAULT))
    if tbl:
        return {**tbl, "source": "table"}
    if tbls:
        return None                # measured for another nozzle only: pressure_advance is that one's value
    pa = extra_value(fil, "pressure_advance")
    if isinstance(pa, (int, float)) and 0 < pa < 1:
        return {"speeds": [SPEED_REF], "k": [float(pa)], "source": "manual"}
    return None


def _fmt(vals: List[float], nd: int) -> str:
    return ",".join(f"{v:.{nd}f}".rstrip("0").rstrip(".") for v in vals)


class PaSync:
    def __init__(self, cfg: "Config", moon: "Moonraker", sm: "Spoolman", slots: "SlotManager"):
        self.cfg, self.moon, self.sm, self.slots = cfg, moon, sm, slots
        self.direct: Optional["DirectFeed"] = None    # set by the bridge (direct.py)
        self.pushed: Dict[int, str] = {}           # T -> last KOBRA_PA_SET sent
        self.push = GcodePush(moon, tr("Auto PA"))  # at most one request in flight (the print start holds Klipper)
        self.events: List[Dict[str, Any]] = []     # {"at", "level", "text"} for the messages
        self.calibrating: Optional[int] = None     # slot a manual measurement is running for
        self._file = os.path.join(cfg.data_dir, "pa.json")
        self.done = self._load()                   # time of the last result taken over

    def _load(self) -> float:
        try:
            with open(self._file, encoding="utf-8") as fh:
                return float(json.load(fh).get("done", 0))
        except (OSError, ValueError, TypeError):
            return 0.0

    def _save(self) -> None:
        save_json(self._file, {"done": self.done})

    # ------------------------------------------------------------ state
    @property
    def klipper(self) -> Optional[Dict[str, Any]]:
        st = self.moon.status.get(OBJ)
        return st if st and self.moon.klippy_ready else None

    def nozzle(self) -> float:
        """Nozzle in use: kobra_nozzle (swappable hotends) when it is there and on, else 0.4."""
        kn = self.moon.status.get("kobra_nozzle") or {}
        d = kn.get("diameter")
        return float(d) if kn.get("enabled") and isinstance(d, (int, float)) and d > 0 else NOZZLE_DEFAULT

    def desired(self) -> Dict[int, str]:
        """Per tool T (slot - 1) the KOBRA_PA_SET command for the current Spoolman state and nozzle."""
        nozzle = self.nozzle()
        assigned, _ = self.slots.assignments()
        if self.direct is not None:
            assigned = self.direct.per_tool(assigned)     # direct feed: the direct spool for every tool
        out = {}
        for slot in range(1, 5):
            t = slot - 1
            spool = assigned.get(slot)
            fil = (spool or {}).get("filament") or {}
            if not fil.get("id"):
                out[t] = f"KOBRA_PA_SET T={t} CLEAR=1"
                continue
            pa = filament_pa(fil, nozzle)
            if pa:
                out[t] = (f"KOBRA_PA_SET T={t} SPEEDS={_fmt(pa['speeds'], 1)} K={_fmt(pa['k'], 5)} "
                          f"FILAMENT={fil['id']}")
            else:
                temp = fil.get("settings_extruder_temp")
                out[t] = (f"KOBRA_PA_SET T={t} NONE=1 FILAMENT={fil['id']}"
                          + (f" TEMP={int(temp)}" if isinstance(temp, (int, float)) and temp > 0 else ""))
        return out

    async def tick(self, full: bool = False) -> None:
        """After every change (slots, Spoolman, Klipper): give the state to Klipper, take over new results."""
        kp = self.klipper
        if full or kp is None:
            # Klipper restarted (Moonraker reports klippy_ready -> new subscription, full) or gone: send everything again
            self.pushed.clear()
        if not getattr(self.cfg, "pa_sync", True) or kp is None:
            return
        if not getattr(self.sm, "connected", True):
            return                     # send nothing without Spoolman data (else "empty" for all slots)
        await self._take_result(kp)
        if kp.get("measuring"):
            return
        want = self.desired()
        cmds = [c for t, c in sorted(want.items()) if self.pushed.get(t) != c]
        if not cmds or self.push.busy:
            return

        def done(ok, err):
            if ok:
                self.pushed.update(want)
                log.info("Auto PA to Klipper: %s", "; ".join(cmds))
            else:
                log.warning("Auto PA: values to Klipper failed: %s", str(err) or type(err).__name__)
        await self.push.send("\n".join(cmds), done)

    def _event(self, level: str, text: str) -> None:
        self.events = [e for e in self.events if time.time() - e["at"] < RECENT_S][-9:]
        self.events.append({"at": time.time(), "level": level, "text": text})

    async def _take_result(self, kp: Dict[str, Any]) -> None:
        res = kp.get("result")
        if not isinstance(res, dict) or float(res.get("time") or 0) <= self.done:
            return
        prev, self.done = self.done, float(res["time"])
        self.calibrating = None
        fil_id = res.get("filament")
        fil = self.sm.filament(int(fil_id)) if str(fil_id or "").isdigit() else None
        name = (fil or {}).get("name") or (f"Filament #{fil_id}" if fil_id else tr("Slot {n}", n=int(res.get("t", 0)) + 1))
        if res.get("kind") == "error" or not res.get("k"):
            self._event("warn", tr("PA measurement {name} failed: {message} – the previous PA stays", name=name,
                                   message=res.get("message") or tr("unknown")))
            self._save()
            return
        if fil is None:
            self._event("warn", tr("PA measured for slot {n}, but no Spoolman filament – not saved",
                                   n=int(res.get("t", 0)) + 1))
            self._save()
            return
        nozzle = res.get("nozzle") if isinstance(res.get("nozzle"), (int, float)) else NOZZLE_DEFAULT
        table = {"speeds": res["speeds"], "k": [round(k, 5) for k in res["k"]], "temp": res.get("temp"),
                 "kind": res.get("kind"), "date": time.strftime("%Y-%m-%d", time.localtime(float(res["time"])))}
        k200 = round(k_at(table["speeds"], table["k"]), 4)
        # the tables of the other nozzles stay; the older single table becomes the entry of its nozzle
        alltbl = {key: {k: v for k, v in t.items() if k != "nozzle"} for key, t in tables(fil).items()}
        alltbl[nozzle_key(nozzle)] = table
        try:
            await self.sm.ensure_field("filament", FIELD, FIELD_DEF)
            await self.sm.patch_filament(fil["id"], {"extra": {
                FIELD: json.dumps(json.dumps({"nozzles": alltbl}, separators=(",", ":"))),
                "pressure_advance": json.dumps(k200)}})
        except Exception as e:  # noqa: BLE001
            self.done = prev                                     # try again with the next status
            log.warning("Auto PA: result for %s not saved in Spoolman: %s", name, e)
            self._event("warn", tr("PA measured for {name}, Spoolman not reachable – will be saved later", name=name))
            return
        self._save()
        log.info("Auto PA: %s measured (%s, nozzle %s), K %s @ %s mm/s -> Spoolman", name, table["kind"],
                 nozzle_key(nozzle), table["k"], table["speeds"])
        if len(table["k"]) > 1:
            self._event("info", tr("PA measured for {name}: {k:.3f} (at 200 mm/s, per speed, nozzle {nozzle})",
                                   name=name, k=k200, nozzle=nozzle_key(nozzle)))
        else:
            self._event("info", tr("PA measured for {name}: {k:.3f} (at 200 mm/s, nozzle {nozzle})", name=name,
                                   k=k200, nozzle=nozzle_key(nozzle)))

    # ------------------------------------------------------------ API
    def view(self) -> Dict[str, Any]:
        kp = self.klipper or {}
        nozzle = self.nozzle()
        assigned, _ = self.slots.assignments()
        slots = []
        for slot in range(1, 5):
            t = slot - 1
            fil = ((assigned.get(slot) or {}).get("filament") or {})
            ks = (kp.get("slots") or {}).get(str(t)) or {}
            pa = filament_pa(fil, nozzle) if fil.get("id") else None
            slots.append({
                "slot": slot, "filament_id": fil.get("id"), "name": fil.get("name"),
                "state": ks.get("state") or ("table" if pa else "needed" if fil.get("id") else "empty"),
                "source": (pa or {}).get("source"),            # table | manual | None
                "speeds": (pa or {}).get("speeds") or [], "k": (pa or {}).get("k") or [],
                "k_ref": round(k_at(pa["speeds"], pa["k"]), 4) if pa else None,
                "date": (pa or {}).get("date"),
                "active": kp.get("active_t") == t,
                "nozzles": sorted(tables(fil), key=float) if fil.get("id") else [],     # measured for these nozzles
            })
        res = kp.get("result") if isinstance(kp.get("result"), dict) else None
        return {
            "present": bool(kp), "sync": bool(getattr(self.cfg, "pa_sync", True)),
            "enabled": kp.get("enabled"), "auto": kp.get("auto"), "patched": kp.get("patched"),
            "measuring": bool(kp.get("measuring")), "calibrating": self.calibrating,
            "nozzle": nozzle_key(nozzle),                       # the values shown are for this nozzle
            "slots": slots,
            # lists never null (a failed measurement has no k) - the app expects lists
            "last": ({**{k: res.get(k) for k in ("t", "kind", "temp", "message", "time")},
                      "speeds": res.get("speeds") or [], "k": res.get("k") or []} if res else None),
        }

    async def switch(self, enabled: Optional[bool] = None, auto: Optional[bool] = None) -> Dict[str, Any]:
        if self.klipper is None:
            raise PaError(503, tr("Auto PA is not set up in Klipper (module kobra_pa) or Klipper is not ready"))
        parts = []
        if enabled is not None:
            parts.append(f"ENABLE={int(bool(enabled))}")
        if auto is not None:
            parts.append(f"AUTO={int(bool(auto))}")
        if not parts:
            raise PaError(400, tr("nothing to change (enabled, auto)"))
        await self.moon.gcode("KOBRA_PA " + " ".join(parts), source=tr("Auto PA"))
        return self.view()

    def calibrate(self, slot: int) -> None:
        """Start a manual measurement (runs ~5 min in the background; the result arrives through the status)."""
        import asyncio
        kp = self.klipper
        if kp is None:
            raise PaError(503, tr("Auto PA is not set up in Klipper or Klipper is not ready"))
        if not kp.get("enabled"):
            raise PaError(409, tr("Auto PA is switched off in Klipper"))
        if not kp.get("patched"):
            raise PaError(409, tr("Klipper without the auto PA patch – cannot measure"))
        if self.slots.printing:
            raise PaError(409, tr("During a print Klipper measures by itself when a filament has no PA yet"))
        if kp.get("measuring") or self.calibrating is not None:
            raise PaError(409, tr("A measurement is already running"))
        if not 1 <= slot <= 4:
            raise PaError(400, tr("Slot 1–4"))
        self.calibrating = slot

        async def run():
            try:
                await self.moon.gcode(f"KOBRA_PA_CALIBRATE T={slot - 1}", source=tr("Auto PA"), timeout=600)
            except Exception as e:  # noqa: BLE001
                self.calibrating = None
                self._event("warn", tr("PA measurement slot {n}: {error}", n=slot, error=str(e)))
        asyncio.get_running_loop().create_task(run())

    async def forget(self, filament_id: int) -> None:
        """Delete a filament's PA for the nozzle in use in Spoolman (the other nozzles' tables stay) - the next print
        with it measures again (when switched on)."""
        fil = self.sm.filament(filament_id)
        if fil is None:
            raise PaError(404, tr("Filament not found"))
        key = nozzle_key(self.nozzle())
        rest = {k: {x: v for x, v in t.items() if x != "nozzle"} for k, t in tables(fil).items() if k != key}
        if rest:
            await self.sm.patch_filament(filament_id, {"extra": {
                FIELD: json.dumps(json.dumps({"nozzles": rest}, separators=(",", ":")))}})
        else:
            await self.sm.patch_filament(filament_id, {"extra": {FIELD: None, "pressure_advance": None}})
        self._event("info", tr("PA of filament #{id} deleted for nozzle {nozzle} – measured again at the next print",
                               id=filament_id, nozzle=key))
