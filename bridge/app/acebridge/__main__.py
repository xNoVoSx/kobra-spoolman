"""Entry point: python -m acebridge"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Any, Dict, Optional

import aiohttp
from aiohttp import web

from . import __version__, acemodel
from .config import Config
from .ace import AceSettings
from .camera import Camera
from .moonraker import Moonraker
from .render import PrintPreview
from .slots import SlotManager
from .spoolman import Spoolman
from .telemetry import Recorder
from .auth import CameraKey, Devices
from .console import LOG_BUFFER, Console
from .phase import ChangeSteps
from .usb import UsbTunnel
from .dryer import Dryer
from .usage import UsageTracker
from .humidity import HumidityLog
from .i18n import tr
from .moisture import MoistureModel, hours_needed
from .purge import PurgeModel
from .mqtt import MqttBridge
from .filament_z import FilamentZSync
from .pa import OBJ as PA_OBJ, PaSync
from .printcheck import PrintGuard
from .clog import Clog
from .files import Files
from .machine import Machine
from .switches import Switches
from .resume import Resume
from .runtime_settings import RuntimeSettings
from .setup import Setup
from .vision import Vision
from .web import build_app

log = logging.getLogger("bridge")


class Bridge:
    def __init__(self, cfg: Config, session: aiohttp.ClientSession):
        self.cfg = cfg
        self.settings = RuntimeSettings(cfg)      # apply saved settings before all parts
        self.setup = Setup(cfg, self.settings)    # new or existing installation - before any part writes to DATA_DIR
        self.session = session
        self.moon = Moonraker(cfg, session, self._on_status)
        self.sm = Spoolman(cfg, session)
        self.slots = SlotManager(cfg, self.moon, self.sm)
        self.recorder = Recorder(cfg)
        self.usage = UsageTracker(cfg, self.moon, self.sm, self.slots)
        self.purge = PurgeModel()                                 # firmware purge under Rinkhals (purge.py)
        self.ace = AceSettings(self.moon, self.slots, self.purge)
        self.usage.purge = self.purge                             # calibrated from finished Orca prints
        self.pa = PaSync(cfg, self.moon, self.sm, self.slots)
        self.filament_z = FilamentZSync(cfg, self.moon, self.sm, self.slots)
        self.resume = Resume(self.moon, self.slots)
        self.clog = Clog(self.moon)
        self.usb = UsbTunnel(self.moon)                           # USB watchdog on the Klipper computer (Moonraker DB)
        self.switches = Switches(self.moon, self.usb)
        self.machine = Machine(self.moon, self.sm, self.slots)
        self.files = Files(self.moon, self.slots)
        self.camera = Camera(cfg, self.moon, session)
        self.vision = Vision(cfg, self.moon, self.camera, session)
        self.preview = PrintPreview(cfg, self.moon, session)
        self.preview.on_ready = self.usage.set_targets
        self.dryer = Dryer(cfg, self.moon, self.slots)
        self.humidity = HumidityLog(cfg, self.moon)
        self.dryer.log_sink = self.humidity
        self.moisture = MoistureModel(cfg, self.moon, self.slots)
        self.moisture.on_insert = self._spool_inserted
        self.humidity.spools_in_ace = self._spools_in_ace
        self.print_guard = PrintGuard(self)
        self.mqtt = MqttBridge(self)
        self.moisture.room_rh_measured = self.mqtt.room_rh
        self.devices = Devices(cfg.data_dir, cfg.app_token, trust_ingress=cfg.ha_ingress_trust)
        self.camera_key = CameraKey(cfg.data_dir)
        self.console = Console()
        self.moon.console = self.console
        self.console.listeners.append(self.recorder.on_console)   # console into the print recording
        self.phase_steps = ChangeSteps()                          # sub-step of a tool change (print phase)
        self.console.listeners.append(self.phase_steps.on_console)
        self.console.listeners.append(self.usage.on_console)      # purge length per colour change (purge log)
        self._print_state = ""
        # last print action triggered through the bridge - the app does not report its own pauses as an alarm
        self.last_control: Optional[Dict[str, Any]] = None

    async def _on_status(self, delta: Dict[str, Any], full: bool) -> None:
        if full:
            self.slots.reset_lane_cache()  # after a (re)connect write everything again
        try:
            self.recorder.on_status(delta, full, self.moon.status)
        except Exception:  # noqa: BLE001
            log.exception("Telemetry error")
        # consumption first: at print end it must be booked before postponed moves to the shelf run
        try:
            await self.usage.on_status(delta, full, self.moon.status)
        except Exception:  # noqa: BLE001
            log.exception("Consumption error")
        try:
            self.preview.watch(self.moon.status)        # new print -> load the file for the preview
        except Exception:  # noqa: BLE001
            log.exception("Preview error")
        new_state = (self.moon.status.get("print_stats", {}) or {}).get("state", "") or ""
        old_state, self._print_state = self._print_state, new_state
        if new_state != old_state:
            log.info("Printer state: %s -> %s", old_state or "?", new_state or "?")
        ace_changed = acemodel.touches(delta)
        if full or ace_changed:
            await self.dryer.evaluate()
        if full or ace_changed or new_state != old_state:
            await self.slots.evaluate()
            if new_state != old_state:
                await self.slots.on_print_state_change(old_state, new_state)
        if full or PA_OBJ in delta:
            try:
                await self.pa.tick(full)     # auto PA: new measurement result to Spoolman at once
            except Exception:  # noqa: BLE001
                log.exception("Auto PA error")
        if full:
            await self.filament_z.tick(full=True)

    def _spools_in_ace(self) -> list:
        assigned, _ = self.slots.assignments()
        out = []
        for slot, s in sorted(assigned.items()):
            if s:
                f = s.get("filament") or {}
                out.append({"slot": slot, "spool_id": s.get("id"), "name": f"{(f.get('vendor') or {}).get('name', '')} "
                            f"{f.get('name') or ''}".strip(), "score": self.moisture.view(s)["score"]})
        return out

    def wet_loaded(self) -> list:
        """Loaded spools that should be dried: (slot, spool, moisture info, hours at the ACE temperature)."""
        assigned, _ = self.slots.assignments()
        temp = self.dryer.required_temp()["temp"]
        out = []
        for slot, s in sorted(assigned.items()):
            if not s:
                continue
            v = self.moisture.view(s)
            if v["needs_drying"]:
                p = v["params"]
                e = self.moisture.state.get(str(s.get("id"))) or {}
                h = hours_needed(e.get("u"), p["dry_hours"], temp or p["dry_temp"], p["dry_temp"])
                out.append((slot, s, v, round(h, 1)))
        return out

    async def _spool_inserted(self, spool: dict, info: dict) -> None:
        """Damp spool inserted: report it (messages) and - if set - have it dried."""
        if not info.get("needs_drying") or not self.cfg.auto_dry_on_insert:
            return
        if self.slots.printing and not self.dryer.config.while_printing:
            return
        wet = self.wet_loaded()
        if not wet:
            return
        hours = max(h for *_, h in wet)
        name = ((spool.get("filament") or {}).get("name") or tr("Spool #{id}", id=spool.get("id")))
        if info.get("score") is None:
            why = tr("new – history unknown")
        elif info.get("outside_h"):
            why = tr("moisture estimate {score} %, was outside for {h:g} h", score=info["score"],
                     h=float(info["outside_h"]))
        else:
            why = tr("moisture estimate {score} %", score=info["score"])
        try:
            if await self.dryer.ensure(hours, tr("Spool inserted: {name} (slot {slot}) – {why}", name=name,
                                                 slot=info.get("slot"), why=why)):
                log.info("Drying %.1f h because of %s (%s)", hours, name, why)
        except Exception as e:  # noqa: BLE001
            log.warning("Drying on insert not started: %s", e)

    def safety_warnings(self) -> list:
        """Prevent double booking: Moonraker/firmware must not book by themselves."""
        out = []
        if "spoolman" in (self.moon.components or []):
            out.append(tr("Moonraker has [spoolman] active - consumption would be booked twice. Remove the section "
                          "[spoolman] from moonraker.conf."))
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
                await self.slots.evaluate()  # debouncing of the auto release
                await self.dryer.evaluate()  # automation and temperature safety
                self.humidity.tick()         # humidity history, drying runs
                await self.moisture.tick()   # moisture per spool
                await self.print_guard.tick()  # damp spool at print start -> pause if set
                await self.ace.refresh()
                await self.pa.tick()         # auto PA: Spoolman state of the slots to Klipper (only on change)
                await self.filament_z.tick()  # Z offset per slot to KOBRA_START (only on change)
                await self.usb.tick()        # state of the USB watchdog (every 30 s)
            except Exception:  # noqa: BLE001
                log.exception("Ticker error")


async def amain() -> None:
    cfg = Config()
    logging.basicConfig(level=getattr(logging, cfg.log_level, logging.INFO),
                        format="%(asctime)s %(levelname)-7s %(name)-10s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger().addHandler(LOG_BUFFER)      # "Logs" page / app log
    log.info("ace-lane-bridge %s", __version__)
    if not cfg.moonraker_url:
        log.error("MOONRAKER_URL missing - set e.g. MOONRAKER_URL=http://<printer-ip>:7125")
        sys.exit(2)
    log.info("  Moonraker : %s", cfg.moonraker_url)
    log.info("  Spoolman  : %s", cfg.spoolman_url)
    log.info("  HTTP      : %s:%d", cfg.http_host, cfg.http_port)
    log.info("  Booking   : %s (interim booking every %ss)", "on" if cfg.book_usage else "off",
             int(cfg.book_interval_s))
    log.info("  lane_data : %s | auto shelf: %s (%ss) | telemetry: %s | language: %s",
             "on" if cfg.write_lane_data else "off", "on" if cfg.auto_unassign_on_empty else "off",
             int(cfg.empty_debounce_s), "on" if cfg.telemetry else "off", cfg.language)
    if cfg.dry_run:
        log.warning("  DRY_RUN active - nothing is written")

    async with aiohttp.ClientSession() as session:
        bridge = Bridge(cfg, session)
        bridge.devices.announce()
        await bridge.sm.refresh()

        runner = web.AppRunner(build_app(bridge), access_log=None)
        await runner.setup()
        await web.TCPSite(runner, cfg.http_host, cfg.http_port).start()

        tasks = [asyncio.create_task(c) for c in (bridge.moon.run(), bridge.spoolman_loop(), bridge.ticker(),
                                                         bridge.vision.run(), bridge.mqtt.run())]
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:
                pass
        await stop.wait()
        log.info("Stopping ...")
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
