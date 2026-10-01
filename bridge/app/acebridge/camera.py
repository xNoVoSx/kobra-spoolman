"""Kamera ueber die Bridge: Einzelbilder vom Drucker, einmal geholt, an alle verteilt.

Rinkhals' Doku warnt ausdruecklich vor dem Stream-Modus von mjpg-streamer ("will spike your CPU usage"),
deshalb nur ?action=snapshot - und nur, wenn jemand ein Bild will. Gleichzeitige Anfragen teilen sich
einen Abruf; mehr als ein Bild pro CAMERA_INTERVAL_S holt die Bridge nie, egal wie viele zuschauen.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Optional, Tuple

import aiohttp

if TYPE_CHECKING:
    from .config import Config
    from .moonraker import Moonraker

log = logging.getLogger("camera")


class CameraError(Exception):
    pass


class Camera:
    def __init__(self, cfg: "Config", moon: "Moonraker", session: aiohttp.ClientSession, clock=time.monotonic):
        self.cfg = cfg
        self.moon = moon
        self.session = session
        self.clock = clock
        self.url: Optional[str] = cfg.camera_snapshot_url or None
        self.image: Optional[bytes] = None
        self.taken_at = 0.0           # Monotonic-Zeit des letzten Bildes
        self.taken_wall = 0.0         # Wanduhr fuer die Anzeige
        self.error: Optional[str] = None
        self._lock = asyncio.Lock()
        self._resolved = bool(self.url)

    async def _resolve(self) -> None:
        """Snapshot-Adresse aus Moonrakers Webcam-Liste (relativ zum Drucker-Webserver)."""
        if self._resolved:
            return
        self._resolved = True
        try:
            cams = (await self.moon.get_json("/server/webcams/list")).get("webcams") or []
            cam = next((c for c in cams if c.get("enabled", True) and c.get("snapshot_url")), None)
        except Exception as e:  # noqa: BLE001
            log.info("Webcam-Liste nicht lesbar (%s) - nehme /webcam/?action=snapshot", e)
            cam = None
        snap = (cam or {}).get("snapshot_url") or "/webcam/?action=snapshot"
        self.url = snap if snap.startswith("http") else self.cfg.printer_base_url() + snap
        log.info("Kamera: %s", self.url)

    async def snapshot(self) -> Tuple[bytes, float]:
        """Aktuelles Bild (JPEG) und Zeitpunkt. Ein frisches Bild wird nur geholt, wenn das letzte aelter
        als CAMERA_INTERVAL_S ist; wer gleichzeitig fragt, wartet auf denselben Abruf."""
        if not self.cfg.camera:
            raise CameraError("Kamera ist abgeschaltet (CAMERA=false)")
        async with self._lock:
            if self.image is not None and self.clock() - self.taken_at < self.cfg.camera_interval_s:
                return self.image, self.taken_wall
            await self._resolve()
            if not self.url:
                raise CameraError("Keine Kamera-Adresse")
            try:
                async with self.session.get(self.url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                    r.raise_for_status()
                    data = await r.read()
                if not data.startswith(b"\xff\xd8"):
                    raise CameraError("Antwort ist kein JPEG")
            except CameraError as e:
                self.error = str(e)
                raise
            except Exception as e:  # noqa: BLE001
                self.error = f"Kamera nicht erreichbar: {e}"
                if self.image is not None and self.clock() - self.taken_at < 30:
                    return self.image, self.taken_wall   # kurz das letzte Bild weiter zeigen
                raise CameraError(self.error) from None
            self.image, self.taken_at, self.taken_wall, self.error = data, self.clock(), time.time(), None
            return data, self.taken_wall

    def state(self) -> dict:
        return {"enabled": self.cfg.camera, "url_known": bool(self.url), "error": self.error,
                "interval_s": self.cfg.camera_interval_s,
                "last": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.taken_wall)) if self.taken_wall else None}
