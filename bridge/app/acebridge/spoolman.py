"""Spoolman-REST-Client mit Cache (Spulen, Filamente)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

import aiohttp

from .config import Config

log = logging.getLogger("spoolman")


def extra_value(obj: Dict[str, Any], key: str) -> Any:
    """Spoolman speichert Zusatzfelder als JSON-Strings. None = nicht gesetzt."""
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
                log.info("Spoolman %s unter %s", self.version, self.cfg.spoolman_url)
            self.spools = await self._get("/spool", allow_archived="false")
            self.filaments = await self._get("/filament")
            if not self.connected:
                log.info("Spoolman erreichbar: %d Spulen, %d Filamente", len(self.spools), len(self.filaments))
            self.connected = True
            self.last_refresh = time.time()
            return True
        except Exception as e:  # noqa: BLE001
            if self.connected:
                log.warning("Spoolman nicht erreichbar: %s", e)
            self.connected = False
            self.version = None
            return False

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
                raise LookupError(f"Filament {filament_id} nicht gefunden")
            if r.status >= 400:
                raise RuntimeError(f"Spoolman PATCH filament {filament_id}: HTTP {r.status} {await r.text()}")
            data = await r.json()
        for i, f in enumerate(self.filaments):
            if f.get("id") == filament_id:
                self.filaments[i] = data
                break
        return data

    async def use_length(self, spool_id: int, mm: float) -> Dict[str, Any]:
        """Verbrauch buchen. Spoolman rechnet ueber Durchmesser und Dichte des Filaments
        selbst in Gramm um; negative Werte (Korrektur) sind erlaubt, Spoolman begrenzt bei 0.
        LookupError, wenn es die Spule nicht (mehr) gibt."""
        async with self.session.put(f"{self.base}/spool/{spool_id}/use", json={"use_length": round(mm, 2)},
                                    timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status == 404:
                raise LookupError(f"Spule {spool_id} nicht gefunden")
            if r.status >= 400:
                raise RuntimeError(f"Spoolman use spool {spool_id}: HTTP {r.status} {await r.text()}")
            data = await r.json()
        # Cache sofort aktualisieren, damit die Seite den neuen Rest zeigt
        for i, s in enumerate(self.spools):
            if s.get("id") == spool_id:
                self.spools[i] = data
                break
        return data

    # ------------------------------------------------------------ Abfragen auf dem Cache
    def spool(self, spool_id: int) -> Optional[Dict[str, Any]]:
        return next((s for s in self.spools if s.get("id") == spool_id), None)

    def filament(self, filament_id: int) -> Optional[Dict[str, Any]]:
        return next((f for f in self.filaments if f.get("id") == filament_id), None)

    def templates(self) -> List[Dict[str, Any]]:
        v = self.cfg.template_vendor
        return [f for f in self.filaments if (f.get("vendor") or {}).get("name") == v]

    def is_template(self, filament: Dict[str, Any]) -> bool:
        return (filament.get("vendor") or {}).get("name") == self.cfg.template_vendor
