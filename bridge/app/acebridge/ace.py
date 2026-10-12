"""ACE card: settings of the ACE the printer display does not show - per driver (acemodel.variant).

Klipper + ACEPRO - reading live from the subscription (object `ace`), writing with the driver's G-code (applies at
once, also during a print):
- endless spool: ACE_ENABLE_ENDLESS_SPOOL / ACE_DISABLE_ENDLESS_SPOOL
- mode:          ACE_SET_ENDLESS_SPOOL_MODE MODE=exact|material|next
Purge lengths come from Orca's matrix (the change-filament G-code passes them to the driver).

Rinkhals (GoKlipper's own ACE configuration, GET /printer/filament_hub/get_config through Moonraker, e.g.
{"auto_refill": 1, "flush_multiplier": 1, "flush_multiplier_editable": 1, "flush_volume_max": 800,
"flush_volume_min": 107, "runout_detect": 1}), read every 10 minutes and right after a change:
- endless spool = auto_refill, runout detection = runout_detect: filament_hub/set_config (as Rinkhals does it)
- purge multiplier: Rinkhals' SET_ACE_FLUSH_MULTIPLIER VALUE=<0.1-3.0>
During a print a change applies from the next colour change; Rinkhals changes then need "confirm_printing": true.
The purge per colour change is the firmware's own (purge.py predicts it, the card shows the pairs).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from . import acemodel
from .i18n import tr
from .purge import AREA_175, CONFIG_REFRESH_S, PurgeModel, change_mm, firmware_volume

if TYPE_CHECKING:
    from .moonraker import Moonraker
    from .slots import SlotManager

log = logging.getLogger("ace")

MODES = {"exact": tr("same colour and same material"), "material": tr("same material"), "next": tr("next spool")}
CONFIRM_WAIT_S = 2.0      # wait this long for the driver to confirm (the answer then shows the new state)
FLUSH_MIN, FLUSH_MAX = 0.1, 3.0          # Rinkhals allows 0-3; 0 would mean no purge at all
PRESETS = {"minimal": 0.1, "normal": 1.0, "maximum": 3.0}    # like Rinkhals' ACE_FLUSH_MINIMAL/NORMAL/MAXIMUM
RINKHALS_OPTIONS = {"endless_spool": "auto_refill", "runout_detect": "runout_detect"}


class AceError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


class AceSettings:
    def __init__(self, moon: "Moonraker", slots: "SlotManager", purge: Optional[PurgeModel] = None,
                 clock: Callable[[], float] = time.monotonic):
        self.moon = moon
        self.slots = slots
        self.purge = purge or PurgeModel()
        self.clock = clock
        self.config: Dict[str, Any] = {}       # GoKlipper's ACE configuration (Rinkhals)
        self.read_at: Optional[float] = None
        self._tried = 0.0

    @property
    def rinkhals(self) -> bool:
        return acemodel.variant(self.moon.status) == acemodel.RINKHALS

    # ------------------------------------------------------------ reading
    async def refresh(self, force: bool = False) -> None:
        """Rinkhals: GoKlipper's ACE configuration every 10 minutes (after a change at once; after a failure also only
        after 10 minutes). ACEPRO: nothing to poll - the driver reports its settings in the subscription."""
        if not self.rinkhals or not self.moon.klippy_ready:
            return
        now = self.clock()
        if not force and self._tried and now - self._tried < CONFIG_REFRESH_S:
            return
        self._tried = now
        try:
            cfg = await self.moon.get_json("/printer/filament_hub/get_config")
        except Exception as e:  # noqa: BLE001
            log.info("ACE settings not readable: %s", e)
            return
        if isinstance(cfg, dict) and cfg:
            self.config = dict(cfg)
            self.read_at = time.time()
            self.purge.set_flush_config(cfg)

    def state(self) -> Dict[str, Any]:
        st = self.moon.status
        present = bool(self.moon.klippy_ready and acemodel.connected(st))
        dry = acemodel.dryer(st)
        base = {"present": present, "variant": acemodel.variant(st), "firmware": dry.get("firmware"),
                "model": dry.get("model"), "printing": self.slots.printing}
        if self.rinkhals:
            c = self.config
            return {**base,
                    "options": ["endless_spool", "runout_detect", "flush_multiplier"],
                    "endless_spool": None if "auto_refill" not in c else bool(c["auto_refill"]),
                    "endless_mode": None, "endless_modes": {},
                    "runout_detect": None if "runout_detect" not in c else bool(c["runout_detect"]),
                    "flush_multiplier": c.get("flush_multiplier"),
                    "flush_multiplier_editable": bool(c.get("flush_multiplier_editable", 1)),
                    "flush_volume_min": c.get("flush_volume_min"), "flush_volume_max": c.get("flush_volume_max"),
                    "limits": {"flush_multiplier": [FLUSH_MIN, FLUSH_MAX]}, "presets": PRESETS,
                    "read_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.read_at)) if self.read_at else None}
        endless = acemodel.endless_spool(st)
        return {**base,
                "options": ["endless_spool", "endless_mode"],
                "endless_spool": endless["enabled"] if present else None,
                "endless_mode": endless["mode"] if present else None,
                "endless_modes": MODES,
                "read_at": time.strftime("%Y-%m-%dT%H:%M:%S") if present else None}

    # ------------------------------------------------------------ writing
    def _check(self, confirm_printing: bool = True) -> None:
        if not self.moon.klippy_ready or not acemodel.connected(self.moon.status):
            raise AceError(503, tr("ACE not connected"))
        if self.rinkhals and self.slots.printing and not confirm_printing:
            raise AceError(409, tr("A print is running – unlock the change first (applies from the next colour change)"))

    async def set_options(self, changes: Dict[str, Any], confirm_printing: bool = False) -> Dict[str, Any]:
        """ACEPRO: endless spool on/off (endless_spool) and mode (endless_mode) - harmless, also during a print, applies at
        the next runout. Rinkhals: endless_spool, runout_detect, flush_multiplier."""
        if not changes:
            raise AceError(400, tr("Nothing to change"))
        if self.rinkhals:
            return await self._set_rinkhals(changes, confirm_printing)
        cmds, want = [], {}
        for k, v in changes.items():
            if k == "endless_spool":
                if not isinstance(v, bool):
                    raise AceError(400, tr("{key}: true or false", key=k))
                cmds.append("ACE_ENABLE_ENDLESS_SPOOL" if v else "ACE_DISABLE_ENDLESS_SPOOL")
                want["enabled"] = v
            elif k == "endless_mode":
                if v not in MODES:
                    raise AceError(400, tr("Mode: {modes}", modes=", ".join(MODES)))
                cmds.append(f"ACE_SET_ENDLESS_SPOOL_MODE MODE={v}")
                want["mode"] = v
            else:
                raise AceError(400, tr("Unknown setting {key}", key=k))
        self._check()
        await self.moon.gcode("\n".join(cmds), source=tr("ACE card"))
        log.info("ACE settings: %s", "; ".join(cmds))
        await self._wait_for(want)
        return self.state()

    async def _set_rinkhals(self, changes: Dict[str, Any], confirm_printing: bool) -> Dict[str, Any]:
        body: Dict[str, int] = {}
        multiplier: Optional[float] = None
        for k, v in changes.items():
            if k in RINKHALS_OPTIONS:
                if not isinstance(v, bool):
                    raise AceError(400, tr("{key}: true or false", key=k))
                body[RINKHALS_OPTIONS[k]] = 1 if v else 0
            elif k == "flush_multiplier":
                try:
                    multiplier = round(float(v), 2)
                except (TypeError, ValueError):
                    raise AceError(400, tr("Give the multiplier as a number")) from None
                if not FLUSH_MIN <= multiplier <= FLUSH_MAX:
                    raise AceError(400, tr("Multiplier {min} to {max}", min=f"{FLUSH_MIN:g}", max=f"{FLUSH_MAX:g}"))
                if self.config and not self.config.get("flush_multiplier_editable", 1):
                    raise AceError(409, tr("The firmware does not allow changing the multiplier right now"))
            else:
                raise AceError(400, tr("Unknown setting {key}", key=k))
        self._check(confirm_printing)
        if body:
            await self.moon.post_json("/printer/filament_hub/set_config", body)
            log.info("ACE settings: %s", body)
        if multiplier is not None:
            await self.moon.gcode(f"SET_ACE_FLUSH_MULTIPLIER VALUE={multiplier:g}", source=tr("ACE card"))
            log.info("Purge multiplier set to %g%s", multiplier, " (during a print)" if self.slots.printing else "")
        await self.refresh(force=True)
        return self.state()

    async def _wait_for(self, want: Dict[str, Any]) -> None:
        """Until the driver reports the new state in the subscription (at most CONFIRM_WAIT_S)."""
        end = time.monotonic() + CONFIRM_WAIT_S
        while time.monotonic() < end:
            cur = acemodel.endless_spool(self.moon.status)
            if all(cur.get(k) == v for k, v in want.items()):
                return
            await asyncio.sleep(0.1)

    # ------------------------------------------------------------ purge preview (Rinkhals)
    def purge_preview(self, multiplier: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Purge for every change between the loaded spools - with the current or a wanted multiplier. Colours as the
        ACE reports them; grams with the filament's density. None under ACEPRO (Orca's matrix is the purge there)."""
        if not self.rinkhals:
            return None
        flush = dict(self.purge.flush)
        if multiplier is not None:
            flush["flush_multiplier"] = float(multiplier)
        assigned, _ = self.slots.assignments()
        gates: List[Dict[str, Any]] = []
        for gate in range(self.slots.num_gates()):
            ace = self.slots.ace_gate(gate)
            spool = assigned.get(gate + 1)
            color = ace.get("color") or ((spool or {}).get("filament") or {}).get("color_hex")
            if not color or not (ace.get("present") or spool):
                continue
            fil = (spool or {}).get("filament") or {}
            gates.append({"slot": gate + 1, "color": color, "density": fil.get("density") or 1.24,
                          "name": f"{(fil.get('vendor') or {}).get('name', '')} {fil.get('name') or ''}".strip()
                          or ace.get("material") or tr("Slot {slot}", slot=gate + 1)})
        pairs = []
        for a in gates:
            for b in gates:
                if a is b:
                    continue
                mm = change_mm(a["color"], b["color"], flush, self.purge.offset_mm)
                if mm is None:
                    continue
                pairs.append({"from_slot": a["slot"], "to_slot": b["slot"], "from_name": a["name"],
                              "to_name": b["name"], "from_color": a["color"], "to_color": b["color"],
                              "volume_mm3": int(firmware_volume(a["color"], b["color"], flush) or 0),
                              "mm": round(mm, 1), "g": round(mm * AREA_175 * b["density"] / 1000, 2)})
        return {"flush_multiplier": flush["flush_multiplier"], "first_load_mm": round(self.purge.first_load_mm, 1),
                "slots": gates, "pairs": pairs}
