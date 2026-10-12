"""Diagnostics for a bug report: everything someone needs to reproduce a problem, in one Markdown text.

`GET /api/diagnostics` (paired devices only) - the web UI copies it for the bug report form on GitHub. Contents:
versions (bridge, Python, Klipper, Moonraker, Spoolman), the firmware setup (Rinkhals or Klipper + ACEPRO), connection
state, slots, settings, warnings and the last log lines.

Nothing private leaves the bridge: secrets (tokens, passwords, API keys) only show as "set", host names and IP
addresses become `<host>`, e-mail addresses `<email>`. The text is meant to be pasted into a public issue.
"""

from __future__ import annotations

import logging
import platform
import re
import time
from dataclasses import fields
from typing import TYPE_CHECKING, Any, Dict, List

from . import __version__, acemodel
from .console import LOG_BUFFER

if TYPE_CHECKING:
    from .__main__ import Bridge

log = logging.getLogger("diagnostics")

SECRET = re.compile(r"(token|password|api_key|secret)", re.I)
LOG_LINES = 60          # last log lines of any level
LOG_PROBLEMS = 30       # last warnings/errors (they may be older than the last LOG_LINES)

_URL_HOST = re.compile(r"\b([a-z][a-z0-9+.-]*://)(?:[^/\s:@]+@)?([^/\s:?#]+)", re.I)
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_BEARER = re.compile(r"(Bearer\s+)\S+", re.I)
_KEYLIKE = re.compile(r"\b[A-Za-z0-9_-]{24,}\b")


def _keylike(m: re.Match) -> str:
    """Hex keys and random tokens (letters and digits mixed), not long file names with words."""
    w = m.group(0)
    hexkey = len(w) >= 32 and all(c in "0123456789abcdefABCDEF" for c in w)
    random = (any(c.isdigit() for c in w) and any(c.islower() for c in w) and any(c.isupper() for c in w)
              and sum(c.isdigit() for c in w) >= 3)
    return "<key>" if hexkey or random else w


def redact(text: str) -> str:
    """Remove what does not belong in a public issue: hosts, IP addresses, e-mail addresses, keys."""
    text = _URL_HOST.sub(lambda m: m.group(1) + "<host>", str(text))
    text = _EMAIL.sub("<email>", text)
    text = _IPV4.sub("<host>", text)
    text = _BEARER.sub(r"\1<key>", text)
    return _KEYLIKE.sub(_keylike, text)


def settings(cfg: Any) -> Dict[str, Any]:
    """All settings; secrets only as set/not set, addresses without the host."""
    out: Dict[str, Any] = {}
    for f in fields(cfg):
        value = getattr(cfg, f.name)
        if SECRET.search(f.name):
            out[f.name] = "set" if value else "not set"
        elif isinstance(value, str):
            out[f.name] = redact(value)
        else:
            out[f.name] = value
    return out


async def _moonraker(bridge: "Bridge") -> List[str]:
    lines = [f"- connected: {bridge.moon.connected}, klippy ready: {bridge.moon.klippy_ready}, "
             f"setup: {bridge.moon.platform} (ACE driver: {acemodel.variant(bridge.moon.status) or 'not found'})"]
    for path, keys in (("/server/info", ("moonraker_version", "api_version_string", "klippy_state")),
                       ("/printer/info", ("software_version", "app", "state"))):
        try:
            info = await bridge.moon.get_json(path, timeout=5) or {}
            lines.append(f"- {path}: " + ", ".join(f"{k}={info.get(k)}" for k in keys if info.get(k) is not None))
        except Exception as e:  # noqa: BLE001
            lines.append(f"- {path}: unavailable ({type(e).__name__})")
    lines.append(f"- components: {', '.join(sorted(bridge.moon.components)) or '-'}")
    try:
        vi = (await bridge.moon.get_json("/machine/update/status", timeout=5) or {}).get("version_info") or {}
        versions = [f"{k} {v.get('version')}" for k, v in sorted(vi.items())
                    if isinstance(v, dict) and v.get("version")]
        if versions:
            lines.append(f"- installed (update manager): {', '.join(versions)}")
    except Exception:  # noqa: BLE001 - Rinkhals' Moonraker has no update manager
        pass
    ace_objects = sorted(k for k in (bridge.moon.status or {})
                         if k.split()[0] in ("ace", "ace_instance_0", "mmu", "filament_hub")
                         or k.startswith(("kobra_", "filament_tracker")))
    lines.append(f"- ACE/kobra objects: {', '.join(ace_objects) or '-'}")
    return lines


def _slots(bridge: "Bridge") -> List[str]:
    lines = []
    try:
        for s in bridge.slots.slots_view():
            ace = s.get("ace") or {}
            spool = s.get("spool") or {}
            parts = [f"ACE: {'present' if ace.get('present') else 'empty'} {ace.get('material') or '-'} "
                     f"#{ace.get('color') or '-'}"]
            if spool:
                parts.append(f"spool {spool.get('spool_id')} ({spool.get('remaining_weight') or 0:.0f} g left): {spool.get('material') or '-'} #{spool.get('color') or '-'}"
                             + (" (tag)" if s.get("by_tag") else ""))
            if s.get("hints"):
                parts.append("hints: " + "; ".join(s["hints"]))
            lines.append(f"- slot {s['slot']}: " + " | ".join(parts))
    except Exception as e:  # noqa: BLE001
        lines.append(f"- unavailable ({type(e).__name__}: {e})")
    return lines


def _line(r: Dict[str, Any]) -> str:
    return (f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r['time']))} {r['level']:<7} {r['name']:<10} "
            f"{redact(r['text'])}")


def _log() -> List[str]:
    recent = LOG_BUFFER.since(0, "DEBUG", LOG_LINES)
    first = recent[0]["id"] if recent else 0
    older = [r for r in LOG_BUFFER.since(0, "WARNING", LOG_PROBLEMS) if r["id"] < first]
    out = []
    if older:
        out += ["# earlier warnings/errors", *map(_line, older), "# last lines"]
    return out + list(map(_line, recent))


async def report(bridge: "Bridge", started: float) -> str:
    cfg = bridge.cfg
    sm = bridge.sm
    lines = [
        f"### Diagnostics – ace-lane-bridge {__version__}",
        "",
        f"- created: {time.strftime('%Y-%m-%d %H:%M:%S %z')}, uptime {int(time.time() - started)} s",
        f"- Python {platform.python_version()} on {platform.system()} {platform.machine()}, "
        f"UI language {cfg.language}, dry run: {cfg.dry_run}",
        f"- print state: {bridge.slots.print_state}, booking: {cfg.book_usage and not cfg.dry_run}, "
        f"open items: {len(bridge.usage.open)}",
        "",
        "**Printer (Moonraker)**",
        *await _moonraker(bridge),
        "",
        "**Spoolman**",
        f"- connected: {sm.connected}, version: {sm.version}, spools: {len(sm.spools)}, "
        f"filaments: {len(sm.filaments)}",
        "",
        "**Slots**",
        *_slots(bridge),
        "",
        "**Warnings**",
        *([f"- {redact(w if isinstance(w, str) else w.get('text') or w)}"
           for w in bridge.safety_warnings() + bridge.slots.warnings] or ["- none"]),
        "",
        "<details><summary>Settings</summary>",
        "",
        "```",
        *(f"{k} = {v}" for k, v in settings(cfg).items()),
        "```",
        "</details>",
        "",
        "<details><summary>Bridge log</summary>",
        "",
        "```",
        *_log(),
        "```",
        "</details>",
    ]
    return "\n".join(lines) + "\n"
