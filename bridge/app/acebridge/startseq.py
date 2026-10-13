"""Pause and cancel during the print start sequence (Klipper module kobra_seq, kobra-klipper).

The start sequence (G9111) holds Klipper's G-code lock for up to half an hour - PAUSE and CANCEL_PRINT would wait until
it is done. kobra_seq runs it in steps and listens on the endpoint `kobra_seq/control` (Moonraker:
`printer.kobra_seq.control`), which bypasses that lock. While it is active, every pause/resume/cancel of the bridge
(web, app, display, AI, damp spool check, clog) goes there instead (Moonraker.action):

- pause: holds at the next safe point (before a step or while waiting for a temperature), lifts the nozzle
- resume: continues there
- cancel: heaters off at the next safe point, the print ends as cancelled

Long steps without a waiting point (tool change, PA measurement, bed mesh) finish first. Missing module, switched off
(`[kobra_seq] enable: False`) or Rinkhals: everything as before.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .i18n import tr

OBJ = "kobra_seq"
SUBSCRIBE = {OBJ: ["enabled", "active", "step", "index", "steps", "paused", "requested", "paused_since", "seq"]}
METHOD = "printer.kobra_seq.control"
# Moonraker methods of the normal print actions -> action of kobra_seq
ROUTED = {"printer.print.pause": "pause", "printer.print.resume": "resume", "printer.print.cancel": "cancel"}


def state(status: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Status of kobra_seq while a start sequence runs, else None."""
    s = status.get(OBJ) or {}
    if not s.get("enabled") or not s.get("active"):
        return None
    return s


def route(method: str, status: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Parameters for kobra_seq/control if this print action has to go there, else None."""
    if method in ROUTED and state(status) is not None:
        return {"action": ROUTED[method]}
    return None


def print_state(status: Dict[str, Any], state_now: Optional[str]) -> Optional[str]:
    """Print state for the UIs and the action check: a paused start sequence counts as paused (Klipper still reports
    printing - the start macro is running)."""
    s = state(status)
    if s is not None and state_now == "printing" and s.get("paused"):
        return "paused"
    return state_now


def view(status: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """For web/app/display: is a start sequence running, paused, pause/cancel waiting for the step to end."""
    s = state(status)
    if s is None:
        return None
    return {"paused": bool(s.get("paused")), "requested": s.get("requested") or None,
            "step": s.get("step") or None, "index": s.get("index"), "steps": s.get("steps"),
            "paused_since": s.get("paused_since")}


def note(status: Dict[str, Any]) -> Optional[str]:
    """Short text next to the print phase."""
    s = state(status)
    if s is None:
        return None
    if s.get("paused"):
        return tr("Start sequence paused")
    if s.get("requested") == "pause":
        return tr("pauses after this step")
    if s.get("requested") == "cancel":
        return tr("cancels after this step")
    return None
