"""Meldungen und Status fuer die Uebersicht (Weboberflaeche und App).

Alles hier wird aus dem gerechnet, was die Bridge ohnehin weiss (Moonraker-Abo, Spoolman, Druckdatei,
Geraete) - kein zusaetzlicher Abruf am Drucker. Meldungen sind nach Wichtigkeit sortiert:
error (rot) > warn (gelb) > info.
"""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional


if TYPE_CHECKING:
    from .__main__ import Bridge

LOW_SPOOL_G = 100           # darunter: "Spule fast leer" (Standard; einstellbar: cfg.low_spool_g)
REACH_RESERVE_PCT = 5.0     # Reserve bei "reicht die Spule?" (cfg.reach_reserve_pct)
RECENT_S = 30 * 60          # so lange bleiben "Druck fertig" / Trockner-Ereignisse als Info stehen
ONLINE_S = 5 * 60           # Geraet gilt als verbunden, wenn es sich so kurz vorher gemeldet hat
LEVELS = {"error": 0, "warn": 1, "info": 2}
# CPU des Klipper-Rechners (Pi), wie Moonraker sie meldet. Keine Meldung, nur die Statuszeile: haengt Klipper
# wirklich, meldet sich "Drucker nicht erreichbar" bzw. "Klipper nicht bereit".
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
# ACEPRO beim Laden eines Slots (ace_KS1.cfg): vom Kopf-Sensor bis zur Duese, danach Spuelen. Die Spuelmenge je
# Wechsel steht in der Datei (ACE_SET_PURGE_AMOUNT aus Orcas Filamentwechsel-G-Code), sonst die Voreinstellung des Treibers.
LOAD_TO_NOZZLE_MM = 85.0
DEFAULT_PURGE_MM = 50.0


def _slot_need(bridge: "Bridge", offset: Optional[int]) -> Dict[int, float]:
    """mm pro Slot ab der Byte-Position (0 = ganze Datei): Druckdatei + Laden und Spuelen der noch kommenden
    Farbwechsel. Werkzeug T<n> = Slot n (ACEPRO)."""
    rest_mm, later = bridge.preview.model.remaining(offset)
    need: Dict[int, float] = {}
    for tool, mm in rest_mm.items():
        if mm > 0:
            need[tool] = need.get(tool, 0.0) + mm
    for _src, dst, purge in later:
        mm = LOAD_TO_NOZZLE_MM + (purge if purge is not None else DEFAULT_PURGE_MM)
        need[dst] = need.get(dst, 0.0) + mm
    return need


def _spool_grams(bridge: "Bridge", spool: Optional[Dict[str, Any]], mm: float) -> float:
    fil = (spool or {}).get("filament") or {}
    return _grams(mm, float(fil.get("diameter") or bridge.cfg.default_diameter),
                  float(fil.get("density") or bridge.cfg.default_density))


def _model_ready(bridge: "Bridge") -> bool:
    st = bridge.moon.status
    if (st.get("print_stats") or {}).get("state") not in ("printing", "paused"):
        return False
    pv = bridge.preview
    return pv.status == "ready" and bool(pv.model)


def spool_reach(bridge: "Bridge") -> List[Dict[str, Any]]:
    """Pro Slot im laufenden Druck: noch benoetigt (Druckdatei ab aktueller Position + Spuelen der noch
    kommenden Farbwechsel) gegen den Rest auf der zugeordneten Spule."""
    if not _model_ready(bridge):
        return []
    pos = (bridge.moon.status.get("virtual_sdcard") or {}).get("file_position")
    need = _slot_need(bridge, pos)
    assigned, _ = bridge.slots.assignments()
    out = []
    for g, mm in sorted(need.items()):
        spool = assigned.get(g + 1)
        if not spool:
            out.append({"slot": g + 1, "need_mm": round(mm), "need_g": None, "have_g": None, "enough": None})
            continue
        have = spool.get("remaining_weight")
        need_g = _spool_grams(bridge, spool, mm)
        out.append({"slot": g + 1, "spool_id": spool.get("id"), "need_mm": round(mm), "need_g": round(need_g, 1),
                    "have_g": round(float(have), 1) if have is not None else None,
                    "enough": None if have is None else float(have) >= need_g * (1 + getattr(
                        bridge.cfg, "reach_reserve_pct", REACH_RESERVE_PCT) / 100)})
    return out


def file_usage(bridge: "Bridge") -> List[Dict[str, Any]]:
    """Welche Slots die laufende Druckdatei benutzt: gesamt und noch offen (mm/g, inkl. Spuelen) mit Spule und Farbe.
    Fuer die Zeile "benutzt" in Web und App."""
    if not _model_ready(bridge):
        return []
    pos = (bridge.moon.status.get("virtual_sdcard") or {}).get("file_position")
    total, rest = _slot_need(bridge, 0), _slot_need(bridge, pos)
    assigned, _ = bridge.slots.assignments()
    out = []
    for g, mm in sorted(total.items()):
        spool = assigned.get(g + 1)
        ace = bridge.slots.ace_gate(g)
        fil = (spool or {}).get("filament") or {}
        out.append({"slot": g + 1, "spool_id": (spool or {}).get("id"),
                    "name": fil.get("name") or ace.get("material") or None,
                    "material": fil.get("material") or ace.get("material") or None,
                    "color": (fil.get("color_hex") or ace.get("color") or "")[:6] or None,
                    "total_mm": round(mm), "total_g": round(_spool_grams(bridge, spool, mm), 1),
                    "rest_mm": round(rest.get(g, 0.0)), "rest_g": round(_spool_grams(bridge, spool, rest.get(g, 0.0)), 1)})
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
        if rem is not None and rem < getattr(bridge.cfg, "low_spool_g", LOW_SPOOL_G):
            out.append(_msg("warn", f"Slot {s['slot']}: {sp.get('display_name') or 'Spule'} fast leer "
                                    f"(noch {round(rem)} g)", f"low{s['slot']}"))

    for r in reach:
        if r["enough"] is False:
            out.append(_msg("warn", f"Slot {r['slot']} reicht wohl nicht für diesen Druck: braucht noch "
                                    f"~{round(r['need_g'])} g, auf der Spule {round(r['have_g'])} g", f"reach{r['slot']}"))
        elif r["enough"] is None and r.get("need_g") is None:
            out.append(_msg("warn", f"Slot {r['slot']} wird noch gebraucht, hat aber keine Spule zugeordnet",
                            f"reach{r['slot']}"))

    for ev in getattr(getattr(bridge, "pa", None), "events", []):
        if now - ev["at"] < RECENT_S:
            out.append(_msg(ev["level"], ev["text"], "pa"))

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
    checked = set()
    if getattr(bridge, "preview", None) is not None and getattr(bridge, "moisture", None) is not None:
        from .printcheck import check
        for issue in check(bridge):
            out.append(_msg(issue["level"], issue["text"], f"check{issue['slot']}{issue['kind']}"))
            if issue["kind"] == "wet":
                checked.add(issue["slot"])
    wet = getattr(bridge, "wet_loaded", None)
    if callable(wet):
        drying = bridge.dryer.state().get("drying")
        for slot, s, v, h in wet():
            if slot in checked:          # schon als Druckstart-Pruefung gemeldet (rot)
                continue
            f = s.get("filament") or {}
            name = f.get("name") or f"Spule #{s.get('id')}"
            if drying:
                out.append(_msg("info", f"Slot {slot}: {name} wird getrocknet", f"wet{slot}"))
            else:
                why = "neu, Verlauf unbekannt" if v["score"] is None else f"Feuchte-Schätzung {v['score']} %"
                out.append(_msg("warn", f"Slot {slot}: {name} wahrscheinlich feucht ({why}) – vor dem Druck ~{h:g} h trocknen",
                                f"wet{slot}"))
    vision = getattr(bridge, "vision", None)
    if vision is not None:
        out.extend(vision.messages())
    out.sort(key=lambda m: LEVELS[m["level"]])
    return out


# ====================================================================== CPU des Klipper-Rechners
def printer_cpu(bridge: "Bridge") -> Optional[float]:
    """CPU des Klipper-Rechners (Pi; Mittel der letzten 5 s) aus Moonrakers notify_proc_stat_update."""
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
        lines.append({"key": "cpu", "label": "Klipper-CPU (Pi)", "detail": f"{cpu:.0f} %",
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
        detail += f" · {cam['viewers']} Zuschauer" if cam.get("viewers") else ""
        lines.append({"key": "camera", "label": "Kamera", "state": "ok", "detail": detail})
    else:
        lines.append({"key": "camera", "label": "Kamera", "state": "ok", "detail": "bereit (nur wenn jemand schaut)"})
    vision = getattr(bridge, "vision", None)
    if vision is not None:
        lines.append(vision.status_line())
    mqtt = getattr(bridge, "mqtt", None)
    if mqtt is not None:
        lines.extend(mqtt.status_lines())
    for kind, label in (("app", "Handy-App"), ("plugin", "Orca-Plugin")):
        d = _device_status(bridge, kind, label, now)
        if d:
            lines.append(d)
    return lines


def notices(bridge: "Bridge", now: Optional[float] = None) -> Dict[str, Any]:
    now = time.time() if now is None else now
    reach = spool_reach(bridge)
    return {"messages": messages(bridge, reach, now), "status": status_lines(bridge, now), "reach": reach}
