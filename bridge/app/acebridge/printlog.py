"""Print log: readable version of a print recording (telemetry.py, JSONL).

Time, console messages (start sequence, ACE changes, auto PA, resume ...) and the important state changes: print
state, tool/ACE, target temperatures, layer, auto PA, clog, resume, Klipper state. The raw data stays in the .jsonl
(debugging, recalculating); this is meant for reading (Logs -> print recordings). Rendered in the language of the
request.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .i18n import tr

# (object, field, label) - only changes of these fields appear in the log
WATCH: List[Tuple[str, str, str]] = [
    ("print_stats", "state", tr("Print state")),
    ("webhooks", "state", tr("Klipper")),
    ("ace", "current_index", tr("loaded T")),
    ("ace", "target_index", tr("change to T")),
    ("extruder", "target", tr("Nozzle target")),
    ("heater_bed", "target", tr("Bed target")),
    ("kobra_pa", "measuring", tr("Auto PA measuring")),
    ("kobra_pa", "result", tr("Auto PA result")),
    ("kobra_clog", "suspect", tr("Clog suspected")),
    ("kobra_clog", "alarm", tr("Clog alarm")),
    ("kobra_resume", "result", tr("Resume result")),
    ("gcode_move", "speed_factor", tr("Speed")),
    ("gcode_move", "extrude_factor", tr("Flow")),
    ("bed_mesh", "profile_name", tr("Bed mesh")),
]


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))[:300]
    return str(v)


def _clock(at: Optional[float], t: float) -> str:
    if at is None:
        return f"+{t:8.1f}s"
    return time.strftime("%H:%M:%S", time.localtime(at + t))


def render(lines: Iterable[str]) -> str:
    """JSONL lines of a recording -> text."""
    out: List[str] = []
    at: Optional[float] = None
    last: Dict[Tuple[str, str], Any] = {}
    for raw in lines:
        try:
            rec = json.loads(raw)
        except (TypeError, ValueError):
            continue
        kind = rec.get("type")
        t = float(rec.get("t") or 0)
        if kind == "start":
            at = rec.get("at")
            st = rec.get("status") or {}
            ps = st.get("print_stats") or {}
            out.append(tr("Print log: {file}", file=ps.get("filename") or "?").render())
            if at:
                out.append(tr("Start: {at}", at=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(at))).render())
            inst = st.get("ace_instance_0") or {}
            for i, sl in enumerate(inst.get("slots") or []):
                if isinstance(sl, dict):
                    out.append(f"  Slot {i + 1}: {sl.get('material') or '-'} {sl.get('color') or ''} "
                               f"{sl.get('temp') or ''}°C {sl.get('status') or ''}".rstrip())
            for (obj, field, _label) in WATCH:
                v = (st.get(obj) or {}).get(field)
                if v is not None:
                    last[(obj, field)] = v
            out.append("")
        elif kind == "delta":
            d = rec.get("d") or {}
            for (obj, field, label) in WATCH:
                if field in (d.get(obj) or {}):
                    v = d[obj][field]
                    if last.get((obj, field)) != v:
                        last[(obj, field)] = v
                        out.append(f"{_clock(at, t)}  ◆ {label.render()}: {_fmt(v)}")
            info = (d.get("print_stats") or {}).get("info") or {}
            if isinstance(info, dict) and info.get("current_layer") is not None:
                if last.get(("layer", "")) != info["current_layer"]:
                    last[("layer", "")] = info["current_layer"]
                    layer = (f"{info['current_layer']}/{info['total_layer']}" if info.get("total_layer")
                             else str(info["current_layer"]))
                    out.append(f"{_clock(at, t)}  ◆ " + tr("Layer {layer}", layer=layer).render())
        elif kind == "console":
            prefix = {"command": "> ", "error": "!! "}.get(rec.get("kind"), "  ")
            src = f" [{rec['source']}]" if rec.get("source") and rec.get("kind") == "command" else ""
            out.append(f"{_clock(at, t)}  {prefix}{(rec.get('text') or '').replace(chr(10), ' | ')}{src}")
        elif kind == "summary":
            out.append("")
            out.append(tr("End: {state} after {min} min", state=rec.get("end_state"),
                          min=round((rec.get("duration_s") or 0) / 60, 1)).render())
            for g in rec.get("gate_changes") or []:
                out.append("  " + tr("Change at +{t}s: slot {a} -> {b}", t=g.get("t"), a=g.get("from"),
                                     b=g.get("to")).render())
    return "\n".join(out) + "\n"
