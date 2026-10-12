"""Auto PA: pressure advance between Spoolman and the Klipper module kobra_pa (Kobra S1, load cell).

The Klipper module measures PA per speed and applies it; the values belong to the filament in Spoolman though:
- extra field `pa_table` (text, JSON): {"speeds": [100, 200, 300], "k": [...], "temp", "nozzle", "kind", "date"}
- extra field `pressure_advance` (Orca value): K at 200 mm/s - so Orca prints with it too.
Only values on the filament itself count, not ones inherited from the template (otherwise it would never measure).

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


def _table(raw: Any) -> Optional[Dict[str, Any]]:
    """pa_table from Spoolman (text with JSON, maybe encoded twice) -> {"speeds", "k", ...} or None."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None
    try:
        pairs = sorted((float(v), float(k)) for v, k in zip(raw["speeds"], raw["k"], strict=True))
    except (KeyError, TypeError, ValueError):
        return None
    if not pairs or any(not 0 < k < 1 or v <= 0 for v, k in pairs):
        return None
    return {**raw, "speeds": [v for v, _ in pairs], "k": [k for _, k in pairs]}


def filament_pa(fil: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """PA of a filament (own values only): table, else fixed pressure_advance, else None."""
    tbl = _table(extra_value(fil, FIELD))
    if tbl:
        return {**tbl, "source": "table"}
    pa = extra_value(fil, "pressure_advance")
    if isinstance(pa, (int, float)) and 0 < pa < 1:
        return {"speeds": [SPEED_REF], "k": [float(pa)], "source": "manual"}
    return None


def _fmt(vals: List[float], nd: int) -> str:
    return ",".join(f"{v:.{nd}f}".rstrip("0").rstrip(".") for v in vals)


class PaSync:
    def __init__(self, cfg: "Config", moon: "Moonraker", sm: "Spoolman", slots: "SlotManager"):
        self.cfg, self.moon, self.sm, self.slots = cfg, moon, sm, slots
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

    def desired(self) -> Dict[int, str]:
        """Per tool T (slot - 1) the KOBRA_PA_SET command for the current Spoolman state."""
        assigned, _ = self.slots.assignments()
        out = {}
        for slot in range(1, 5):
            t = slot - 1
            spool = assigned.get(slot)
            fil = (spool or {}).get("filament") or {}
            if not fil.get("id"):
                out[t] = f"KOBRA_PA_SET T={t} CLEAR=1"
                continue
            pa = filament_pa(fil)
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
        table = {"speeds": res["speeds"], "k": [round(k, 5) for k in res["k"]], "temp": res.get("temp"),
                 "nozzle": res.get("nozzle"), "kind": res.get("kind"),
                 "date": time.strftime("%Y-%m-%d", time.localtime(float(res["time"])))}
        k200 = round(k_at(table["speeds"], table["k"]), 4)
        try:
            await self.sm.ensure_field("filament", FIELD, FIELD_DEF)
            await self.sm.patch_filament(fil["id"], {"extra": {
                FIELD: json.dumps(json.dumps(table, separators=(",", ":"))),
                "pressure_advance": json.dumps(k200)}})
        except Exception as e:  # noqa: BLE001
            self.done = prev                                     # try again with the next status
            log.warning("Auto PA: result for %s not saved in Spoolman: %s", name, e)
            self._event("warn", tr("PA measured for {name}, Spoolman not reachable – will be saved later", name=name))
            return
        self._save()
        log.info("Auto PA: %s measured (%s), K %s @ %s mm/s -> Spoolman", name, table["kind"],
                 table["k"], table["speeds"])
        if len(table["k"]) > 1:
            self._event("info", tr("PA measured for {name}: {k:.3f} (at 200 mm/s, per speed)", name=name, k=k200))
        else:
            self._event("info", tr("PA measured for {name}: {k:.3f} (at 200 mm/s)", name=name, k=k200))

    # ------------------------------------------------------------ API
    def view(self) -> Dict[str, Any]:
        kp = self.klipper or {}
        assigned, _ = self.slots.assignments()
        slots = []
        for slot in range(1, 5):
            t = slot - 1
            fil = ((assigned.get(slot) or {}).get("filament") or {})
            ks = (kp.get("slots") or {}).get(str(t)) or {}
            pa = filament_pa(fil) if fil.get("id") else None
            slots.append({
                "slot": slot, "filament_id": fil.get("id"), "name": fil.get("name"),
                "state": ks.get("state") or ("table" if pa else "needed" if fil.get("id") else "empty"),
                "source": (pa or {}).get("source"),            # table | manual | None
                "speeds": (pa or {}).get("speeds") or [], "k": (pa or {}).get("k") or [],
                "k_ref": round(k_at(pa["speeds"], pa["k"]), 4) if pa else None,
                "date": (pa or {}).get("date"),
                "active": kp.get("active_t") == t,
            })
        res = kp.get("result") if isinstance(kp.get("result"), dict) else None
        return {
            "present": bool(kp), "sync": bool(getattr(self.cfg, "pa_sync", True)),
            "enabled": kp.get("enabled"), "auto": kp.get("auto"), "patched": kp.get("patched"),
            "measuring": bool(kp.get("measuring")), "calibrating": self.calibrating,
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
        """Start a manual measurement (runs ~2 min in the background; the result arrives through the status)."""
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
        """Delete a filament's PA in Spoolman - the next print with it measures again (when switched on)."""
        if self.sm.filament(filament_id) is None:
            raise PaError(404, tr("Filament not found"))
        await self.sm.patch_filament(filament_id, {"extra": {FIELD: None, "pressure_advance": None}})
        self._event("info", tr("PA of filament #{id} deleted – measured again at the next print", id=filament_id))
