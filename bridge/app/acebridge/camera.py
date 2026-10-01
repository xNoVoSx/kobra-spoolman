"""Kamera ueber die Bridge: genau eine Stream-Verbindung zum Drucker, weiterverteilt an alle.

Der Drucker (Rinkhals' mjpg-streamer) reicht die JPEG-Bilder der Kamera durch; teuer wird fuer den schwachen
Drucker jeder weitere Zuschauer. Deshalb haelt die Bridge hoechstens EINE Verbindung zum Stream offen - nur
solange jemand zuschaut oder ein Bild braucht - und verteilt die Bilder an Weboberflaeche, App, Mainsail/OctoApp
(ueber einen Kamera-Link) und spaeter die KI. Einzelbilder kommen aus demselben Stream.
Liefert der Drucker keinen Stream, holt die Bridge Einzelbilder (?action=snapshot), hoechstens eins pro
CAMERA_INTERVAL_S.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import time
from typing import TYPE_CHECKING, AsyncIterator, Deque, Optional, Tuple

import aiohttp

if TYPE_CHECKING:
    from .config import Config
    from .moonraker import Moonraker

log = logging.getLogger("camera")

IDLE_CLOSE_S = 20.0          # so lange nach dem letzten Zuschauer bleibt der Stream offen
FIRST_FRAME_TIMEOUT_S = 6.0
RETRY_S = 5.0                # nach einem Abbruch frühestens wieder verbinden
NO_STREAM_RETRY_S = 300.0    # Drucker liefert gar keinen Stream: so lange Einzelbilder


class CameraError(Exception):
    pass


def is_bridge_url(url: Optional[str]) -> bool:
    """Zeigt die Adresse auf den Restream einer Bridge (Kamera-Link)? Dann waere es eine Schleife."""
    return bool(url) and "/api/camera/" in url


async def read_mjpeg(content: aiohttp.StreamReader) -> AsyncIterator[bytes]:
    """JPEG-Bilder aus einem multipart/x-mixed-replace-Strom (mjpg-streamer). Nutzt Content-Length,
    sonst die JPEG-Endmarke."""
    buf = b""
    while True:
        # Kopfzeilen bis zur Leerzeile
        while b"\r\n\r\n" not in buf:
            chunk = await content.read(16384)
            if not chunk:
                return
            buf += chunk
            if len(buf) > 1_000_000:
                raise CameraError("Stream ohne erkennbare Bildgrenzen")
        head, buf = buf.split(b"\r\n\r\n", 1)
        length = None
        for line in head.split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                try:
                    length = int(line.split(b":", 1)[1].strip())
                except ValueError:
                    length = None
        if length is not None:
            while len(buf) < length:
                chunk = await content.read(max(16384, length - len(buf)))
                if not chunk:
                    return
                buf += chunk
            frame, buf = buf[:length], buf[length:]
        else:
            while b"\xff\xd9" not in buf:
                chunk = await content.read(16384)
                if not chunk:
                    return
                buf += chunk
            end = buf.index(b"\xff\xd9") + 2
            frame, buf = buf[:end], buf[end:]
        start = frame.find(b"\xff\xd8")
        if start >= 0:
            yield frame[start:]


class Camera:
    def __init__(self, cfg: "Config", moon: "Moonraker", session: aiohttp.ClientSession, clock=time.monotonic):
        self.cfg = cfg
        self.moon = moon
        self.session = session
        self.clock = clock
        self.stream_url: Optional[str] = cfg.camera_stream_url or None
        self.snapshot_url: Optional[str] = cfg.camera_snapshot_url or None
        self._resolved = bool(self.stream_url and self.snapshot_url)   # fehlende aus Moonrakers Liste
        self.image: Optional[bytes] = None
        self.frame_no = 0
        self.taken_at = 0.0
        self.taken_wall = 0.0
        self.error: Optional[str] = None
        self.mode = "idle"                       # idle | stream | snapshot
        self._times: Deque[float] = collections.deque(maxlen=60)
        self._new = asyncio.Condition()
        self._reader: Optional[asyncio.Task] = None
        self._wanted_until = 0.0
        self._viewers = 0
        self._snap_lock = asyncio.Lock()
        self._retry_at = 0.0

    # ------------------------------------------------------------ Adressen
    async def _resolve(self) -> None:
        if self._resolved:
            return
        self._resolved = True
        cam = None
        try:
            cams = (await self.moon.get_json("/server/webcams/list")).get("webcams") or []
            # Eintraege, die auf den Restream der Bridge zeigen (Mainsail mit Kamera-Link), nie als Quelle nehmen
            cam = next((c for c in cams if c.get("enabled", True) and not is_bridge_url(c.get("stream_url"))
                        and not is_bridge_url(c.get("snapshot_url"))), None)
        except Exception as e:  # noqa: BLE001
            log.info("Webcam-Liste nicht lesbar (%s) - nehme /webcam/", e)
        base = self.cfg.printer_base_url()

        def absolute(u: Optional[str], default: str) -> str:
            u = u or default
            return u if u.startswith("http") else base + u
        self.stream_url = self.stream_url or absolute((cam or {}).get("stream_url"), "/webcam/?action=stream")
        self.snapshot_url = self.snapshot_url or absolute((cam or {}).get("snapshot_url"), "/webcam/?action=snapshot")
        log.info("Kamera: Stream %s, Einzelbild %s", self.stream_url, self.snapshot_url)

    # ------------------------------------------------------------ Stream lesen (eine Verbindung)
    def fps(self) -> Optional[float]:
        now = self.clock()
        recent = [t for t in self._times if now - t <= 3.0]
        if len(recent) < 2:
            return None
        return round((len(recent) - 1) / max(recent[-1] - recent[0], 1e-3), 1)

    def _want(self) -> None:
        self._wanted_until = max(self._wanted_until, self.clock() + IDLE_CLOSE_S)
        if (self.cfg.camera_stream and self.clock() >= self._retry_at
                and (self._reader is None or self._reader.done())):
            self._reader = asyncio.create_task(self._run_stream())

    async def _publish(self, frame: bytes) -> None:
        now = self.clock()
        self.image, self.taken_at, self.taken_wall, self.error = frame, now, time.time(), None
        self.frame_no += 1
        self._times.append(now)
        async with self._new:
            self._new.notify_all()

    @property
    def streaming(self) -> bool:
        return self._reader is not None and not self._reader.done()

    async def _run_stream(self) -> None:
        await self._resolve()
        got = 0
        log.info("Kamera-Stream geoeffnet (eine Verbindung zum Drucker)")
        self.mode = "stream"
        try:
            async with self.session.get(self.stream_url, timeout=aiohttp.ClientTimeout(total=None, sock_read=10)) as r:
                r.raise_for_status()
                async for frame in read_mjpeg(r.content):
                    got += 1
                    await self._publish(frame)
                    if self._viewers == 0 and self.clock() > self._wanted_until:
                        break
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            self.error = f"Kamera-Stream: {e}"
            # ohne ein einziges Bild kann der Drucker wohl keinen Stream: eine Weile Einzelbilder
            self._retry_at = self.clock() + (RETRY_S if got else NO_STREAM_RETRY_S)
            log.warning("Kamera-Stream unterbrochen (%s) - %s", e,
                        "verbinde neu" if got else "nehme Einzelbilder")
        finally:
            self.mode = "idle"
            log.info("Kamera-Stream geschlossen")

    # ------------------------------------------------------------ Einzelbild
    async def snapshot(self) -> Tuple[bytes, float]:
        """Aktuelles Bild. Aus dem Stream, wenn er laeuft (oder kurz geoeffnet wird), sonst ein Einzelabruf."""
        if not self.cfg.camera:
            raise CameraError("Kamera ist abgeschaltet (CAMERA=false)")
        if self.image is not None and self.clock() - self.taken_at < self.cfg.camera_interval_s:
            return self.image, self.taken_wall
        self._want()
        if self.streaming:
            seen = self.frame_no
            try:
                async with self._new:
                    await asyncio.wait_for(self._new.wait_for(lambda: self.frame_no > seen), FIRST_FRAME_TIMEOUT_S)
                return self.image, self.taken_wall   # type: ignore[return-value]
            except asyncio.TimeoutError:
                pass
        return await self._single()

    async def _single(self) -> Tuple[bytes, float]:
        async with self._snap_lock:
            if self.image is not None and self.clock() - self.taken_at < self.cfg.camera_interval_s:
                return self.image, self.taken_wall
            await self._resolve()
            try:
                async with self.session.get(self.snapshot_url, timeout=aiohttp.ClientTimeout(total=8)) as r:
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
                    return self.image, self.taken_wall
                raise CameraError(self.error) from None
            if not self.streaming:
                self.mode = "snapshot"
            await self._publish(data)
            return data, self.taken_wall

    # ------------------------------------------------------------ Weiterverteilen
    async def frames(self, max_fps: Optional[float] = None) -> AsyncIterator[bytes]:
        """Bilder fuer einen Zuschauer: immer das neueste, langsame Zuschauer verpassen Bilder statt zu stauen."""
        if not self.cfg.camera:
            raise CameraError("Kamera ist abgeschaltet (CAMERA=false)")
        self._viewers += 1
        try:
            min_gap = 1.0 / max_fps if max_fps else 0.0
            last_no, last_sent = -1, 0.0
            while True:
                self._want()
                if not self.streaming:
                    data, _ = await self.snapshot()          # ohne Stream: Einzelbilder im Takt
                    if self.frame_no != last_no:
                        last_no = self.frame_no
                        yield data
                    await asyncio.sleep(max(self.cfg.camera_interval_s, min_gap))
                    continue
                async with self._new:
                    try:
                        await asyncio.wait_for(self._new.wait_for(lambda n=last_no: self.image is not None and self.frame_no != n), 10)
                    except asyncio.TimeoutError:
                        continue
                wait = min_gap - (self.clock() - last_sent)
                if wait > 0:
                    await asyncio.sleep(wait)
                last_no, last_sent = self.frame_no, self.clock()
                yield self.image   # type: ignore[misc]
        finally:
            self._viewers -= 1
            self._wanted_until = max(self._wanted_until, self.clock() + IDLE_CLOSE_S)

    def state(self) -> dict:
        return {"enabled": self.cfg.camera, "mode": self.mode, "viewers": self._viewers, "fps": self.fps(),
                "error": self.error, "stream": bool(self.cfg.camera_stream),
                "last": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.taken_wall)) if self.taken_wall else None}
