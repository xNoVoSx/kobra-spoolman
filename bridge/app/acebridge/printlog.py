"""Druckprotokoll: lesbare Fassung einer Druck-Aufzeichnung (telemetry.py, JSONL).

Uhrzeit, Konsolenmeldungen (Start-Ablauf, ACE-Wechsel, Auto-PA, Fortsetzen ...) und die wichtigen Zustandswechsel:
Druckstatus, Werkzeug/ACE, Soll-Temperaturen, Schicht, Auto-PA, Verstopfung, Fortsetzen, Klipper-Zustand. Die Rohdaten
bleiben in der .jsonl (Fehlersuche, Nachrechnen); das hier ist zum Lesen gedacht (Logs -> Druck-Aufzeichnungen).
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

# (Objekt, Feld, Beschriftung) - nur Wechsel dieser Felder erscheinen im Protokoll
WATCH: List[Tuple[str, str, str]] = [
    ("print_stats", "state", "Druckstatus"),
    ("webhooks", "state", "Klipper"),
    ("ace", "current_index", "geladen T"),
    ("ace", "target_index", "Wechsel nach T"),
    ("extruder", "target", "Düse Soll"),
    ("heater_bed", "target", "Bett Soll"),
    ("kobra_pa", "measuring", "Auto-PA misst"),
    ("kobra_pa", "result", "Auto-PA Ergebnis"),
    ("kobra_clog", "suspect", "Verstopfung Verdacht"),
    ("kobra_clog", "alarm", "Verstopfung Alarm"),
    ("kobra_resume", "result", "Fortsetzen Ergebnis"),
    ("gcode_move", "speed_factor", "Tempo"),
    ("gcode_move", "extrude_factor", "Fluss"),
    ("bed_mesh", "profile_name", "Bettnetz"),
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
    """JSONL-Zeilen einer Aufzeichnung -> Text."""
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
            out.append(f"Druckprotokoll: {ps.get('filename') or '?'}")
            if at:
                out.append("Beginn: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(at)))
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
                        out.append(f"{_clock(at, t)}  ◆ {label}: {_fmt(v)}")
            info = (d.get("print_stats") or {}).get("info") or {}
            if isinstance(info, dict) and info.get("current_layer") is not None:
                if last.get(("layer", "")) != info["current_layer"]:
                    last[("layer", "")] = info["current_layer"]
                    out.append(f"{_clock(at, t)}  ◆ Schicht {info['current_layer']}"
                               f"{'/' + str(info['total_layer']) if info.get('total_layer') else ''}")
        elif kind == "console":
            prefix = {"command": "> ", "error": "!! "}.get(rec.get("kind"), "  ")
            src = f" [{rec['source']}]" if rec.get("source") and rec.get("kind") == "command" else ""
            out.append(f"{_clock(at, t)}  {prefix}{(rec.get('text') or '').replace(chr(10), ' | ')}{src}")
        elif kind == "summary":
            out.append("")
            out.append(f"Ende: {rec.get('end_state')} nach {round((rec.get('duration_s') or 0) / 60, 1)} min")
            for g in rec.get("gate_changes") or []:
                out.append(f"  Wechsel bei +{g.get('t')}s: Slot {g.get('from')} -> {g.get('to')}")
    return "\n".join(out) + "\n"
