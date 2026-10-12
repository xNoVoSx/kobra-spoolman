"""Camera through the bridge: one source at the printer, re-distributed to every viewer.

The camera is attached to the printer (mjpg-streamer, port 8080); its URLs come from Moonraker's webcam list. On the
stock firmware even ONE continuous stream used the whole printer CPU (2026-10-01) - so the bridge fetches snapshots
(like Mainsail's "adaptive" mode), only while someone watches, at most CAMERA_FPS_MAX, and re-distributes them as an
MJPEG stream to web UI, app, Mainsail (camera link) and the AI. With Klipper on a separate computer the printer CPU is
free: CAMERA_STREAM=true uses the printer's continuous stream (full frame rate).

Under Rinkhals Moonraker reports the printer's own CPU (notify_proc_stat_update, over the one Moonraker connection
anyway): the frame rate follows it - start with 2 fps; CPU mean below CAMERA_CPU_LOW -> +1 fps every 5 s up to
CAMERA_FPS_MAX; above CAMERA_CPU_HIGH -> 1 fps less every 5 s down to CAMERA_FPS_MIN. The print always comes first.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import time
from typing import TYPE_CHECKING, AsyncIterator, Deque, Optional, Tuple

import aiohttp

from .i18n import msg_of, tr

if TYPE_CHECKING:
    from .config import Config
    from .moonraker import Moonraker

log = logging.getLogger("camera")

IDLE_CLOSE_S = 20.0          # the stream stays open this long after the last viewer
FIRST_FRAME_TIMEOUT_S = 6.0
NEXT_FRAME_TIMEOUT_S = 10.0  # frame.jpg waits at most this long for a newer image
RETRY_S = 5.0                # reconnect no sooner after a failure
START_FPS = 2.0              # Rinkhals: start rate, then by the printer CPU
ADJUST_S = 5.0               # control step
CPU_WINDOW_S = 10.0          # averaging window of the printer CPU (short peaks while printing count less)
NO_STREAM_RETRY_S = 300.0    # printer delivers no stream at all: snapshots for this long


class CameraError(Exception):
    pass


def is_bridge_url(url: Optional[str]) -> bool:
    """Does the URL point to a bridge's restream (camera link)? Then it would be a loop."""
    return bool(url) and "/api/camera/" in url


async def read_mjpeg(content: aiohttp.StreamReader) -> AsyncIterator[bytes]:
    """JPEG images from a multipart/x-mixed-replace stream (mjpg-streamer). Uses Content-Length, else the JPEG end
    marker."""
    buf = b""
    while True:
        # headers up to the empty line
        while b"\r\n\r\n" not in buf:
            chunk = await content.read(16384)
            if not chunk:
                return
            buf += chunk
            if len(buf) > 1_000_000:
                raise CameraError(tr("Stream without recognisable image boundaries"))
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
        self._resolved = bool(self.stream_url and self.snapshot_url)   # missing ones from Moonraker's list
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
        self.target_fps = float(cfg.camera_fps_max)
        self.throttled = False       # Rinkhals: below the maximum because of a high printer CPU

    # ------------------------------------------------------------ URLs
    async def _resolve(self) -> None:
        if self._resolved:
            return
        self._resolved = True
        cam = None
        try:
            cams = (await self.moon.get_json("/server/webcams/list")).get("webcams") or []
            # never use entries that point to the bridge's restream (Mainsail with the camera link) as the source
            cam = next((c for c in cams if c.get("enabled", True) and not is_bridge_url(c.get("stream_url"))
                        and not is_bridge_url(c.get("snapshot_url"))), None)
        except Exception as e:  # noqa: BLE001
            log.info("Webcam list unreadable (%s) - using /webcam/", e)
        base = self.cfg.printer_base_url()

        def absolute(u: Optional[str], default: str) -> str:
            u = u or default
            return u if u.startswith("http") else base + u
        self.stream_url = self.stream_url or absolute((cam or {}).get("stream_url"), "/webcam/?action=stream")
        self.snapshot_url = self.snapshot_url or absolute((cam or {}).get("snapshot_url"), "/webcam/?action=snapshot")
        log.info("Camera: stream %s, snapshot %s", self.stream_url, self.snapshot_url)

    # ------------------------------------------------------------ reading the stream (one connection)
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

    def _throttles(self) -> bool:
        """The frame rate follows the printer CPU only where Moonraker reports the printer's own CPU (Rinkhals)."""
        return getattr(self.moon, "platform", "klipper") == "rinkhals"

    def adjust(self, cpu: Optional[float]) -> None:
        """One control step: printer CPU above CAMERA_CPU_HIGH -> 1 fps less, below CAMERA_CPU_LOW -> 1 fps more.
        The load while printing comes almost entirely from GoKlipper, snapshots cost little (findings) - hence high
        thresholds and small steps: a single peak should not choke the camera. Without CPU values: nothing."""
        lo, hi = float(self.cfg.camera_fps_min), float(self.cfg.camera_fps_max)
        if cpu is None:
            return
        if cpu > self.cfg.camera_cpu_high:
            new = max(lo, self.target_fps - 1)
            if new < self.target_fps:
                log.info("Camera: printer CPU %.0f %% - %.1f -> %.1f fps", cpu, self.target_fps, new)
            self.target_fps, self.throttled = new, True
        elif cpu < self.cfg.camera_cpu_low and self.target_fps < hi:
            self.target_fps = min(hi, self.target_fps + 1)
            self.throttled = self.target_fps < hi and self.throttled

    async def _run_pump(self) -> None:
        """Snapshots one after the other (never two at once): at CAMERA_FPS_MAX, under Rinkhals by the printer CPU."""
        await self._resolve()
        throttles = self._throttles()
        start = min(START_FPS, float(self.cfg.camera_fps_max)) if throttles else float(self.cfg.camera_fps_max)
        self.mode, self.target_fps, self.throttled = "snapshots", start, False
        cpu_of = getattr(self.moon, "cpu", None)
        next_adjust = self.clock() + ADJUST_S
        fails = 0
        log.info("Camera: snapshots, %s", f"{self.cfg.camera_fps_min:.0f}-{self.cfg.camera_fps_max:.0f} fps by the "
                 "printer CPU" if throttles else f"up to {self.target_fps:.0f} fps")
        try:
            while not self._idle():
                started = self.clock()
                try:
                    async with self.session.get(self.snapshot_url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                        r.raise_for_status()
                        data = await r.read()
                    if not data.startswith(b"\xff\xd8"):
                        raise CameraError(tr("Answer is not a JPEG"))
                    await self._publish(data)
                    fails = 0
                    if throttles and started >= next_adjust:
                        self.adjust(cpu_of(CPU_WINDOW_S) if cpu_of else None)
                        next_adjust = started + ADJUST_S
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    fails += 1
                    self.error = tr("Camera not reachable: {error}", error=str(e))
                    if fails >= 3:
                        self._retry_at = self.clock() + RETRY_S
                        log.warning("Camera: %s - retrying in %.0f s", e, RETRY_S)
                        return
                await asyncio.sleep(max(0.0, 1.0 / self.target_fps - (self.clock() - started)))
        finally:
            self.mode = "idle"
            log.info("Camera: no viewers left - polling stopped")

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
        log.info("Camera stream opened (one connection to the printer)")
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
            self.error = tr("Camera stream: {error}", error=str(e))
            # without a single image the printer probably cannot stream: snapshots for a while
            self._retry_at = self.clock() + (RETRY_S if got else NO_STREAM_RETRY_S)
            log.warning("Camera stream interrupted (%s) - %s", e,
                        "reconnecting" if got else "using snapshots")
        finally:
            self.mode = "idle"
            log.info("Camera stream closed")

    # ------------------------------------------------------------ snapshot
    async def snapshot(self) -> Tuple[bytes, float]:
        """Current image. From the stream when it runs (or is opened briefly), else a single request."""
        if not self.cfg.camera:
            raise CameraError(tr("Camera is switched off (CAMERA=false)"))
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

    async def still(self) -> Tuple[bytes, float]:
        """One image for the AI: the current one when someone watches, else exactly one request - does not start the
        image pump (snapshot() keeps it running for IDLE_CLOSE_S at up to CAMERA_FPS_MAX)."""
        if not self.cfg.camera:
            raise CameraError(tr("Camera is switched off (CAMERA=false)"))
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
                    raise CameraError(tr("Answer is not a JPEG"))
            except CameraError as e:
                self.error = msg_of(e)
                raise
            except Exception as e:  # noqa: BLE001
                self.error = tr("Camera not reachable: {error}", error=str(e))
                if self.image is not None and self.clock() - self.taken_at < 30:
                    return self.image, self.taken_wall
                raise CameraError(self.error) from None
            if not self.streaming:
                self.mode = "snapshot"
            await self._publish(data)
            return data, self.taken_wall

    # ------------------------------------------------------------ re-distributing
    async def next_frame(self, after: int, timeout: float = NEXT_FRAME_TIMEOUT_S) -> Tuple[bytes, int]:
        """The first image newer than frame number `after` - for viewers that cannot hold an MJPEG stream (Home
        Assistant ingress): they ask again as soon as an image is there, which keeps the reader running like a stream
        viewer and gives them its full frame rate."""
        if not self.cfg.camera:
            raise CameraError(tr("Camera is switched off (CAMERA=false)"))
        self._want()
        if not self.streaming:                       # reader cannot run right now (after errors): a single image
            data, _ = await self.snapshot()
            return data, self.frame_no
        if self.image is None or self.frame_no <= after:
            async with self._new:
                try:
                    await asyncio.wait_for(
                        self._new.wait_for(lambda: self.image is not None and self.frame_no > after), timeout)
                except asyncio.TimeoutError:
                    pass
        if self.image is None:
            raise CameraError(self.error or tr("No camera image yet"))
        return self.image, self.frame_no

    async def frames(self, max_fps: Optional[float] = None) -> AsyncIterator[bytes]:
        """Images for one viewer: always the newest; slow viewers miss images instead of piling them up."""
        if not self.cfg.camera:
            raise CameraError(tr("Camera is switched off (CAMERA=false)"))
        self._viewers += 1
        try:
            min_gap = 1.0 / max_fps if max_fps else 0.0
            last_no, last_sent = -1, 0.0
            while True:
                self._want()
                if not self.streaming:
                    data, _ = await self.snapshot()          # without a stream: snapshots at the interval
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
                "throttled": self.throttled and self.mode == "snapshots",   # Rinkhals: slowed by the printer CPU
                "last": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.taken_wall)) if self.taken_wall else None}
