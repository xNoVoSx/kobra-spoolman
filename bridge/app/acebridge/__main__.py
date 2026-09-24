"""Einstiegspunkt: python -m acebridge"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Any, Dict

import aiohttp
from aiohttp import web

from . import __version__
from .config import Config
from .moonraker import Moonraker
from .slots import SlotManager
from .spoolman import Spoolman
from .telemetry import Recorder
from .usage import UsageTracker
from .web import build_app

log = logging.getLogger("bridge")


class Bridge:
    def __init__(self, cfg: Config, session: aiohttp.ClientSession):
        self.cfg = cfg
        self.session = session
        self.moon = Moonraker(cfg, session, self._on_status)
        self.sm = Spoolman(cfg, session)
        self.slots = SlotManager(cfg, self.moon, self.sm)
        self.recorder = Recorder(cfg)
        self.usage = UsageTracker(cfg, self.moon, self.sm, self.slots)
        self._print_state = ""

    async def _on_status(self, delta: Dict[str, Any], full: bool) -> None:
        if full:
            self.slots.reset_lane_cache()  # nach (Re-)Connect alles neu schreiben
        try:
            self.recorder.on_status(delta, full, self.moon.status)
        except Exception:  # noqa: BLE001
            log.exception("Telemetrie-Fehler")
        # Verbrauch zuerst: bei Druckende muss gebucht sein, bevor aufgeschobene
        # Rueckbuchungen ins Regal laufen
        try:
            await self.usage.on_status(delta, full, self.moon.status)
        except Exception:  # noqa: BLE001
            log.exception("Verbrauchs-Fehler")
        new_state = (self.moon.status.get("print_stats", {}) or {}).get("state", "") or ""
        old_state, self._print_state = self._print_state, new_state
        if new_state != old_state:
            log.info("Druckerstatus: %s -> %s", old_state or "?", new_state or "?")
        if full or "mmu" in delta or new_state != old_state:
            await self.slots.evaluate()
            if new_state != old_state:
                await self.slots.on_print_state_change(old_state, new_state)

    def safety_warnings(self) -> list:
        """Doppelte Buchung verhindern: Moonraker/Firmware duerfen nicht selbst buchen."""
        out = []
        if "spoolman" in (self.moon.components or []):
            out.append("Moonraker hat [spoolman] aktiv - Verbrauch wuerde doppelt gebucht. "
                       "Abschnitt [spoolman] in moonraker.conf entfernen.")
        support = (self.moon.status.get("mmu", {}) or {}).get("spoolman_support")
        if support not in (None, "off"):
            out.append(f"Drucker-Firmware meldet spoolman_support={support} - Verbrauch wuerde doppelt gebucht.")
        return out

    async def spoolman_loop(self) -> None:
        while True:
            before = [(s.get("id"), s.get("location"), (s.get("filament") or {}).get("id")) for s in self.sm.spools]
            fil_before = [(f.get("id"), f.get("material"), f.get("color_hex"), f.get("extra")) for f in self.sm.filaments]
            if await self.sm.refresh():
                after = [(s.get("id"), s.get("location"), (s.get("filament") or {}).get("id")) for s in self.sm.spools]
                fil_after = [(f.get("id"), f.get("material"), f.get("color_hex"), f.get("extra")) for f in self.sm.filaments]
                if before != after or fil_before != fil_after:
                    await self.slots.evaluate()
            await asyncio.sleep(self.cfg.spoolman_poll_s)

    async def ticker(self) -> None:
        while True:
            await asyncio.sleep(2)
            try:
                self.recorder.tick(self.moon.status)
                await self.usage.tick()
                await self.slots.evaluate()  # Entprellung der Auto-Freigabe
            except Exception:  # noqa: BLE001
                log.exception("Ticker-Fehler")


async def amain() -> None:
    cfg = Config()
    logging.basicConfig(level=getattr(logging, cfg.log_level, logging.INFO),
                        format="%(asctime)s %(levelname)-7s %(name)-10s %(message)s", datefmt="%H:%M:%S")
    log.info("ace-lane-bridge %s", __version__)
    if not cfg.moonraker_url:
        log.error("MOONRAKER_URL fehlt - z.B. MOONRAKER_URL=http://<drucker-ip>:7125 setzen")
        sys.exit(2)
    log.info("  Moonraker : %s", cfg.moonraker_url)
    log.info("  Spoolman  : %s", cfg.spoolman_url)
    log.info("  HTTP      : %s:%d", cfg.http_host, cfg.http_port)
    log.info("  Buchung   : %s (Zwischenbuchung alle %ss)", "an" if cfg.book_usage else "aus",
             int(cfg.book_interval_s))
    log.info("  lane_data : %s | Auto-Regal: %s (%ss) | Telemetrie: %s",
             "an" if cfg.write_lane_data else "aus", "an" if cfg.auto_unassign_on_empty else "aus",
             int(cfg.empty_debounce_s), "an" if cfg.telemetry else "aus")
    if cfg.dry_run:
        log.warning("  DRY_RUN aktiv - es wird nichts geschrieben")

    async with aiohttp.ClientSession() as session:
        bridge = Bridge(cfg, session)
        await bridge.sm.refresh()

        runner = web.AppRunner(build_app(bridge), access_log=None)
        await runner.setup()
        await web.TCPSite(runner, cfg.http_host, cfg.http_port).start()

        tasks = [asyncio.create_task(c) for c in (bridge.moon.run(), bridge.spoolman_loop(), bridge.ticker())]
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:
                pass
        await stop.wait()
        log.info("Beende ...")
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await runner.cleanup()


def main() -> int:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
