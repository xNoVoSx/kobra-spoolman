"""CPU of the printer itself (its own small computer), wherever the bridge can read it.

- Rinkhals: Moonraker runs on the printer - its notify_proc_stat_update (moon.cpu, over the one connection anyway) is
  the printer CPU.
- Klipper on a separate computer with the camera still on the printer (kobra-klipper's USB tunnel): Klipper and
  Moonraker run on the Pi, but mjpg-streamer and the tunnel stay on the printer - a continuous camera stream took its
  CPU to 100 % (2026-10-19). Rinkhals' own Moonraker keeps running there (Klipper disconnected) and still reports the
  CPU: the bridge reads /machine/proc_stats every POLL_S seconds, read only. Address: PRINTER_CPU_URL, else the
  camera's host on Moonraker's port 7125 - only when that is not the Klipper computer itself (a camera on the Pi says
  nothing about the printer). PRINTER_CPU_URL=off: never asked.

The camera follows this value (frame rate by the printer CPU, no continuous stream), web, app, display and Home
Assistant show it.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import time
from typing import TYPE_CHECKING, Awaitable, Callable, Deque, Optional, Tuple
from urllib.parse import urlparse

import aiohttp

from .i18n import msg_of

if TYPE_CHECKING:
    from .config import Config
    from .moonraker import Moonraker

log = logging.getLogger("printercpu")

POLL_S = 3.0             # one small read request; Moonraker measures every second anyway
RETRY_S = 300.0          # printer's Moonraker not reachable: ask again after this long
MOONRAKER_PORT = 7125


def _host(url: Optional[str]) -> Optional[str]:
    try:
        return urlparse(url or "").hostname or None
    except ValueError:
        return None


def parse_cpu(result: dict) -> Optional[float]:
    """System CPU in % from /machine/proc_stats (Moonraker: result.system_cpu_usage.cpu)."""
    cpu = ((result or {}).get("system_cpu_usage") or {}).get("cpu")
    return float(cpu) if isinstance(cpu, (int, float)) else None


class PrinterCpu:
    def __init__(self, cfg: "Config", moon: "Moonraker", session: Optional[aiohttp.ClientSession],
                 source_url: Optional[Callable[[], Awaitable[Optional[str]]]] = None, clock=time.monotonic):
        self.cfg, self.moon, self.session = cfg, moon, session
        self.source_url = source_url        # camera's source URL (camera.Camera.source_url) for the automatic address
        self.clock = clock
        self.url: Optional[str] = None      # Moonraker on the printer (not under Rinkhals: there it is self.moon)
        self.samples: Deque[Tuple[float, float]] = collections.deque(maxlen=60)
        self.error: Optional[str] = None

    # ------------------------------------------------------------ state
    def _rinkhals(self) -> bool:
        return getattr(self.moon, "platform", "klipper") == "rinkhals"

    def _setting(self) -> str:
        return (getattr(self.cfg, "printer_cpu_url", "") or "").strip().rstrip("/")

    def measures(self) -> bool:
        """Is there a printer CPU at all (Rinkhals, or the printer's Moonraker answered once)?"""
        return self._rinkhals() or self.url is not None

    def source(self) -> Optional[str]:
        """"rinkhals" (Moonraker on the printer), "printer" (its Moonraker beside a separate Klipper), None."""
        return "rinkhals" if self._rinkhals() else "printer" if self.url else None

    def cpu(self, window_s: float = 5.0) -> Optional[float]:
        """Mean printer CPU over the last window_s seconds, None without fresh values."""
        if self._rinkhals():
            cpu_of = getattr(self.moon, "cpu", None)
            return cpu_of(window_s) if callable(cpu_of) else None
        if self.url is None:
            return None
        now = self.clock()
        window = max(window_s, 2 * POLL_S + 0.5)          # at least two polls
        vals = [c for t, c in self.samples if now - t <= window]
        return sum(vals) / len(vals) if vals else None

    # ------------------------------------------------------------ reading
    async def _candidate(self) -> Optional[str]:
        """Address of the printer's Moonraker: the setting, else the camera's host if it is not the Klipper computer."""
        setting = self._setting()
        if setting.lower() in ("off", "false", "0", "no"):
            return None
        if setting:
            return setting if setting.startswith("http") else f"http://{setting}"
        if self.source_url is None:
            return None
        host = _host(await self.source_url())
        if not host or host == _host(getattr(self.cfg, "moonraker_url", "")):
            return None
        return f"http://{host}:{MOONRAKER_PORT}"

    async def read(self, url: str) -> float:
        async with self.session.get(f"{url}/machine/proc_stats", timeout=aiohttp.ClientTimeout(total=5)) as r:
            r.raise_for_status()
            cpu = parse_cpu((await r.json()).get("result") or {})
        if cpu is None:
            raise ValueError("no system_cpu_usage")
        return cpu

    async def run(self) -> None:
        """Poll the printer's Moonraker while Klipper runs elsewhere; under Rinkhals nothing to do."""
        while True:
            if self._rinkhals() or not getattr(self.moon, "connected", False) or self.session is None:
                await asyncio.sleep(10.0)
                continue
            try:
                url = await self._candidate()
            except Exception as e:  # noqa: BLE001
                log.debug("Printer CPU: no address (%s)", e)
                url = None
            if url is None:
                if self.url:
                    log.info("Printer CPU: not asked any more")
                self.url = None
                await asyncio.sleep(RETRY_S)
                continue
            try:
                cpu = await self.read(url)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                if self.error is None:
                    log.info("Printer CPU: %s not readable (%s) - asking again in %.0f min", url, msg_of(e) or
                             type(e).__name__, RETRY_S / 60)
                self.error = msg_of(e) or type(e).__name__
                await asyncio.sleep(POLL_S if self.url == url else RETRY_S)   # known source: a short gap only
                continue
            if self.url != url:
                log.info("Printer CPU: read from %s (camera and USB tunnel run there)", url)
            self.url, self.error = url, None
            self.samples.append((self.clock(), cpu))
            await asyncio.sleep(POLL_S)
