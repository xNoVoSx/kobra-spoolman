"""Moonraker-Anbindung: WebSocket-Abo (mmu, print_stats, virtual_sdcard) und HTTP fuer die Datenbank."""

from __future__ import annotations

import asyncio
import collections
import itertools
import json
import logging
import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Deque, Dict, Optional, Tuple

import aiohttp

from . import __version__
from .config import Config

if TYPE_CHECKING:
    from .console import Console

log = logging.getLogger("moonraker")

# Druckerdaten fuer Karte/App: nur einzelne Felder, nichts was sich bei jeder Bewegung aendert
# (Position, aktuelle Geschwindigkeit) - jede Aenderung kostet den schwachen Drucker etwas.
SUBSCRIBE_OBJECTS = {"mmu": None, "print_stats": None, "virtual_sdcard": None,
                     "extruder": ["temperature", "target", "power"],
                     "heater_bed": ["temperature", "target", "power"],
                     "fan": ["speed", "rpm"],
                     "gcode_move": ["speed_factor", "extrude_factor", "speed_mode"]}
# GoKlippers ACE-Rohdaten (Trockner, Feuchte) und die Zusatzluefter des S1; fehlen sie, ohne abonnieren
OPTIONAL_OBJECTS = {"filament_hub": None, "fan_generic box_fan": ["speed"], "fan_generic air_filter_fan": ["speed"]}

StatusCallback = Callable[[Dict[str, Any], bool], Awaitable[None]]


class Moonraker:
    """Haelt eine WebSocket-Verbindung, fuehrt einen zusammengefuehrten Status-Cache
    und ruft bei jeder Aenderung den Callback mit dem Delta auf."""

    def __init__(self, cfg: Config, session: aiohttp.ClientSession, on_status: StatusCallback):
        self.cfg = cfg
        self.session = session
        self.on_status = on_status
        self.status: Dict[str, Dict[str, Any]] = {}
        self.connected = False
        self.klippy_ready = False
        self._ids = itertools.count(1)
        self._pending: Dict[int, asyncio.Future] = {}
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.console: Optional["Console"] = None   # gesetzt von der Bridge
        self.cpu_samples: Deque[Tuple[float, float]] = collections.deque(maxlen=180)   # (monotonic, CPU %)
        self.components: list = []   # Moonraker-Komponenten (fuer die Warnung bei aktivem [spoolman])

    # ------------------------------------------------------------------ HTTP
    def _headers(self) -> Dict[str, str]:
        return {"X-Api-Key": self.cfg.moonraker_api_key} if self.cfg.moonraker_api_key else {}

    async def db_post(self, namespace: str, key: str, value: Any) -> None:
        if self.cfg.dry_run:
            log.info("[dry-run] db %s.%s = %s", namespace, key, json.dumps(value, ensure_ascii=False))
            return
        async with self.session.post(
            f"{self.cfg.moonraker_url}/server/database/item",
            json={"namespace": namespace, "key": key, "value": value},
            headers=self._headers(),
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            r.raise_for_status()

    async def db_delete(self, namespace: str, key: str) -> None:
        if self.cfg.dry_run:
            log.info("[dry-run] db delete %s.%s", namespace, key)
            return
        async with self.session.delete(
            f"{self.cfg.moonraker_url}/server/database/item",
            params={"namespace": namespace, "key": key},
            headers=self._headers(),
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            if r.status not in (200, 404):
                r.raise_for_status()

    def cpu(self, window_s: float = 5.0, now: Optional[float] = None) -> Optional[float]:
        """Mittlere System-CPU des Druckers der letzten window_s Sekunden (None ohne frische Werte)."""
        now = time.monotonic() if now is None else now
        vals = [c for t, c in self.cpu_samples if now - t <= window_s]
        return sum(vals) / len(vals) if vals else None

    async def get_json(self, path: str, timeout: float = 10) -> Any:
        """Lesende HTTP-Abfrage an Moonraker (z.B. GoKlippers /printer/filament_hub/get_config)."""
        async with self.session.get(f"{self.cfg.moonraker_url}{path}", headers=self._headers(),
                                    timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            r.raise_for_status()
            data = await r.json(content_type=None)
        return data.get("result", data) if isinstance(data, dict) else data

    async def post_json(self, path: str, body: Dict[str, Any], timeout: float = 10) -> Any:
        """Schreibende HTTP-Abfrage an Moonraker/GoKlipper (z.B. filament_hub/set_config)."""
        if self.cfg.dry_run:
            log.info("[dry-run] POST %s %s", path, json.dumps(body))
            return None
        async with self.session.post(f"{self.cfg.moonraker_url}{path}", json=body, headers=self._headers(),
                                     timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            r.raise_for_status()
            data = await r.json(content_type=None)
        return data.get("result", data) if isinstance(data, dict) else data

    async def gcode(self, script: str, timeout: float = 15, source: str = "Bridge") -> None:
        """G-Code ueber die bestehende WebSocket-Verbindung (Moonraker/Rinkhals faengt MMU_* ab).
        source: wer sendet - steht so in der Konsole."""
        if self.console is not None:
            self.console.add("command", script, source + (" (dry-run)" if self.cfg.dry_run else ""))
        if self.cfg.dry_run:
            log.info("[dry-run] gcode %s", script)
            return
        if self._ws is None or not self.klippy_ready:
            raise ConnectionError("Moonraker nicht bereit")
        try:
            await self._call("printer.gcode.script", {"script": script}, timeout=timeout)
        except Exception as e:
            if self.console is not None:
                self.console.add("error", str(e) or e.__class__.__name__, source)
            raise

    async def action(self, method: str, label: str, source: str = "Bridge", timeout: float = 30) -> None:
        """Moonraker-Aktion wie printer.print.pause; steht als label mit Absender in der Konsole."""
        if self.console is not None:
            self.console.add("command", label, source + (" (dry-run)" if self.cfg.dry_run else ""))
        if self.cfg.dry_run:
            log.info("[dry-run] %s", method)
            return
        if self._ws is None:
            raise ConnectionError("Moonraker nicht verbunden")
        try:
            await self._call(method, timeout=timeout)
        except Exception as e:
            if self.console is not None:
                self.console.add("error", str(e) or e.__class__.__name__, source)
            raise

    # ------------------------------------------------------------------ WebSocket
    def _ws_url(self) -> str:
        base = self.cfg.moonraker_url
        if base.startswith("https://"):
            return "wss://" + base[len("https://"):] + "/websocket"
        return "ws://" + base.removeprefix("http://") + "/websocket"

    async def _call(self, method: str, params: Optional[dict] = None, timeout: float = 10) -> Any:
        assert self._ws is not None
        req_id = next(self._ids)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        msg = {"jsonrpc": "2.0", "method": method, "id": req_id}
        if params is not None:
            msg["params"] = params
        await self._ws.send_str(json.dumps(msg))
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(req_id, None)

    def _merge(self, delta: Dict[str, Any]) -> Dict[str, Any]:
        """Uebernimmt ein Update in den Cache und liefert nur die Felder, die sich wirklich
        geaendert haben. Rinkhals schickt das komplette mmu-Objekt bei jedem Update
        (etwa zweimal pro Sekunde) - ohne diesen Filter waere jedes Update ein "mmu-Wechsel"."""
        changed: Dict[str, Any] = {}
        for obj, fields in delta.items():
            if not isinstance(fields, dict):
                continue
            cur = self.status.setdefault(obj, {})
            for k, v in fields.items():
                if k not in cur or cur[k] != v:
                    cur[k] = v
                    changed.setdefault(obj, {})[k] = v
        return changed

    async def _subscribe(self) -> None:
        try:
            res = await self._call("printer.objects.subscribe", {"objects": {**SUBSCRIBE_OBJECTS, **OPTIONAL_OBJECTS}})
        except RuntimeError as e:
            log.info("Abo ohne %s (%s)", ", ".join(OPTIONAL_OBJECTS), e)
            res = await self._call("printer.objects.subscribe", {"objects": SUBSCRIBE_OBJECTS})
        snapshot = res.get("status", {}) if isinstance(res, dict) else {}
        self.status = {}
        self._merge(snapshot)
        self.klippy_ready = True
        log.info("Abo aktiv (%s)", ", ".join(k for k in snapshot))
        if self.console is not None and not self.console.lines:
            try:      # Vorlauf fuer die Konsole: die letzten Zeilen, die Moonraker ohnehin speichert
                store = await self._call("server.gcode_store", {"count": 100})
                self.console.seed((store or {}).get("gcode_store") or [])
            except Exception as e:  # noqa: BLE001
                log.info("Konsolen-Verlauf nicht lesbar: %s", e)
        await self.on_status(snapshot, True)

    async def _reader(self) -> None:
        assert self._ws is not None
        async for msg in self._ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
                continue
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                continue

            if "id" in data and data["id"] in self._pending:
                fut = self._pending[data["id"]]
                if not fut.done():
                    if "error" in data:
                        fut.set_exception(RuntimeError(str(data["error"])))
                    else:
                        fut.set_result(data.get("result"))
                continue

            method = data.get("method")
            if method == "notify_status_update":
                params = data.get("params") or []
                if params and isinstance(params[0], dict):
                    changed = self._merge(params[0])
                    if changed:
                        await self.on_status(changed, False)
            elif method == "notify_proc_stat_update":
                # schickt Moonraker von selbst (~1/s): Drucker-CPU ohne zusaetzliche Abfrage
                params = data.get("params") or []
                cpu = ((params[0] if params and isinstance(params[0], dict) else {}).get("system_cpu_usage") or {}).get("cpu")
                if isinstance(cpu, (int, float)):
                    self.cpu_samples.append((time.monotonic(), float(cpu)))
            elif method == "notify_gcode_response":
                if self.console is not None:
                    for line in data.get("params") or []:
                        self.console.add("response", str(line))
            elif method == "notify_klippy_ready":
                log.info("Klippy bereit - abonniere neu")
                asyncio.create_task(self._safe_subscribe())
            elif method in ("notify_klippy_shutdown", "notify_klippy_disconnected"):
                log.warning("Klippy %s", method.removeprefix("notify_klippy_"))
                self.klippy_ready = False

    async def _safe_subscribe(self) -> None:
        try:
            await self._subscribe()
        except Exception as e:  # noqa: BLE001
            log.warning("Abo fehlgeschlagen: %s", e)

    async def run(self) -> None:
        delay = 2.0
        while True:
            try:
                async with self.session.ws_connect(
                    self._ws_url(), headers=self._headers(), heartbeat=30, timeout=aiohttp.ClientWSTimeout(ws_close=10)
                ) as ws:
                    self._ws = ws
                    self.connected = True
                    delay = 2.0
                    log.info("Verbunden mit %s", self.cfg.moonraker_url)
                    reader = asyncio.create_task(self._reader())
                    try:
                        await self._call("server.connection.identify", {
                            "client_name": "ace-lane-bridge", "version": __version__,
                            "type": "other", "url": "https://github.com/",
                        })
                        info = await self._call("server.info")
                        self.components = list((info or {}).get("components") or []) if isinstance(info, dict) else []
                        if isinstance(info, dict) and info.get("klippy_state") == "ready":
                            await self._subscribe()
                        else:
                            log.info("Klippy noch nicht bereit (%s) - warte", (info or {}).get("klippy_state"))
                        await reader
                    finally:
                        reader.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("Moonraker nicht erreichbar: %s", e)
            finally:
                self._ws = None
                if self.connected:
                    log.warning("Verbindung zu Moonraker getrennt")
                self.connected = False
                self.klippy_ready = False
                for fut in self._pending.values():
                    if not fut.done():
                        fut.set_exception(ConnectionError("getrennt"))
                self._pending.clear()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60.0)
