"""USB tunnel between printer and Klipper computer: state of the watchdog and its switches.

The Klipper computer (Pi) is connected to the printer as a USB gadget. After the printer is switched off and on, the
enumeration there sometimes fails; a watchdog service on the Pi (kobra-klipper: pi/usb/kobra-usb-watch.py) then
reconnects by itself and reloads Klipper. It keeps its state in Moonraker's database (namespace `kobra_usb`, key
`state`) and reads its switches there (`switches`: watch, auto_restart, full_speed) - they take precedence over its
config file.

The bridge reads the state every 30 s (one small request to the Pi, nothing on the printer), shows it as a status line
and a message, and switches it through the same switch list as the Klipper modules (switches.py). Without the watchdog
nothing of this is shown.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .i18n import tr

if TYPE_CHECKING:
    from .moonraker import Moonraker

log = logging.getLogger("usb")

NS = "kobra_usb"
POLL_S = 30.0
STALE_S = 180.0          # heartbeat every 60 s - older: the watchdog is not running
SWITCHES = [
    ("usb_watch", "watch", tr("Reconnect USB automatically"),
     tr("Printer on but not connected → the Pi reconnects itself")),
    ("usb_auto_restart", "auto_restart", tr("Reload Klipper afterwards"),
     tr("When Klipper lost the boards (never during a print)")),
    ("usb_full_speed", "full_speed", tr("Slow, robust USB"),
     tr("12 Mbit/s – only if the connection often fails despite the watchdog")),
]


class UsbError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


class UsbTunnel:
    def __init__(self, moon: "Moonraker", clock=time.time, mono=time.monotonic):
        self.moon = moon
        self.clock = clock
        self.mono = mono
        self.state: Optional[Dict[str, Any]] = None
        self.read_at: Optional[float] = None

    async def tick(self, force: bool = False) -> None:
        if not self.moon.connected:
            return
        if getattr(self.moon, "platform", "klipper") == "rinkhals":
            self.state = None            # no USB tunnel on the stock firmware: nothing to show
            return
        now = self.mono()
        if not force and self.read_at is not None and now - self.read_at < POLL_S:
            return
        self.read_at = now
        try:
            val = await self.moon.db_get(NS, "state")
        except Exception as e:  # noqa: BLE001 - Moonraker briefly gone: next time
            log.debug("Reading the USB watchdog: %s", e)
            return
        self.state = val if isinstance(val, dict) else None

    # ------------------------------------------------------------ view
    def available(self) -> bool:
        return self.state is not None

    def alive(self) -> bool:
        at = (self.state or {}).get("at")
        return isinstance(at, (int, float)) and self.clock() - at < STALE_S

    def summary(self) -> Dict[str, str]:
        """{"state": ok|warn|bad|off, "detail": text} for the status line and the display."""
        st = self.state or {}
        if not self.alive():
            return {"state": "warn", "detail": tr("Watchdog not reporting (service kobra-usb-watch?)")}
        if st.get("state") == "configured":
            if st.get("max_speed") == "full-speed":
                return {"state": "ok", "detail": tr("connected · 12 Mbit/s")}
            return {"state": "ok", "detail": tr("connected")}
        if not st.get("present"):
            return {"state": "off", "detail": tr("Printer off")}
        if st.get("gave_up"):
            return {"state": "bad", "detail": tr("no connection after {tries} attempts – check the cable",
                                                 tries=st.get("tries"))}
        if st.get("tries"):
            return {"state": "warn", "detail": tr("connecting … attempt {tries}/{max}", tries=st["tries"],
                                                  max=st.get("max_tries"))}
        return {"state": "warn", "detail": tr("Printer on, waiting for the connection")}

    def view(self) -> Dict[str, Any]:
        st = self.state or {}
        return {"available": self.available(), "alive": self.alive(), **self.summary(),
                "gadget": st.get("state"), "tries": st.get("tries"), "max_tries": st.get("max_tries"),
                "gave_up": bool(st.get("gave_up")), "restarts": st.get("restarts"), "max_speed": st.get("max_speed"),
                "switches": st.get("switches") or {}, "events": list(st.get("events") or [])[-8:], "at": st.get("at")}

    def message(self) -> Optional[str]:
        st = self.state or {}
        if self.alive() and st.get("present") and st.get("gave_up"):
            return tr("USB tunnel: the printer does not connect (after {tries} attempts) – check the cable, "
                      "replug it once if needed", tries=st.get("tries"))
        return None

    def items(self) -> List[Dict[str, Any]]:
        """Switches for switches.py (group system) - only while the watchdog is running."""
        if not self.alive():
            return []
        cur = (self.state or {}).get("switches") or {}
        return [{"key": key, "group": "system", "kind": "switch", "title": title, "hint": hint,
                 "on": bool(cur.get(field)), "sensitive": True} for key, field, title, hint in SWITCHES]

    # ------------------------------------------------------------ switching
    async def set(self, key: str, value: Any) -> Dict[str, Any]:
        field = next((f for k, f, _t, _h in SWITCHES if k == key), None)
        if field is None:
            raise UsbError(404, tr("There is no switch {key}", key=key))
        if not isinstance(value, bool):
            raise UsbError(400, tr("Value: true or false"))
        if not self.alive():
            raise UsbError(503, tr("The USB watchdog on the Klipper computer is not reporting"))
        cur = dict((self.state or {}).get("switches") or {})
        cur[field] = value
        await self.moon.db_post(NS, "switches", cur)
        # show it right away; the watchdog takes it over within 10 s and reports it back
        if self.state is not None:
            self.state = dict(self.state, switches=cur)
        log.info("USB watchdog: %s = %s", field, value)
        return {"ok": True, "key": key, "value": value}
