"""Moonraker connection (Klipper): WebSocket subscription (ACE driver, print_stats, virtual_sdcard, heaters, fans) and
HTTP for the database."""

from __future__ import annotations

import asyncio
import collections
import itertools
import json
import logging
import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Deque, Dict, Optional, Tuple

import aiohttp

from . import __version__, acemodel, clog, pa, phase, resume, startseq, switches
from .i18n import tr
from .prompts import Prompts
from .config import Config

if TYPE_CHECKING:
    from .console import Console

log = logging.getLogger("moonraker")

# printer data for card/app: single fields only, nothing that changes with every move
# (position, current speed).
SUBSCRIBE_OBJECTS = {"print_stats": None, "virtual_sdcard": None,
                     "extruder": ["temperature", "target", "power"],
                     "heater_bed": ["temperature", "target", "power"],
                     "fan": ["speed", "rpm"],
                     "gcode_move": ["speed_factor", "extrude_factor"],
                     "bed_mesh": ["profile_name"]}
# ACE driver (ACEPRO, acemodel.SUBSCRIBE), Klipper modules and the S1's extra fans - only what objects/list names
OPTIONAL_OBJECTS = {**acemodel.SUBSCRIBE, **pa.SUBSCRIBE, **resume.SUBSCRIBE, **clog.SUBSCRIBE, **switches.SUBSCRIBE,
                    **phase.SUBSCRIBE, **startseq.SUBSCRIBE,
                    "fan_generic box_fan": ["speed"], "fan_generic air_filter_fan": ["speed"]}

StatusCallback = Callable[[Dict[str, Any], bool], Awaitable[None]]


class Moonraker:
    """Keeps one WebSocket connection, a merged status cache, and calls the callback with the delta on every change.

    The callback runs in its own task (_dispatch), never in the WebSocket reader: it may call Moonraker itself (G-code,
    queries) - the reader reads the answer. Up to 3.11.0 it ran in the reader; every call from it waited 15 s for an
    answer nobody read, and the bridge processed nothing meanwhile (web UI frozen, discard/pause not arriving). Merging
    into the cache and on_status both happen in _dispatch, one by one and in order - as before, on_status sees the cache
    matching the delta (consumption needs every state change).
    """

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
        self.console: Optional["Console"] = None   # set by the bridge
        self.prompts = Prompts()                    # macro prompts (action:prompt_*) for the display
        self.cpu_samples: Deque[Tuple[float, float]] = collections.deque(maxlen=180)   # (monotonic, CPU %)
        self.components: list = []   # Moonraker components (for the warning about an active [spoolman])
        # (status, new subscription) to process; (None, False) = Klipper gone
        self._todo: Deque[Tuple[Optional[Dict[str, Any]], bool]] = collections.deque()
        self._wake = asyncio.Event()
        self._sub_ids: set = set()   # open subscribe requests: the reader queues their state (before later changes)
        self._dispatcher: Optional[asyncio.Task] = None
        self._heal_at = 0.0          # last check of the late fields (heal_late_fields)

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

    async def db_get(self, namespace: str, key: str) -> Any:
        """One value from Moonraker's database (None if it does not exist)."""
        async with self.session.get(
            f"{self.cfg.moonraker_url}/server/database/item", params={"namespace": namespace, "key": key},
            headers=self._headers(), timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            if r.status == 404:
                return None
            r.raise_for_status()
            return ((await r.json()).get("result") or {}).get("value")

    async def db_keys(self, namespace: str) -> list:
        """Keys of a namespace of Moonraker's database ([] if it does not exist)."""
        async with self.session.get(
            f"{self.cfg.moonraker_url}/server/database/item", params={"namespace": namespace},
            headers=self._headers(), timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            if r.status == 404:
                return []
            r.raise_for_status()
            value = ((await r.json()).get("result") or {}).get("value")
            return list(value) if isinstance(value, dict) else []

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
        """Mean system CPU of the Klipper computer over the last window_s seconds (None without fresh values)."""
        now = time.monotonic() if now is None else now
        vals = [c for t, c in self.cpu_samples if now - t <= window_s]
        return sum(vals) / len(vals) if vals else None

    async def get_json(self, path: str, timeout: float = 10) -> Any:
        """Reading HTTP request to Moonraker."""
        async with self.session.get(f"{self.cfg.moonraker_url}{path}", headers=self._headers(),
                                    timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            r.raise_for_status()
            data = await r.json(content_type=None)
        return data.get("result", data) if isinstance(data, dict) else data

    async def get_bytes(self, path: str, timeout: float = 10) -> bytes:
        """File from Moonraker (e.g. the thumbnail of a print file)."""
        async with self.session.get(f"{self.cfg.moonraker_url}{path}", headers=self._headers(),
                                    timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            r.raise_for_status()
            return await r.read()

    async def post_json(self, path: str, body: Dict[str, Any], timeout: float = 10) -> Any:
        """Writing HTTP request to Moonraker."""
        if self.cfg.dry_run:
            log.info("[dry-run] POST %s %s", path, json.dumps(body))
            return None
        async with self.session.post(f"{self.cfg.moonraker_url}{path}", json=body, headers=self._headers(),
                                     timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            r.raise_for_status()
            data = await r.json(content_type=None)
        return data.get("result", data) if isinstance(data, dict) else data

    async def query(self, objects: Dict[str, Any], timeout: float = 5) -> Dict[str, Any]:
        """One-off query (printer.objects.query) - for values that should not be subscribed permanently."""
        if self._ws is None or not self.klippy_ready:
            raise ConnectionError(tr("Moonraker not ready"))
        res = await self._call("printer.objects.query", {"objects": objects}, timeout=timeout)
        return (res or {}).get("status") or {}

    async def heal_late_fields(self, interval: float = 60.0, now: Optional[float] = None) -> bool:
        """Every `interval` s: query the fields that only appear after the ACE connects (acemodel.LATE_FIELDS). If the
        printer has a value the subscription never delivered, Klipper froze the field list without them - subscribe
        again (Moonraker then renews its subscription at Klipper) and take the values over. True if it subscribed."""
        now = time.monotonic() if now is None else now
        if not self.klippy_ready or now - self._heal_at < interval:
            return False
        want = {obj: list(fields) for obj, fields in acemodel.LATE_FIELDS.items() if obj in self.status}
        if not want:
            return False
        self._heal_at = now
        try:
            fresh = await self.query(want)
        except Exception as e:  # noqa: BLE001
            log.debug("Late fields not queryable: %s", e)
            return False
        missed = [f"{obj}.{k}" for obj, vals in fresh.items() for k, v in (vals or {}).items()
                  if v is not None and (self.status.get(obj) or {}).get(k) is None]
        if not missed:
            return False
        log.warning("Subscription misses %s (field list frozen before the ACE connected) - subscribing again",
                    ", ".join(missed))
        await self._subscribe()
        return True

    async def gcode(self, script: str, timeout: float = 15, source: str = "Bridge") -> None:
        """G-code over the existing WebSocket connection.
        source: who sends it - shown like that in the console."""
        if self.console is not None:
            self.console.add("command", script, source + (" (dry-run)" if self.cfg.dry_run else ""))
        if self.cfg.dry_run:
            log.info("[dry-run] gcode %s", script)
            return
        if self._ws is None or not self.klippy_ready:
            raise ConnectionError(tr("Moonraker not ready"))
        try:
            await self._call("printer.gcode.script", {"script": script}, timeout=timeout)
        except Exception as e:
            if self.console is not None:
                self.console.add("error", str(e) or e.__class__.__name__, source)
            raise

    async def action(self, method: str, label: str, source: str = "Bridge", timeout: float = 30) -> None:
        """Moonraker action like printer.print.pause; shown as label with its sender in the console."""
        if self.console is not None:
            self.console.add("command", label, source + (" (dry-run)" if self.cfg.dry_run else ""))
        if self.cfg.dry_run:
            log.info("[dry-run] %s", method)
            return
        if self._ws is None:
            raise ConnectionError(tr("Moonraker not connected"))
        # print start sequence running (kobra_seq): pause/resume/cancel go to its endpoint, which bypasses Klipper's
        # G-code lock - PAUSE/CANCEL_PRINT would wait until the start sequence is done
        params = startseq.route(method, self.status)
        if params is not None:
            method = startseq.METHOD
            log.info("Start sequence running: %s via %s", params["action"], method)
        try:
            await self._call(method, params, timeout=timeout)
        except asyncio.TimeoutError:
            if self.console is not None:
                self.console.add("response", tr("No answer yet – the printer is still working on it"), source)
            raise
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

    async def _call(self, method: str, params: Optional[dict] = None, timeout: float = 10,
                    subscribe: bool = False) -> Any:
        assert self._ws is not None
        req_id = next(self._ids)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        if subscribe:
            self._sub_ids.add(req_id)
        msg = {"jsonrpc": "2.0", "method": method, "id": req_id}
        if params is not None:
            msg["params"] = params
        await self._ws.send_str(json.dumps(msg))
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(req_id, None)
            self._sub_ids.discard(req_id)

    def _merge(self, delta: Dict[str, Any]) -> Dict[str, Any]:
        """Takes an update into the cache and returns only the fields that really changed (ACEPRO sends the slot list as
        a whole, even when only a counter changed)."""
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

    @property
    def platform(self) -> str:
        """"rinkhals" (Anycubic firmware with GoKlipper, Rinkhals' Moonraker components) or "klipper"."""
        return "rinkhals" if {"mmu_ace", "kobra"} & set(self.components) else "klipper"

    async def _objects(self) -> Dict[str, Any]:
        """What to subscribe: the base objects plus the optional ones the printer really has (objects/list).
        Rinkhals: never an absent object - subscribing to one can make GoKlipper panic (Rinkhals' kobra.py); its ACE
        objects come from acemodel.SUBSCRIBE_RINKHALS (mmu is added by Rinkhals, filament_hub is not listed)."""
        try:
            res = await self._call("printer.objects.list")
            listed = set((res or {}).get("objects") or []) if isinstance(res, dict) else set()
        except Exception as e:  # noqa: BLE001
            log.info("Object list not readable (%s)", e)
            listed = set()
        objs = dict(SUBSCRIBE_OBJECTS)
        if self.platform == "rinkhals":
            objs.update(acemodel.SUBSCRIBE_RINKHALS)
            objs.update({k: v for k, v in OPTIONAL_OBJECTS.items() if k in listed})
        elif listed:
            objs.update({k: v for k, v in OPTIONAL_OBJECTS.items() if k in listed})
        else:
            objs.update(OPTIONAL_OBJECTS)          # Klipper ignores unknown objects
        return objs

    async def _subscribe(self) -> None:
        # the reader (_reader) queues the subscription's state as soon as the answer is there - Moonraker sends changes
        # right after it, they must not be processed before the (older) state
        objs = await self._objects()
        try:
            res = await self._call("printer.objects.subscribe", {"objects": objs}, subscribe=True)
        except RuntimeError as e:
            log.info("Subscribing only to the base objects (%s)", e)
            res = await self._call("printer.objects.subscribe", {"objects": SUBSCRIBE_OBJECTS}, subscribe=True)
        snapshot = res.get("status", {}) if isinstance(res, dict) else {}
        log.info("Subscription active on %s (%s)", self.platform, ", ".join(k for k in snapshot))
        if self.console is not None and not self.console.lines:
            try:      # backlog for the console: the last lines Moonraker keeps anyway
                store = await self._call("server.gcode_store", {"count": 100})
                self.console.seed((store or {}).get("gcode_store") or [])
            except Exception as e:  # noqa: BLE001
                log.info("Console history unreadable: %s", e)

    # ------------------------------------------------------------------ status to the bridge
    def _queue(self, delta: Optional[Dict[str, Any]], full: bool = False) -> None:
        """Queue status from Moonraker for processing (never blocks). full: state of a new subscription;
        None: Klipper gone (klippy_ready off, after a still queued subscription state switched it on)."""
        self._todo.append((delta, full))
        if len(self._todo) in (500, 5000):
            log.warning("Status processing is falling behind: %d changes open", len(self._todo))
        self._wake.set()
        if self._dispatcher is None or self._dispatcher.done():
            self._dispatcher = asyncio.get_running_loop().create_task(self._dispatch())

    async def _dispatch(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            while self._todo:
                delta, full = self._todo.popleft()
                if delta is None:                # Klipper gone - after a still queued subscription state
                    self.klippy_ready = False
                    continue
                try:
                    if full:
                        self.status = {}
                        self._merge(delta)
                        self.klippy_ready = True     # subscription in place (later changes may send G-code)
                    else:
                        delta = self._merge(delta)
                        if not delta:
                            continue
                    await self.on_status(delta, full)
                except Exception:  # noqa: BLE001 - processing must never stop
                    log.exception("Error while processing the status")

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
                        res = data.get("result")
                        if data["id"] in self._sub_ids:
                            self._queue((res.get("status") or {}) if isinstance(res, dict) else {}, full=True)
                        fut.set_result(res)
                continue

            method = data.get("method")
            if method == "notify_status_update":
                params = data.get("params") or []
                if params and isinstance(params[0], dict):
                    self._queue(params[0])
            elif method == "notify_proc_stat_update":
                # Moonraker sends this by itself (~1/s): CPU without an extra query
                params = data.get("params") or []
                cpu = ((params[0] if params and isinstance(params[0], dict) else {}).get("system_cpu_usage") or {}).get("cpu")
                if isinstance(cpu, (int, float)):
                    self.cpu_samples.append((time.monotonic(), float(cpu)))
            elif method == "notify_gcode_response":
                for line in data.get("params") or []:
                    self.prompts.feed(str(line))
                    if self.console is not None:
                        self.console.add("response", str(line))
            elif method == "notify_klippy_ready":
                log.info("Klippy ready - subscribing again")
                asyncio.create_task(self._safe_subscribe())
            elif method in ("notify_klippy_shutdown", "notify_klippy_disconnected"):
                log.warning("Klippy %s", method.removeprefix("notify_klippy_"))
                self.klippy_ready = False
                self._queue(None)
                self.prompts.close()

    async def _safe_subscribe(self) -> None:
        try:
            await self._subscribe()
        except Exception as e:  # noqa: BLE001
            log.warning("Subscription failed: %s", e)

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
                    log.info("Connected to %s", self.cfg.moonraker_url)
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
                            log.info("Klippy not ready yet (%s) - waiting", (info or {}).get("klippy_state"))
                        await reader
                    finally:
                        reader.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("Moonraker not reachable: %s", e)
            finally:
                self._ws = None
                if self.connected:
                    log.warning("Connection to Moonraker lost")
                self.connected = False
                self.klippy_ready = False
                if self._todo:
                    self._queue(None)
                for fut in self._pending.values():
                    if not fut.done():
                        fut.set_exception(ConnectionError(tr("disconnected")))
                self._pending.clear()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60.0)
