"""Spoolman REST client with a cache (spools, filaments)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

import aiohttp

from .config import Config
from .i18n import tr

log = logging.getLogger("spoolman")


# extra fields on the spool the bridge maintains itself (names only used when creating them)
TAG_NR_FIELD = {"name": "Tag number", "field_type": "integer", "order": 11}
NFC_UID_FIELD = {"name": "NFC ID", "field_type": "text", "order": 10}


def extra_value(obj: Dict[str, Any], key: str) -> Any:
    """Spoolman stores extra fields as JSON strings. None = not set."""
    raw = (obj.get("extra") or {}).get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return raw


class Spoolman:
    def __init__(self, cfg: Config, session: aiohttp.ClientSession):
        self.cfg = cfg
        self.session = session
        self.base = cfg.spoolman_url + "/api/v1"
        self.spools: List[Dict[str, Any]] = []
        self.filaments: List[Dict[str, Any]] = []
        self.vendors: List[Dict[str, Any]] = []
        self._fields: Dict[str, List[Dict[str, Any]]] = {}   # extra field definitions per entity
        self.connected = False
        self.version: Optional[str] = None
        self.last_refresh = 0.0

    async def _get(self, path: str, **params) -> Any:
        async with self.session.get(self.base + path, params=params or None,
                                    timeout=aiohttp.ClientTimeout(total=15)) as r:
            r.raise_for_status()
            return await r.json()

    async def refresh(self) -> bool:
        try:
            if self.version is None:
                self.version = (await self._get("/info")).get("version")
                log.info("Spoolman %s at %s", self.version, self.cfg.spoolman_url)
            self.spools = await self._get("/spool", allow_archived="false")
            self.filaments = await self._get("/filament")
            self.vendors = await self._get("/vendor")
            self.resolve_names()
            if not self.connected:
                log.info("Spoolman reachable: %d spools, %d filaments", len(self.spools), len(self.filaments))
            self.connected = True
            self.last_refresh = time.time()
            return True
        except Exception as e:  # noqa: BLE001
            if self.connected:
                log.warning("Spoolman not reachable: %s", e)
            self.connected = False
            self.version = None
            return False

    def resolve_names(self) -> None:
        """Shelf location and template vendor when not set in the configuration: keep the names an existing install
        uses (German before 3.12), else the English defaults. Decided once, at the first answer of Spoolman."""
        from .config import SHELF_NAMES, TEMPLATE_VENDORS
        if self.cfg.template_vendor_auto:
            names = {(v.get("name") or "") for v in self.vendors}
            self.cfg.template_vendor = next((n for n in TEMPLATE_VENDORS if n in names), TEMPLATE_VENDORS[0])
            self.cfg.template_vendor_auto = False
            log.info("Template vendor in Spoolman: %s", self.cfg.template_vendor)
        if self.cfg.shelf_location_auto:
            used = {(s.get("location") or "") for s in self.spools}
            self.cfg.shelf_location = next((n for n in SHELF_NAMES if n in used), SHELF_NAMES[0])
            self.cfg.shelf_location_auto = False
            log.info("Shelf location in Spoolman: %s", self.cfg.shelf_location)

    async def fetch_spool(self, spool_id: int) -> Optional[Dict[str, Any]]:
        """One spool straight from Spoolman, archived ones too (the cache holds only active spools). None = no such
        spool."""
        async with self.session.get(f"{self.base}/spool/{spool_id}", timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status == 404:
                return None
            r.raise_for_status()
            return await r.json()

    async def patch_spool(self, spool_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        if self.cfg.dry_run:
            log.info("[dry-run] PATCH spool %s %s", spool_id, data)
            return {}
        async with self.session.patch(f"{self.base}/spool/{spool_id}", json=data,
                                      timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status >= 400:
                raise RuntimeError(f"Spoolman PATCH spool {spool_id}: HTTP {r.status} {await r.text()}")
            return await r.json()

    async def patch_filament(self, filament_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        if self.cfg.dry_run:
            log.info("[dry-run] PATCH filament %s %s", filament_id, data)
            return {}
        async with self.session.patch(f"{self.base}/filament/{filament_id}", json=data,
                                      timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status == 404:
                raise LookupError(tr("Filament {id} not found", id=filament_id))
            if r.status >= 400:
                raise RuntimeError(f"Spoolman PATCH filament {filament_id}: HTTP {r.status} {await r.text()}")
            data = await r.json()
        for i, f in enumerate(self.filaments):
            if f.get("id") == filament_id:
                self.filaments[i] = data
                break
        return data

    # ------------------------------------------------------------ creating (Android app)
    async def _write(self, method: str, path: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if self.cfg.dry_run:
            log.info("[dry-run] %s %s %s", method, path, data)
            return {"id": 0, **data}
        async with self.session.request(method, self.base + path, json=data,
                                        timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status == 404:
                raise LookupError(tr("{path} not found", path=path))
            if r.status >= 400:
                raise RuntimeError(f"Spoolman {method} {path}: HTTP {r.status} {await r.text()}")
            return await r.json()

    async def create(self, entity: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a vendor, filament or spool (entity: vendor|filament|spool)."""
        return await self._write("POST", f"/{entity}", data)

    async def fields(self, entity: str, refresh: bool = False) -> List[Dict[str, Any]]:
        """Extra field definitions (key, name, field_type, unit, choices), cached."""
        if refresh or entity not in self._fields:
            self._fields[entity] = await self._get(f"/field/{entity}")
        return self._fields[entity]

    async def ensure_field(self, entity: str, key: str, body: Dict[str, Any]) -> bool:
        """Create an extra field if it is missing. True = newly created. Never changes an existing field."""
        if any(f.get("key") == key for f in await self.fields(entity, refresh=True)):
            return False
        await self._write("POST", f"/field/{entity}/{key}", body)
        await self.fields(entity, refresh=True)
        log.info("Spoolman extra field %s.%s created", entity, key)
        return True

    async def use_length(self, spool_id: int, mm: float) -> Dict[str, Any]:
        """Book consumption. Spoolman converts to grams itself through the filament's diameter and density; negative
        values (correction) are allowed, Spoolman stops at 0. LookupError if the spool does not exist (any more)."""
        async with self.session.put(f"{self.base}/spool/{spool_id}/use", json={"use_length": round(mm, 2)},
                                    timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status == 404:
                raise LookupError(tr("Spool {id} not found", id=spool_id))
            if r.status >= 400:
                raise RuntimeError(f"Spoolman use spool {spool_id}: HTTP {r.status} {await r.text()}")
            data = await r.json()
        # update the cache at once so the page shows the new remainder
        for i, s in enumerate(self.spools):
            if s.get("id") == spool_id:
                self.spools[i] = data
                break
        return data

    # ------------------------------------------------------------ queries on the cache
    def spool(self, spool_id: int) -> Optional[Dict[str, Any]]:
        return next((s for s in self.spools if s.get("id") == spool_id), None)

    def filament(self, filament_id: int) -> Optional[Dict[str, Any]]:
        return next((f for f in self.filaments if f.get("id") == filament_id), None)

    def templates(self) -> List[Dict[str, Any]]:
        v = self.cfg.template_vendor
        return [f for f in self.filaments if (f.get("vendor") or {}).get("name") == v]

    def is_template(self, filament: Dict[str, Any]) -> bool:
        return (filament.get("vendor") or {}).get("name") == self.cfg.template_vendor
