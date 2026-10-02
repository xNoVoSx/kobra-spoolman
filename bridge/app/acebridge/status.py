"""Meldungen und Status fuer die Uebersicht (Weboberflaeche und App).

Alles hier wird aus dem gerechnet, was die Bridge ohnehin weiss (Moonraker-Abo, Spoolman, Druckdatei,
Geraete) - kein zusaetzlicher Abruf am Drucker. Meldungen sind nach Wichtigkeit sortiert:
error (rot) > warn (gelb) > info.
"""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .purge import change_mm

if TYPE_CHECKING:
    from .__main__ import Bridge

LOW_SPOOL_G = 100           # darunter: "Spule fast leer"
REACH_MARGIN = 1.05         # 5 % Reserve bei "reicht die Spule?"
RECENT_S = 30 * 60          # so lange bleiben "Druck fertig" / Trockner-Ereignisse als Info stehen
ONLINE_S = 5 * 60           # Geraet gilt als verbunden, wenn es sich so kurz vorher gemeldet hat
LEVELS = {"error": 0, "warn": 1, "info": 2}
# Im Druck liegt der S1 allein durch GoKlipper bei 75-89 % - erst darueber ist es auffaellig. Keine Meldung:
# daran laesst sich im Druck nichts aendern; haengt der Drucker wirklich, meldet sich "Drucker nicht erreichbar".
CPU_WARN = 90               # Status gelb ab
CPU_BAD = 97                # Status rot ab (wie CAMERA_CPU_HIGH)


def _msg(level: str, text: str, key: str) -> Dict[str, str]:
    return {"level": level, "text": text, "key": key}


def _grams(mm: float, diameter: float, density: float) -> float:
    return mm * math.pi * (diameter / 2) ** 2 * density / 1000.0


def _iso_age(iso: Optional[str], now: float) -> Optional[float]:
    if not iso:
        return None
    try:
        return now - time.mktime(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


# ====================================================================== Reicht die Spule?
def spool_reach(bridge: "Bridge") -> List[Dict[str, Any]]:
    """Pro Slot im laufenden Druck: noch benoetigt (Druckdatei ab aktueller Position + Spuelen der noch
    kommenden Farbwechsel) gegen den Rest auf der zugeordneten Spule."""
    st = bridge.moon.status
    if (st.get("print_stats") or {}).get("state") not in ("printing", "paused"):
        return []
    pv = bridge.preview
    if pv.status != "ready" or not pv.model:
        return []
    pos = (st.get("virtual_sdcard") or {}).get("file_position")
    rest_mm, later = pv.model.remaining(pos)
    mmu = st.get("mmu") or {}
    colors = [(c or "")[:6] or None for c in (mmu.get("gate_color") or [])]
    ttg = mmu.get("ttg_map") or list(range(len(colors)))

    def gate(tool: Optional[int]) -> Optional[int]:
        if tool is None:
            return None
        g = ttg[tool] if tool < len(ttg) else tool
        return g if isinstance(g, int) and g >= 0 else None

    need: Dict[int, float] = {}
    for tool, mm in rest_mm.items():
        g = gate(tool)
        if g is not None and mm > 0:
            need[g] = need.get(g, 0.0) + mm
    purge = bridge.purge
    for src, dst in later:
        g = gate(dst)
        if g is None:
            continue
        s = gate(src)
        if s is None:
            mm = purge.first_load_mm
        else:
            mm = change_mm(colors[s] if s < len(colors) else None, colors[g] if g < len(colors) else None,
                           purge.flush, purge.offset_mm) or 0.0
        need[g] = need.get(g, 0.0) + mm

    assigned, _ = bridge.slots.assignments()
    out = []
    for g, mm in sorted(need.items()):
        spool = assigned.get(g + 1)
        if not spool:
            out.append({"slot": g + 1, "need_mm": round(mm), "need_g": None, "have_g": None, "enough": None})
            continue
        fil = spool.get("filament") or {}
        d = float(fil.get("diameter") or bridge.cfg.default_diameter)
        rho = float(fil.get("density") or bridge.cfg.default_density)
        have = spool.get("remaining_weight")
        need_g = _grams(mm, d, rho)
        out.append({"slot": g + 1, "spool_id": spool.get("id"), "need_mm": round(mm), "need_g": round(need_g, 1),
                    "have_g": round(float(have), 1) if have is not None else None,
                    "enough": None if have is None else float(have) >= need_g * REACH_MARGIN})
    return out


# ====================================================================== Meldungen
def messages(bridge: "Bridge", reach: List[Dict[str, Any]], now: float) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    moon = bridge.moon
    ps = moon.status.get("print_stats") or {}
    state = ps.get("state")
    if not moon.connected:
        out.append(_msg("error", "Drucker nicht erreichbar (Moonraker)", "printer"))
    elif not moon.klippy_ready:
        out.append(_msg("error", "Klipper ist nicht bereit", "klippy"))
    elif state == "paused":
        out.append(_msg("error", "Druck pausiert" + (f": {ps['message']}" if ps.get("message") else ""), "paused"))
    elif state == "error":
        out.append(_msg("error", "Druckerfehler" + (f": {ps['message']}" if ps.get("message") else ""), "error"))

    for w in bridge.safety_warnings():
        out.append(_msg("error", w, "safety"))
    for w in bridge.slots.warnings:
        out.append(_msg("warn", w, "assign"))

    for s in bridge.slots.slots_view():
        for h in s["hints"]:
            level = "error" if "kein Material" in h else "warn" if ("meldet" in h or "weicht" in h) else "info"
            out.append(_msg(level, f"Slot {s['slot']}: {h}", f"hint{s['slot']}"))
        sp = s["spool"]
        rem = sp.get("remaining_weight") if sp else None
        if rem is not None and rem < LOW_SPOOL_G:
            out.append(_msg("warn", f"Slot {s['slot']}: {sp.get('display_name') or 'Spule'} fast leer "
                                    f"(noch {round(rem)} g)", f"low{s['slot']}"))

    for r in reach:
        if r["enough"] is False:
            out.append(_msg("warn", f"Slot {r['slot']} reicht wohl nicht für diesen Druck: braucht noch "
                                    f"~{round(r['need_g'])} g, auf der Spule {round(r['have_g'])} g", f"reach{r['slot']}"))
        elif r["enough"] is None and r.get("need_g") is None:
            out.append(_msg("warn", f"Slot {r['slot']} wird noch gebraucht, hat aber keine Spule zugeordnet",
                            f"reach{r['slot']}"))

    slots = bridge.slots
    for gate, nr in sorted(getattr(slots, "unknown_tags", {}).items()):
        out.append(_msg("warn", f"Slot {gate + 1}: unbekannter Tag {nr} – Spule zuordnen, die Nummer wird gemerkt",
                        f"tag{gate + 1}"))
    for ev in getattr(slots, "tag_events", []):
        if now - ev["at"] < RECENT_S and "unbekannter Tag" not in ev["text"]:
            out.append(_msg("info", ev["text"], "rfid"))

    n_open = len(bridge.usage.open or [])
    if n_open:
        out.append(_msg("warn", f"{n_open} Buchung{'en' if n_open > 1 else ''} noch nicht in Spoolman", "open"))
    if not bridge.sm.connected:
        out.append(_msg("warn", "Spoolman nicht erreichbar – Verbrauch wird gemerkt und nachgebucht", "spoolman"))

    dry = bridge.dryer.state()
    hum, cfg = dry.get("humidity"), dry.get("config") or {}
    # nur ohne Automatik: mit Automatik trocknet die Bridge selbst
    if (hum is not None and not cfg.get("enabled") and cfg.get("start_above") is not None
            and hum >= cfg["start_above"] and not dry.get("drying")):
        out.append(_msg("info", f"Feuchte im ACE {hum} % – Trocknen empfohlen", "humidity"))
    ev = dry.get("last_event") or {}
    age = _iso_age(ev.get("at"), now)
    if age is not None and age < RECENT_S:
        out.append(_msg("info", f"Trockner: {ev.get('text')}", "dryer"))

    last = bridge.usage.history[0] if bridge.usage.history else None
    age = _iso_age((last or {}).get("ended"), now)
    if last and age is not None and age < RECENT_S and state not in ("printing", "paused"):
        word = {"complete": "fertig", "cancelled": "abgebrochen", "error": "mit Fehler beendet"}.get(
            last.get("state"), "beendet")
        out.append(_msg("info", f"Druck {word}: {last.get('file')} (vor {round(age / 60)} min)", "done"))

    cam = bridge.camera.state()
    if cam.get("enabled") and cam.get("error"):
        out.append(_msg("info", cam["error"], "camera"))
    out.sort(key=lambda m: LEVELS[m["level"]])
    return out


# ====================================================================== Drucker-CPU
def printer_cpu(bridge: "Bridge") -> Optional[float]:
    """Drucker-CPU (Mittel der letzten 5 s) aus Moonrakers notify_proc_stat_update."""
    cpu = getattr(bridge.moon, "cpu", None)
    return cpu(5.0) if callable(cpu) else None


# ====================================================================== Status
def _device_status(bridge: "Bridge", kind: str, label: str, now: float) -> Optional[Dict[str, Any]]:
    devs = [d for d in bridge.devices.devices if d.get("kind") == kind]
    if not devs:
        return None
    d = max(devs, key=lambda x: x.get("last_seen") or 0)
    seen = d.get("last_seen") or 0
    return {"key": kind, "label": label, "state": "ok" if now - seen < ONLINE_S else "off",
            "detail": d.get("name"), "seen": seen}


def status_lines(bridge: "Bridge", now: float) -> List[Dict[str, Any]]:
    moon = bridge.moon
    lines: List[Dict[str, Any]] = []
    if not moon.connected:
        lines.append({"key": "printer", "label": "Drucker", "state": "bad", "detail": "nicht erreichbar"})
    elif not moon.klippy_ready:
        lines.append({"key": "printer", "label": "Drucker", "state": "warn", "detail": "Klipper nicht bereit"})
    else:
        lines.append({"key": "printer", "label": "Drucker", "state": "ok", "detail": "Moonraker verbunden"})
    cpu = printer_cpu(bridge)
    if cpu is not None:
        lines.append({"key": "cpu", "label": "Drucker-CPU", "detail": f"{cpu:.0f} %",
                      "state": "ok" if cpu < CPU_WARN else "warn" if cpu < CPU_BAD else "bad"})
    lines.append({"key": "spoolman", "label": "Spoolman", "state": "ok" if bridge.sm.connected else "bad",
                  "detail": "verbunden" if bridge.sm.connected else "nicht erreichbar"})
    cam = bridge.camera.state()
    if not cam.get("enabled"):
        lines.append({"key": "camera", "label": "Kamera", "state": "off", "detail": "abgeschaltet"})
    elif cam.get("error") and cam.get("mode") == "idle":
        lines.append({"key": "camera", "label": "Kamera", "state": "warn", "detail": cam["error"]})
    elif cam.get("mode") in ("stream", "snapshots"):
        detail = f"{cam['fps']:.0f} fps" if cam.get("fps") else "läuft"
        detail += " · gedrosselt (Drucker-CPU)" if cam.get("throttled") else ""
        detail += f" · {cam['viewers']} Zuschauer" if cam.get("viewers") else ""
        lines.append({"key": "camera", "label": "Kamera", "state": "warn" if cam.get("throttled") else "ok",
                      "detail": detail})
    else:
        lines.append({"key": "camera", "label": "Kamera", "state": "ok", "detail": "bereit (nur wenn jemand schaut)"})
    for kind, label in (("app", "Handy-App"), ("plugin", "Orca-Plugin")):
        d = _device_status(bridge, kind, label, now)
        if d:
            lines.append(d)
    return lines


def notices(bridge: "Bridge", now: Optional[float] = None) -> Dict[str, Any]:
    now = time.time() if now is None else now
    reach = spool_reach(bridge)
    return {"messages": messages(bridge, reach, now), "status": status_lines(bridge, now), "reach": reach}
