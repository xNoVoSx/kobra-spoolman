"""Auto-PA: Pressure Advance zwischen Spoolman und dem Klipper-Modul kobra_pa (Kobra S1, Wiegezelle).

Das Klipper-Modul misst PA je Geschwindigkeit und wendet es an; die Werte gehoeren aber zum Filament in Spoolman:
- Zusatzfeld `pa_table` (Text, JSON): {"speeds": [100, 200, 300], "k": [...], "temp", "nozzle", "kind", "date"}
- Zusatzfeld `pressure_advance` (Orca-Wert): K bei 200 mm/s - so druckt auch Orca damit.
Es zaehlen nur Werte am Filament selbst, nicht von der Vorlage geerbte (sonst wuerde nie gemessen).

Die Bridge gibt Klipper pro Slot den Stand (KOBRA_PA_SET): Tabelle, festes PA (nur pressure_advance von Hand) oder
NONE=1 = "noch nicht gemessen" - dann misst Klipper beim naechsten Druck mit diesem Slot (wenn dort eingeschaltet).
Neue Ergebnisse (Status `kobra_pa.result`) schreibt sie ans Filament zurueck.

Abschaltbar: Einstellung `pa_sync` (Bridge gibt nichts weiter, schreibt nichts zurueck); die Schalter in Klipper
(KOBRA_PA ENABLE/AUTO) setzt POST /api/pa/switch.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .spoolman import extra_value

if TYPE_CHECKING:
    from .config import Config
    from .moonraker import Moonraker
    from .slots import SlotManager
    from .spoolman import Spoolman

log = logging.getLogger("pa")

OBJ = "kobra_pa"
SUBSCRIBE = {OBJ: ["enabled", "auto", "patched", "measuring", "active_t", "slots", "result", "result_seq"]}
FIELD = "pa_table"
FIELD_DEF = {"name": "PA-Tabelle (Auto-PA)", "field_type": "text", "order": 43}
SPEED_REF = 200.0           # mm/s: K fuer Orcas Feld und das globale PA (wie kobra_pa.SPEED_REF)
RECENT_S = 12 * 3600        # so lange steht eine Mess-Meldung in der Uebersicht


class PaError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


def k_at(speeds: List[float], ks: List[float], v: float = SPEED_REF) -> float:
    """K bei Geschwindigkeit v wie das Klipper-Modul: Randwert ausserhalb, dazwischen linear; steigt K zwischen
    zwei Stufen, gilt der untere Wert (wie GoKlipper)."""
    if len(ks) == 1:
        return ks[0]
    v = min(max(v, speeds[0]), speeds[-1])
    for i in range(1, len(speeds)):
        if v <= speeds[i]:
            x1, y1, x2, y2 = speeds[i - 1], ks[i - 1], speeds[i], ks[i]
            return y1 if y1 < y2 else y1 + (y2 - y1) * (v - x1) / (x2 - x1)
    return ks[-1]


def _table(raw: Any) -> Optional[Dict[str, Any]]:
    """pa_table aus Spoolman (Text mit JSON, evtl. doppelt kodiert) -> {"speeds", "k", ...} oder None."""
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
    """PA eines Filaments (nur eigene Werte): Tabelle, sonst festes pressure_advance, sonst None."""
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
        self.pushed: Dict[int, str] = {}           # T -> zuletzt geschickter KOBRA_PA_SET
        self.events: List[Dict[str, Any]] = []     # {"at", "level", "text"} fuer die Meldungen
        self.calibrating: Optional[int] = None     # Slot, fuer den eine Messung von Hand laeuft
        self._file = os.path.join(cfg.data_dir, "pa.json")
        self.done = self._load()                   # Zeit des letzten uebernommenen Ergebnisses

    def _load(self) -> float:
        try:
            with open(self._file, encoding="utf-8") as fh:
                return float(json.load(fh).get("done", 0))
        except (OSError, ValueError, TypeError):
            return 0.0

    def _save(self) -> None:
        tmp = self._file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"done": self.done}, fh)
        os.replace(tmp, self._file)

    # ------------------------------------------------------------ Zustand
    @property
    def klipper(self) -> Optional[Dict[str, Any]]:
        st = self.moon.status.get(OBJ)
        return st if st and self.moon.klippy_ready else None

    def desired(self) -> Dict[int, str]:
        """Pro Werkzeug T (Slot - 1) der KOBRA_PA_SET-Befehl fuer den aktuellen Spoolman-Stand."""
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
        """Nach jeder Aenderung (Slots, Spoolman, Klipper): Stand an Klipper geben, neue Ergebnisse uebernehmen."""
        kp = self.klipper
        if full or kp is None:
            # Klipper neu gestartet (Moonraker meldet klippy_ready -> neues Abo, full) oder weg: alles neu schicken
            self.pushed.clear()
        if not getattr(self.cfg, "pa_sync", True) or kp is None:
            return
        if not getattr(self.sm, "connected", True):
            return                     # ohne Spoolman-Stand nichts schicken (sonst "leer" fuer alle Slots)
        await self._take_result(kp)
        if kp.get("measuring"):
            return
        want = self.desired()
        cmds = [c for t, c in sorted(want.items()) if self.pushed.get(t) != c]
        if not cmds:
            return
        try:
            await self.moon.gcode("\n".join(cmds), source="Auto-PA")
        except Exception as e:  # noqa: BLE001
            log.warning("Auto-PA: Werte an Klipper fehlgeschlagen: %s", e)
            return
        self.pushed.update(want)
        log.info("Auto-PA an Klipper: %s", "; ".join(cmds))

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
        name = (fil or {}).get("name") or (f"Filament #{fil_id}" if fil_id else f"Slot {int(res.get('t', 0)) + 1}")
        if res.get("kind") == "error" or not res.get("k"):
            self._event("warn", f"PA-Messung {name} fehlgeschlagen: {res.get('message') or 'unbekannt'} – "
                                "es bleibt beim bisherigen PA")
            self._save()
            return
        if fil is None:
            self._event("warn", f"PA für Slot {int(res.get('t', 0)) + 1} gemessen, aber kein Spoolman-Filament – "
                                "nicht gespeichert")
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
            self.done = prev                                     # beim naechsten Status nochmal versuchen
            log.warning("Auto-PA: Ergebnis fuer %s nicht in Spoolman gespeichert: %s", name, e)
            self._event("warn", f"PA für {name} gemessen, Spoolman nicht erreichbar – wird nachgeholt")
            return
        self._save()
        log.info("Auto-PA: %s gemessen (%s), K %s @ %s mm/s -> Spoolman", name, table["kind"],
                 table["k"], table["speeds"])
        self._event("info", f"PA für {name} gemessen: {k200:.3f} (bei 200 mm/s"
                            + (", je Geschwindigkeit)" if len(table["k"]) > 1 else ")"))

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
            "last": ({k: res.get(k) for k in ("t", "kind", "speeds", "k", "temp", "message", "time")} if res else None),
        }

    async def switch(self, enabled: Optional[bool] = None, auto: Optional[bool] = None) -> Dict[str, Any]:
        if self.klipper is None:
            raise PaError(503, "Auto-PA ist in Klipper nicht eingerichtet (Modul kobra_pa) oder Klipper nicht bereit")
        parts = []
        if enabled is not None:
            parts.append(f"ENABLE={int(bool(enabled))}")
        if auto is not None:
            parts.append(f"AUTO={int(bool(auto))}")
        if not parts:
            raise PaError(400, "nichts zu ändern (enabled, auto)")
        await self.moon.gcode("KOBRA_PA " + " ".join(parts), source="Auto-PA")
        return self.view()

    def calibrate(self, slot: int) -> None:
        """Messung von Hand starten (laeuft ~2 min im Hintergrund; das Ergebnis kommt ueber den Status)."""
        import asyncio
        kp = self.klipper
        if kp is None:
            raise PaError(503, "Auto-PA ist in Klipper nicht eingerichtet oder Klipper nicht bereit")
        if not kp.get("enabled"):
            raise PaError(409, "Auto-PA ist in Klipper ausgeschaltet")
        if not kp.get("patched"):
            raise PaError(409, "Klipper ohne Auto-PA-Patch – messen geht nicht")
        if self.slots.printing:
            raise PaError(409, "Während eines Drucks misst Klipper selbst, wenn ein Filament noch kein PA hat")
        if kp.get("measuring") or self.calibrating is not None:
            raise PaError(409, "Es läuft schon eine Messung")
        if not 1 <= slot <= 4:
            raise PaError(400, "Slot 1–4")
        self.calibrating = slot

        async def run():
            try:
                await self.moon.gcode(f"KOBRA_PA_CALIBRATE T={slot - 1}", source="Auto-PA", timeout=600)
            except Exception as e:  # noqa: BLE001
                self.calibrating = None
                self._event("warn", f"PA-Messung Slot {slot}: {e}")
        asyncio.get_running_loop().create_task(run())

    async def forget(self, filament_id: int) -> None:
        """PA eines Filaments in Spoolman loeschen - der naechste Druck damit misst neu (wenn eingeschaltet)."""
        if self.sm.filament(filament_id) is None:
            raise PaError(404, "Filament nicht gefunden")
        await self.sm.patch_filament(filament_id, {"extra": {FIELD: None, "pressure_advance": None}})
        self._event("info", f"PA von Filament #{filament_id} gelöscht – wird beim nächsten Druck neu gemessen")
