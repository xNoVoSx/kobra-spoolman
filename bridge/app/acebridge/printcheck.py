"""Check at print start: do the slots match the print file?

As soon as the bridge has read the print file (render.py), it compares, for every tool the file really uses, the slot
(ACEPRO: tool T<n> = slot n+1, Rinkhals: the ACE's ttg_map): spool assigned? material as in the slicer? colour roughly the same? spool not too
damp (moisture.py)? Whether the remaining amount is enough, status.spool_reach checks anyway.

The result is messages (red = alarm on the phone). With wet_print_action = pause the bridge pauses a print that starts
with a damp spool - once per print, only in the first minutes.

Direct feed (direct.py): the ACE is passed by - the file is compared with the direct spool instead of the slots. A file
that uses more than one tool cannot print that way: alarm, and the bridge pauses it at once (Klipper would pause at
the first colour change anyway - this catches it at the start).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from . import acemodel
from .i18n import tr
from .slots import base_type

if TYPE_CHECKING:
    from .__main__ import Bridge

log = logging.getLogger("printcheck")

COLOUR_LIMIT = 140          # RGB distance from which the colour is "clearly different"
PAUSE_WINDOW_S = 10 * 60    # pause for a damp spool only this soon after the start


def _rgb(h: Optional[str]):
    h = (h or "").lstrip("#")[:6]
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) == 6 else None
    except ValueError:
        return None


def colour_distance(a: Optional[str], b: Optional[str]) -> Optional[float]:
    ra, rb = _rgb(a), _rgb(b)
    if not ra or not rb:
        return None
    return sum((x - y) ** 2 for x, y in zip(ra, rb, strict=True)) ** 0.5


def check(bridge: "Bridge") -> List[Dict[str, Any]]:
    """Problems of the running print: [{slot, tool, kind, level, text}]. Empty while the file is not read."""
    ps = bridge.moon.status.get("print_stats") or {}
    if ps.get("state") not in ("printing", "paused"):
        return []
    pv = bridge.preview
    m = pv.model
    if not m or pv.status != "ready" or not len(m):
        return []
    assigned, _ = bridge.slots.assignments()
    out: List[Dict[str, Any]] = []
    tools = sorted(t for t, mm in m.e_total.items() if mm > 1)
    direct = getattr(bridge, "direct", None)
    if direct is not None and direct.active:
        return _check_direct(bridge, m, tools)
    for tool in tools:
        gate = acemodel.tool_slot(bridge.moon.status, tool)   # ACEPRO: T<n> = slot n+1; Rinkhals: its ttg_map
        slot = gate + 1
        ace = bridge.slots.ace_gate(gate)
        spool = assigned.get(slot)
        want_type = base_type(m.types[tool]).upper() if tool < len(m.types) and m.types[tool] else ""
        want_col = m.colours[tool] if tool < len(m.colours) else None
        tag = tr("T{tool} → slot {slot}", tool=tool, slot=slot)
        if not ace["present"] and not spool:
            out.append({"slot": slot, "tool": tool, "kind": "empty", "level": "error",
                        "text": tr("Print start check: {tag} is needed, the slot is empty", tag=tag)})
            continue
        fil = (spool or {}).get("filament") or {}
        have_type = base_type(fil.get("material") or ace["material"] or "").upper()
        if want_type and have_type and want_type != have_type:
            out.append({"slot": slot, "tool": tool, "kind": "material", "level": "error",
                        "text": tr("Print start check: {tag} – the file wants {want}, loaded is {have}", tag=tag,
                                   want=want_type, have=have_type)})
        dist = colour_distance(want_col, ace["color"] or fil.get("color_hex"))
        if dist is not None and dist > COLOUR_LIMIT:
            out.append({"slot": slot, "tool": tool, "kind": "colour", "level": "warn",
                        "text": tr("Print start check: {tag} – colour differs from the slicer (#{want} instead of "
                                   "#{have})", tag=tag, want=want_col,
                                   have=(ace["color"] or fil.get("color_hex") or "")[:6])})
        if not spool:
            out.append({"slot": slot, "tool": tool, "kind": "nospool", "level": "warn",
                        "text": tr("Print start check: {tag} has no spool assigned – the consumption goes to the "
                                   "open bookings", tag=tag)})
            continue
        mv = bridge.moisture.view(spool)
        if mv["needs_drying"]:
            why = (tr("new, history unknown") if mv["score"] is None
                   else tr("moisture estimate {score} %", score=mv["score"]))
            out.append({"slot": slot, "tool": tool, "kind": "wet", "level": "error",
                        "text": tr("Print start check: {tag} – {name} probably damp ({why}), dry ~{h:g} h first",
                                   tag=tag, name=fil.get("name") or tr("spool"), why=why,
                                   h=float(mv["hours_needed"]))})
    return out


def _check_direct(bridge: "Bridge", m: Any, tools: List[int]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if len(tools) > 1:
        out.append({"slot": None, "tool": None, "kind": "direct_multi", "level": "error",
                    "text": tr("Print start check: direct feed is on, but the file uses {n} filaments – multi-colour "
                               "only works through the ACE. The print is paused – cancel it.", n=len(tools))})
    spool = bridge.direct.spool()
    fil = (spool or {}).get("filament") or {}
    for tool in tools[:1]:
        want_type = base_type(m.types[tool]).upper() if tool < len(m.types) and m.types[tool] else ""
        have_type = base_type(fil.get("material") or "").upper()
        if want_type and have_type and want_type != have_type:
            out.append({"slot": None, "tool": tool, "kind": "material", "level": "error",
                        "text": tr("Print start check: direct feed – the file wants {want}, the direct spool is {have}",
                                   want=want_type, have=have_type)})
        if spool:
            mv = bridge.moisture.view(spool)
            if mv["needs_drying"]:
                why = (tr("new, history unknown") if mv["score"] is None
                       else tr("moisture estimate {score} %", score=mv["score"]))
                out.append({"slot": None, "tool": tool, "kind": "wet", "level": "error",
                            "text": tr("Print start check: direct feed – {name} probably damp ({why}), dry ~{h:g} h "
                                       "first", name=fil.get("name") or tr("spool"), why=why,
                                       h=float(mv["hours_needed"]))})
    return out


class PrintGuard:
    """Pauses once per print: a damp spool is needed and wet_print_action = pause, or direct feed with a multi-colour
    file."""

    def __init__(self, bridge: "Bridge", clock=time.time):
        self.bridge = bridge
        self.clock = clock
        self.acted_job: Optional[str] = None
        self.started_at: Optional[float] = None
        self._state = ""

    async def tick(self) -> None:
        b = self.bridge
        ps = b.moon.status.get("print_stats") or {}
        st = ps.get("state") or ""
        if st != self._state:
            if st == "printing" and self._state not in ("printing", "paused"):
                self.started_at = self.clock()
            self._state = st
        if st != "printing" or self.started_at is None:
            return
        job = f"{ps.get('filename')}:{self.started_at}"
        if job == self.acted_job or self.clock() - self.started_at > PAUSE_WINDOW_S:
            return
        problems = check(b)
        multi = [i for i in problems if i["kind"] == "direct_multi"]
        wet = [i for i in problems if i["kind"] == "wet"]
        if multi:
            why, items = tr("PAUSE (direct feed, several filaments)"), multi
        elif wet and b.cfg.wet_print_action == "pause":
            why, items = tr("PAUSE (damp spool)"), wet
        else:
            return
        self.acted_job = job
        try:
            await b.moon.action("printer.print.pause", why, source=tr("Print start check"))
            log.warning("Print paused: %s", "; ".join(i["text"] for i in items))
        except Exception as e:  # noqa: BLE001
            log.error("Pause at the print start check failed: %s", e)
