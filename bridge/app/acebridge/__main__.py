"""Einstiegspunkt: python -m acebridge"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Any, Dict, Optional

import aiohttp
from aiohttp import web

from . import __version__
from .config import Config
from .ace import AceSettings
from .camera import Camera
from .moonraker import Moonraker
from .purge import PurgeModel
from .render import PrintPreview
from .slots import SlotManager
from .spoolman import Spoolman
from .telemetry import Recorder
from .auth import CameraKey, Devices
from .console import LOG_BUFFER, Console
from .dryer import Dryer
from .usage import UsageTracker
from .humidity import HumidityLog
from .moisture import MoistureModel, hours_needed
from .runtime_settings import RuntimeSettings
from .vision import Vision
from .web import build_app

log = logging.getLogger("bridge")


def spoolman_support_off(value) -> bool:
    """Rinkhals meldet "off"; False/0/"false" (andere Staende) gelten ebenso als aus."""
    return value is None or value is False or str(value).strip().lower() in ("off", "false", "0", "disabled", "")


class Bridge:
    def __init__(self, cfg: Config, session: aiohttp.ClientSession):
        self.cfg = cfg
        self.settings = RuntimeSettings(cfg)      # gespeicherte Einstellungen vor allen Bausteinen anwenden
        self.session = session
        self.moon = Moonraker(cfg, session, self._on_status)
        self.sm = Spoolman(cfg, session)
        self.slots = SlotManager(cfg, self.moon, self.sm)
        self.recorder = Recorder(cfg)
        self.usage = UsageTracker(cfg, self.moon, self.sm, self.slots)
        self.purge = PurgeModel()
        self.usage.purge = self.purge
        self.purge.learn(self.usage.history)
        self.ace = AceSettings(self.moon, self.purge, self.slots, self.sm)
        self.camera = Camera(cfg, self.moon, session)
        self.vision = Vision(cfg, self.moon, self.camera, session)
        self.preview = PrintPreview(cfg, self.moon, session)
        self.dryer = Dryer(cfg, self.moon, self.slots)
        self.humidity = HumidityLog(cfg, self.moon)
        self.dryer.log_sink = self.humidity
        self.moisture = MoistureModel(cfg, self.moon, self.slots)
        self.moisture.on_insert = self._spool_inserted
        self.humidity.spools_in_ace = self._spools_in_ace
        self.devices = Devices(cfg.data_dir, cfg.app_token)
        self.camera_key = CameraKey(cfg.data_dir)
        self.console = Console()
        self.moon.console = self.console
        self._print_state = ""
        # zuletzt ueber die Bridge ausgeloeste Druckaktion - die App meldet eigene Pausen nicht als Alarm
        self.last_control: Optional[Dict[str, Any]] = None

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
        try:
            self.preview.watch(self.moon.status)        # neuer Druck -> Datei fuer die Vorschau laden
        except Exception:  # noqa: BLE001
            log.exception("Vorschau-Fehler")
        new_state = (self.moon.status.get("print_stats", {}) or {}).get("state", "") or ""
        old_state, self._print_state = self._print_state, new_state
        if new_state != old_state:
            log.info("Druckerstatus: %s -> %s", old_state or "?", new_state or "?")
        if full or "filament_hub" in delta:
            await self.dryer.evaluate()
        if full or "mmu" in delta or new_state != old_state:
            await self.slots.evaluate()
            if new_state != old_state:
                await self.slots.on_print_state_change(old_state, new_state)

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
        """Eingelegte Spulen, die getrocknet werden sollten: (Slot, Spule, Feuchte-Info, Stunden bei der ACE-Temperatur)."""
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
        """Feuchte Spule eingelegt: melden (messages) und - wenn eingestellt - trocknen lassen."""
        if not info.get("needs_drying") or not self.cfg.auto_dry_on_insert:
            return
        if self.slots.printing and not self.dryer.config.while_printing:
            return
        wet = self.wet_loaded()
        if not wet:
            return
        hours = max(h for *_, h in wet)
        name = ((spool.get("filament") or {}).get("name") or f"Spule #{spool.get('id')}")
        why = "neu – Verlauf unbekannt" if info.get("score") is None else \
            f"Feuchte-Schätzung {info['score']} %" + (f", lag {info['outside_h']:g} h draußen" if info.get("outside_h") else "")
        try:
            if await self.dryer.ensure(hours, f"Spule eingelegt: {name} (Slot {info.get('slot')}) – {why}"):
                log.info("Trockne %.1f h wegen %s (%s)", hours, name, why)
        except Exception as e:  # noqa: BLE001
            log.warning("Trocknen beim Einlegen nicht gestartet: %s", e)

    def safety_warnings(self) -> list:
        """Doppelte Buchung verhindern: Moonraker/Firmware duerfen nicht selbst buchen."""
        out = []
        if "spoolman" in (self.moon.components or []):
            out.append("Moonraker hat [spoolman] aktiv - Verbrauch wuerde doppelt gebucht. "
                       "Abschnitt [spoolman] in moonraker.conf entfernen.")
        support = (self.moon.status.get("mmu", {}) or {}).get("spoolman_support")
        if not spoolman_support_off(support):
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
                await self.dryer.evaluate()  # Automatik und Temperatur-Sicherheit
                self.humidity.tick()         # Feuchte-Verlauf, Trocknungen
                await self.moisture.tick()   # Feuchte je Spule
                await self.ace.refresh()
            except Exception:  # noqa: BLE001
                log.exception("Ticker-Fehler")


async def amain() -> None:
    cfg = Config()
    logging.basicConfig(level=getattr(logging, cfg.log_level, logging.INFO),
                        format="%(asctime)s %(levelname)-7s %(name)-10s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger().addHandler(LOG_BUFFER)      # Seite "Logs" / App-Protokoll
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
        bridge.devices.announce()
        await bridge.sm.refresh()

        runner = web.AppRunner(build_app(bridge), access_log=None)
        await runner.setup()
        await web.TCPSite(runner, cfg.http_host, cfg.http_port).start()

        tasks = [asyncio.create_task(c) for c in (bridge.moon.run(), bridge.spoolman_loop(), bridge.ticker(),
                                                         bridge.vision.run())]
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
