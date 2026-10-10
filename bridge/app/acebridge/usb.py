"""USB-Tunnel zwischen Drucker und Klipper-Rechner: Zustand des Waechters und seine Schalter.

Der Klipper-Rechner (Pi) ist per USB-Gadget mit dem Drucker verbunden. Nach Drucker aus/an bricht die Anmeldung dort
manchmal ab; ein Waechter-Dienst am Pi (kobra-klipper: pi/usb/kobra-usb-watch.py) steckt dann selbst neu an und laedt
Klipper neu. Er legt seinen Zustand in Moonrakers Datenbank ab (Namensraum `kobra_usb`, Schluessel `state`) und liest
dort seine Schalter (`switches`: watch, auto_restart, full_speed) - sie gelten vor seiner Konfigurationsdatei.

Die Bridge liest den Zustand alle 30 s (eine kleine Abfrage am Pi, nichts am Drucker), zeigt ihn als Statuszeile und
Meldung und schaltet ueber dieselbe Schalter-Liste wie die Klipper-Module (switches.py). Fehlt der Waechter, fehlt alles.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from .moonraker import Moonraker

log = logging.getLogger("usb")

NS = "kobra_usb"
POLL_S = 30.0
STALE_S = 180.0          # Lebenszeichen alle 60 s - aelter: Waechter laeuft nicht
SWITCHES = [
    ("usb_watch", "watch", "USB selbst neu anstecken", "Drucker an, aber nicht verbunden → der Pi steckt sich neu an"),
    ("usb_auto_restart", "auto_restart", "Klipper danach neu laden", "Wenn Klipper die Platinen verloren hat (nie im Druck)"),
    ("usb_full_speed", "full_speed", "USB langsam, robust", "12 Mbit/s – nur wenn die Verbindung trotz Wächter oft scheitert"),
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
        now = self.mono()
        if not force and self.read_at is not None and now - self.read_at < POLL_S:
            return
        self.read_at = now
        try:
            val = await self.moon.db_get(NS, "state")
        except Exception as e:  # noqa: BLE001 - Moonraker kurz weg: beim naechsten Mal
            log.debug("USB-Waechter lesen: %s", e)
            return
        self.state = val if isinstance(val, dict) else None

    # ------------------------------------------------------------ Sicht
    def available(self) -> bool:
        return self.state is not None

    def alive(self) -> bool:
        at = (self.state or {}).get("at")
        return isinstance(at, (int, float)) and self.clock() - at < STALE_S

    def summary(self) -> Dict[str, str]:
        """{"state": ok|warn|bad|off, "detail": Text} fuer Statuszeile und Display."""
        st = self.state or {}
        if not self.alive():
            return {"state": "warn", "detail": "Wächter meldet sich nicht (Dienst kobra-usb-watch?)"}
        if st.get("state") == "configured":
            speed = " · 12 Mbit/s" if st.get("max_speed") == "full-speed" else ""
            return {"state": "ok", "detail": "verbunden" + speed}
        if not st.get("present"):
            return {"state": "off", "detail": "Drucker aus"}
        if st.get("gave_up"):
            return {"state": "bad", "detail": f"keine Verbindung nach {st.get('tries')} Versuchen – Kabel prüfen"}
        if st.get("tries"):
            return {"state": "warn", "detail": f"verbindet … Versuch {st['tries']}/{st.get('max_tries')}"}
        return {"state": "warn", "detail": "Drucker an, wartet auf Verbindung"}

    def view(self) -> Dict[str, Any]:
        st = self.state or {}
        return {"available": self.available(), "alive": self.alive(), **self.summary(),
                "gadget": st.get("state"), "tries": st.get("tries"), "max_tries": st.get("max_tries"),
                "gave_up": bool(st.get("gave_up")), "restarts": st.get("restarts"), "max_speed": st.get("max_speed"),
                "switches": st.get("switches") or {}, "events": list(st.get("events") or [])[-8:], "at": st.get("at")}

    def message(self) -> Optional[str]:
        st = self.state or {}
        if self.alive() and st.get("present") and st.get("gave_up"):
            return (f"USB-Tunnel: der Drucker verbindet sich nicht (nach {st.get('tries')} Versuchen) – Kabel prüfen, "
                    "notfalls einmal umstecken")
        return None

    def items(self) -> List[Dict[str, Any]]:
        """Schalter fuer switches.py (Gruppe System) - nur, wenn der Waechter laeuft."""
        if not self.alive():
            return []
        cur = (self.state or {}).get("switches") or {}
        return [{"key": key, "group": "system", "kind": "switch", "title": title, "hint": hint,
                 "on": bool(cur.get(field)), "sensitive": True} for key, field, title, hint in SWITCHES]

    # ------------------------------------------------------------ Schalten
    async def set(self, key: str, value: Any) -> Dict[str, Any]:
        field = next((f for k, f, _t, _h in SWITCHES if k == key), None)
        if field is None:
            raise UsbError(404, f"Schalter {key} gibt es nicht")
        if not isinstance(value, bool):
            raise UsbError(400, "Wert: true oder false")
        if not self.alive():
            raise UsbError(503, "Der USB-Wächter am Klipper-Rechner meldet sich nicht")
        cur = dict((self.state or {}).get("switches") or {})
        cur[field] = value
        await self.moon.db_post(NS, "switches", cur)
        # sofort so anzeigen; der Waechter uebernimmt es binnen 10 s und meldet es zurueck
        if self.state is not None:
            self.state = dict(self.state, switches=cur)
        log.info("USB-Wächter: %s = %s", field, value)
        return {"ok": True, "key": key, "value": value}
