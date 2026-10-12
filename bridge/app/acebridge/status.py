"""Messages and status for the overview (web UI and app).

Everything here is computed from what the bridge knows anyway (Moonraker subscription, Spoolman, print file, devices)
- no extra request to the printer. Messages are sorted by importance: error (red) > warn (yellow) > info.
"""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .i18n import tr
from .slots import hint_level, is_unknown_tag_event

if TYPE_CHECKING:
    from .__main__ import Bridge

LOW_SPOOL_G = 100           # below: "spool almost empty" (default; adjustable: cfg.low_spool_g)
REACH_RESERVE_PCT = 5.0     # reserve for "is the spool enough?" (cfg.reach_reserve_pct)
RECENT_S = 30 * 60          # "print finished" / dryer events stay as info this long
ONLINE_S = 5 * 60           # a device counts as connected when it reported this recently
LEVELS = {"error": 0, "warn": 1, "info": 2}
# CPU of the Klipper computer, as Moonraker reports it. No message, only the status line: if Klipper really hangs,
# "printer not reachable" or "Klipper not ready" appears.
CPU_WARN = 90               # status yellow from
CPU_BAD = 97                # status red from


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


# ====================================================================== is the spool enough?
# ACEPRO when loading a slot (ace_KS1.cfg): from the head sensor to the nozzle, then purging. The purge length per
# change is in the file (ACE_SET_PURGE_AMOUNT from Orca's change-filament G-code), else the driver's default.
LOAD_TO_NOZZLE_MM = 85.0
DEFAULT_PURGE_MM = 50.0


def _slot_need(bridge: "Bridge", offset: Optional[int]) -> Dict[int, float]:
    """mm per slot from the byte position on (0 = whole file): print file + loading and purging of the colour changes
    still to come. Tool T<n> = slot n+1 (ACEPRO)."""
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
    """Per slot in the running print: still needed (print file from the current position + purging of the colour
    changes still to come) against the remainder on the assigned spool."""
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
    """Which slots the running print file uses: total and still open (mm/g, incl. purging) with spool and colour.
    For the "used" line in web and app."""
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


# ====================================================================== messages
def messages(bridge: "Bridge", reach: List[Dict[str, Any]], now: float) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    moon = bridge.moon
    ps = moon.status.get("print_stats") or {}
    state = ps.get("state")
    if not moon.connected:
        out.append(_msg("error", tr("Printer not reachable (Moonraker)"), "printer"))
    elif not moon.klippy_ready:
        out.append(_msg("error", tr("Klipper is not ready"), "klippy"))
    elif state == "paused":
        out.append(_msg("error", tr("Print paused: {why}", why=ps["message"]) if ps.get("message")
                        else tr("Print paused"), "paused"))
    elif state == "error":
        out.append(_msg("error", tr("Printer error: {why}", why=ps["message"]) if ps.get("message")
                        else tr("Printer error"), "error"))

    rs = getattr(bridge, "resume", None)
    if rs is not None and rs.message():
        out.append(_msg("error", rs.message(), "resume"))
    elif rs is not None and rs.error:
        out.append(_msg("error", tr("Resume cancelled: {error}", error=rs.error), "resume"))
    usb = getattr(bridge, "usb", None)
    if usb is not None and usb.message():
        out.append(_msg("error", usb.message(), "usb"))
    cl = getattr(bridge, "clog", None)
    if cl is not None and cl.message():
        out.append(_msg("error", cl.message(), "clog"))

    for w in bridge.safety_warnings():
        out.append(_msg("error", w, "safety"))
    for w in bridge.slots.warnings:
        out.append(_msg("warn", w, "assign"))

    for s in bridge.slots.slots_view():
        for h in s["hints"]:
            out.append(_msg(hint_level(h), tr("Slot {slot}: {hint}", slot=s["slot"], hint=h), f"hint{s['slot']}"))
        sp = s["spool"]
        rem = sp.get("remaining_weight") if sp else None
        if rem is not None and rem < getattr(bridge.cfg, "low_spool_g", LOW_SPOOL_G):
            out.append(_msg("warn", tr("Slot {slot}: {name} almost empty ({g} g left)", slot=s["slot"],
                                       name=sp.get("display_name") or tr("spool"), g=round(rem)), f"low{s['slot']}"))

    for r in reach:
        if r["enough"] is False:
            out.append(_msg("warn", tr("Slot {slot} is probably not enough for this print: needs ~{need} g more, "
                                       "{have} g on the spool", slot=r["slot"], need=round(r["need_g"]),
                                       have=round(r["have_g"])), f"reach{r['slot']}"))
        elif r["enough"] is None and r.get("need_g") is None:
            out.append(_msg("warn", tr("Slot {slot} is still needed but has no spool assigned", slot=r["slot"]),
                            f"reach{r['slot']}"))

    for ev in getattr(getattr(bridge, "pa", None), "events", []):
        if now - ev["at"] < RECENT_S:
            out.append(_msg(ev["level"], ev["text"], "pa"))

    slots = bridge.slots
    for gate, nr in sorted(getattr(slots, "unknown_tags", {}).items()):
        out.append(_msg("warn", tr("Slot {slot}: unknown tag {nr} – assign a spool, the number will be remembered",
                                   slot=gate + 1, nr=nr), f"tag{gate + 1}"))
    for ev in getattr(slots, "tag_events", []):
        if now - ev["at"] < RECENT_S and not is_unknown_tag_event(ev["text"]):
            out.append(_msg("info", ev["text"], "rfid"))

    n_open = len(bridge.usage.open or [])
    if n_open:
        out.append(_msg("warn", tr("{n} booking not in Spoolman yet", n=n_open) if n_open == 1
                        else tr("{n} bookings not in Spoolman yet", n=n_open), "open"))
    if not bridge.sm.connected:
        out.append(_msg("warn", tr("Spoolman not reachable – consumption is kept and booked later"), "spoolman"))

    dry = bridge.dryer.state()
    hum, cfg = dry.get("humidity"), dry.get("config") or {}
    # only without automation: with automation the bridge dries by itself
    if (hum is not None and not cfg.get("enabled") and cfg.get("start_above") is not None
            and hum >= cfg["start_above"] and not dry.get("drying")):
        out.append(_msg("info", tr("Humidity in the ACE {rh} % – drying recommended", rh=hum), "humidity"))
    ev = dry.get("last_event") or {}
    age = _iso_age(ev.get("at"), now)
    if age is not None and age < RECENT_S:
        out.append(_msg("info", tr("Dryer: {text}", text=ev.get("text")), "dryer"))

    last = bridge.usage.history[0] if bridge.usage.history else None
    age = _iso_age((last or {}).get("ended"), now)
    if last and age is not None and age < RECENT_S and state not in ("printing", "paused"):
        text = {"complete": tr("Print finished: {file} ({min} min ago)", file=last.get("file"), min=round(age / 60)),
                "cancelled": tr("Print cancelled: {file} ({min} min ago)", file=last.get("file"), min=round(age / 60)),
                "error": tr("Print ended with an error: {file} ({min} min ago)", file=last.get("file"),
                            min=round(age / 60))}.get(last.get("state"))
        out.append(_msg("info", text or tr("Print ended: {file} ({min} min ago)", file=last.get("file"),
                                           min=round(age / 60)), "done"))

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
            if slot in checked:          # already reported by the print start check (red)
                continue
            f = s.get("filament") or {}
            name = f.get("name") or tr("Spool #{id}", id=s.get("id"))
            if drying:
                out.append(_msg("info", tr("Slot {slot}: {name} is being dried", slot=slot, name=name), f"wet{slot}"))
            else:
                why = (tr("new, history unknown") if v["score"] is None
                       else tr("moisture estimate {score} %", score=v["score"]))
                out.append(_msg("warn", tr("Slot {slot}: {name} probably damp ({why}) – dry ~{h:g} h before printing",
                                           slot=slot, name=name, why=why, h=float(h)), f"wet{slot}"))
    vision = getattr(bridge, "vision", None)
    if vision is not None:
        out.extend(vision.messages())
    out.sort(key=lambda m: LEVELS[m["level"]])
    return out


# ====================================================================== CPU of the Klipper computer
def printer_cpu(bridge: "Bridge") -> Optional[float]:
    """CPU of the Klipper computer (mean of the last 5 s) from Moonraker's notify_proc_stat_update."""
    cpu = getattr(bridge.moon, "cpu", None)
    return cpu(5.0) if callable(cpu) else None


# ====================================================================== status
def _device_status(bridge: "Bridge", kind: str, label: Any, now: float) -> Optional[Dict[str, Any]]:
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
    printer = tr("Printer")
    if not moon.connected:
        lines.append({"key": "printer", "label": printer, "state": "bad", "detail": tr("not reachable")})
    elif not moon.klippy_ready:
        lines.append({"key": "printer", "label": printer, "state": "warn", "detail": tr("Klipper not ready")})
    else:
        lines.append({"key": "printer", "label": printer, "state": "ok", "detail": tr("Moonraker connected")})
    usb = getattr(bridge, "usb", None)
    if usb is not None and usb.available():
        lines.append({"key": "usb", "label": tr("USB tunnel"), **usb.summary()})
    cpu = printer_cpu(bridge)
    if cpu is not None:
        lines.append({"key": "cpu", "label": tr("Klipper CPU"), "detail": f"{cpu:.0f} %",
                      "state": "ok" if cpu < CPU_WARN else "warn" if cpu < CPU_BAD else "bad"})
    lines.append({"key": "spoolman", "label": "Spoolman", "state": "ok" if bridge.sm.connected else "bad",
                  "detail": tr("connected") if bridge.sm.connected else tr("not reachable")})
    cam = bridge.camera.state()
    camera = tr("Camera")
    if not cam.get("enabled"):
        lines.append({"key": "camera", "label": camera, "state": "off", "detail": tr("switched off")})
    elif cam.get("error") and cam.get("mode") == "idle":
        lines.append({"key": "camera", "label": camera, "state": "warn", "detail": cam["error"]})
    elif cam.get("mode") in ("stream", "snapshots"):
        fps = f"{cam['fps']:.0f} fps" if cam.get("fps") else tr("running")
        detail = tr("{fps} · {n} viewers", fps=fps, n=cam["viewers"]) if cam.get("viewers") else fps
        lines.append({"key": "camera", "label": camera, "state": "ok", "detail": detail})
    else:
        lines.append({"key": "camera", "label": camera, "state": "ok", "detail": tr("ready (only while someone watches)")})
    vision = getattr(bridge, "vision", None)
    if vision is not None:
        lines.append(vision.status_line())
    mqtt = getattr(bridge, "mqtt", None)
    if mqtt is not None:
        lines.extend(mqtt.status_lines())
    for kind, label in (("app", tr("Phone app")), ("plugin", tr("Orca plugin"))):
        d = _device_status(bridge, kind, label, now)
        if d:
            lines.append(d)
    return lines


def notices(bridge: "Bridge", now: Optional[float] = None) -> Dict[str, Any]:
    now = time.time() if now is None else now
    reach = spool_reach(bridge)
    return {"messages": messages(bridge, reach, now), "status": status_lines(bridge, now), "reach": reach}
