"""Kamera ueber die Bridge: eine Quelle am Drucker, weiterverteilt an alle Zuschauer.

Gemessen am Kobra S1 (01.10.2026, Rinkhals' mjpg-streamer, 1280x720): schon EIN Dauerstream
(?action=stream) treibt die Drucker-CPU auf 100 %; Einzelbilder (?action=snapshot) mit bis zu ~5 pro Sekunde
aendern nichts gegenueber dem Leerlauf (30-50 %). Deshalb holt die Bridge Einzelbilder - wie Mainsails
"adaptive"-Modus -, nur solange jemand zuschaut, und verteilt sie als MJPEG-Stream an Weboberflaeche, App,
Mainsail (Kamera-Link) und spaeter die KI.

Die Bildrate regelt sich nach der Drucker-CPU (notify_proc_stat_update, kommt ohnehin ueber die eine
Moonraker-Verbindung): Start mit 2 fps; CPU-Mittel unter CAMERA_CPU_LOW -> alle 5 s +1 fps bis CAMERA_FPS_MAX;
ueber CAMERA_CPU_HIGH -> alle 5 s 1 fps weniger bis CAMERA_FPS_MIN. Der Druck hat immer Vorrang.
CAMERA_STREAM=true nutzt stattdessen den Stream des Druckers (fuer Drucker, bei denen er billig ist).
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
START_FPS = 2.0
ADJUST_S = 5.0               # Regelschritt
CPU_WINDOW_S = 10.0          # Mittelungsfenster der Drucker-CPU (kurze Spitzen im Druck zaehlen weniger)


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
        self.target_fps = START_FPS
        self.throttled = False       # wegen hoher Drucker-CPU unter dem Maximum

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
        if self.clock() >= self._retry_at and (self._reader is None or self._reader.done()):
            self._reader = asyncio.create_task(self._run_stream() if self.cfg.camera_stream else self._run_pump())

    def _idle(self) -> bool:
        return self._viewers == 0 and self.clock() > self._wanted_until

    def adjust(self, cpu: Optional[float]) -> None:
        """Ein Regelschritt: Drucker-CPU ueber CAMERA_CPU_HIGH -> 1 fps weniger, unter CAMERA_CPU_LOW -> 1 fps mehr.
        Die Last im Druck kommt fast ganz von GoKlipper, Einzelbilder kosten kaum etwas (findings) - darum hohe
        Schwellen und kleine Schritte: eine einzelne Spitze soll die Kamera nicht abwuergen. Ohne CPU-Werte: nichts."""
        lo, hi = float(self.cfg.camera_fps_min), float(self.cfg.camera_fps_max)
        if cpu is None:
            return
        if cpu > self.cfg.camera_cpu_high:
            new = max(lo, self.target_fps - 1)
            if new < self.target_fps:
                log.info("Kamera: Drucker-CPU %.0f %% - %.1f -> %.1f fps", cpu, self.target_fps, new)
            self.target_fps, self.throttled = new, True
        elif cpu < self.cfg.camera_cpu_low and self.target_fps < hi:
            self.target_fps = min(hi, self.target_fps + 1)
            self.throttled = self.target_fps < hi and self.throttled

    async def _run_pump(self) -> None:
        """Einzelbilder nacheinander (nie zwei gleichzeitig), Rate nach der Drucker-CPU geregelt."""
        await self._resolve()
        self.mode, self.target_fps, self.throttled = "snapshots", min(START_FPS, float(self.cfg.camera_fps_max)), False
        cpu_of = getattr(self.moon, "cpu", None)
        next_adjust = self.clock() + ADJUST_S
        fails = 0
        log.info("Kamera: Einzelbilder, %.0f-%.0f fps je nach Drucker-CPU", self.cfg.camera_fps_min, self.cfg.camera_fps_max)
        try:
            while not self._idle():
                started = self.clock()
                if started >= next_adjust:
                    self.adjust(cpu_of(CPU_WINDOW_S) if cpu_of else None)
                    next_adjust = started + ADJUST_S
                try:
                    async with self.session.get(self.snapshot_url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                        r.raise_for_status()
                        data = await r.read()
                    if not data.startswith(b"\xff\xd8"):
                        raise CameraError("Antwort ist kein JPEG")
                    await self._publish(data)
                    fails = 0
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    fails += 1
                    self.error = f"Kamera nicht erreichbar: {e}"
                    if fails >= 3:
                        self._retry_at = self.clock() + RETRY_S
                        log.warning("Kamera: %s - neuer Versuch in %.0f s", e, RETRY_S)
                        return
                await asyncio.sleep(max(0.0, 1.0 / self.target_fps - (self.clock() - started)))
        finally:
            self.mode = "idle"
            log.info("Kamera: keine Zuschauer mehr - Abfrage beendet")

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
                    if self._idle():
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
                "source": "stream" if self.cfg.camera_stream else "snapshots",
                "target_fps": round(self.target_fps, 1) if self.mode == "snapshots" else None,
                "throttled": self.throttled and self.mode == "snapshots",
                "last": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.taken_wall)) if self.taken_wall else None}
