"""Printer and ACE model for the UI ("Kobra 3 · Ready", "ACE Pro · Slots") instead of a fixed "Kobra S1".

Neither Klipper nor Rinkhals' Moonraker tells the printer model, but the slicer does: Orca writes
"; printer_model = Anycubic Kobra 3" into the config block at the end of every G-code file. At a print start the bridge
reads only the file's tail (HTTP range, at most TAIL_BYTES) and keeps the model in data/printer.json. PRINTER_NAME
(setting) wins; without both the UI says "Printer".

The ACE model comes from the driver: ACEPRO ace_instance_0.model ("ACE2 (USB Single Serial)"), Rinkhals
filament_hub.filament_hubs[].filament_model ("Anycubic Color Engine Pro", missing on the S1).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import TYPE_CHECKING, Any, Dict, Optional
from urllib.parse import quote

import aiohttp

from .i18n import tr
from .storage import save_json

if TYPE_CHECKING:
    from .config import Config
    from .moonraker import Moonraker

log = logging.getLogger("printer")

TAIL_BYTES = 128 * 1024           # Orca's config block is ~30-60 KB
_MODEL = re.compile(r"^; printer_model = (.+?)\s*$", re.M)


def model_from_gcode_tail(text: str) -> Optional[str]:
    """'; printer_model = Anycubic Kobra 3' -> 'Kobra 3' (the last one in the text)."""
    found = _MODEL.findall(text)
    if not found:
        return None
    name = found[-1].strip()
    if name.lower().startswith("anycubic "):
        name = name[len("anycubic "):].strip()
    return name[:40] or None


def ace_model(status: Dict[str, Any]) -> Optional[str]:
    """Short name of the ACE from the driver, None when it does not say."""
    raw = str((status.get("ace_instance_0") or {}).get("model") or "")
    if not raw:
        hubs = (status.get("filament_hub") or {}).get("filament_hubs")
        if isinstance(hubs, list) and hubs and isinstance(hubs[0], dict):
            raw = str(hubs[0].get("filament_model") or "")
    low = raw.lower()
    if low.startswith("ace2") or "ace 2" in low:
        return "ACE 2 Pro"
    if "color engine pro" in low or low.startswith("ace pro"):
        return "ACE Pro"
    return None


class PrinterInfo:
    def __init__(self, cfg: "Config", moon: "Moonraker", session: Optional[aiohttp.ClientSession]):
        self.cfg, self.moon, self.session = cfg, moon, session
        self.path = os.path.join(cfg.data_dir, "printer.json")
        self.learned: Optional[str] = None
        self._file: Optional[str] = None
        self._task: Optional[asyncio.Task] = None
        try:
            with open(self.path, encoding="utf-8") as fh:
                self.learned = (json.load(fh) or {}).get("model") or None
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            log.warning("printer.json unreadable: %s", e)

    def name(self) -> str:
        return (self.cfg.printer_name or "").strip() or self.learned or tr("Printer").render()

    def view(self, status: Dict[str, Any]) -> Dict[str, Any]:
        """For the UIs: printer_name None = say "Printer" in the device's language."""
        return {"printer_name": (self.cfg.printer_name or "").strip() or self.learned, "ace_model": ace_model(status)}

    def watch(self, status: Dict[str, Dict[str, Any]]) -> None:
        """On every status: a new print -> read the model from the file's tail (once per file). While nothing is
        known yet, the last print's file counts too (Klipper keeps its name after the print)."""
        ps = status.get("print_stats") or {}
        name = ps.get("filename") or ""
        current = ps.get("state") in ("printing", "paused") or not self.learned
        if current and name and name != self._file and self.session is not None:
            self._file = name
            self._task = asyncio.create_task(self._learn(name))

    async def _learn(self, name: str) -> None:
        url = f"{self.cfg.moonraker_url}/server/files/gcodes/{quote(name)}"
        headers = {**self.moon._headers(), "Range": f"bytes=-{TAIL_BYTES}"}
        try:
            async with self.session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as r:
                if r.status != 206:              # no range support: never download a whole print file for this
                    log.info("Printer model: %s answered %s to a range request - not read", name, r.status)
                    return
                text = (await r.content.read(TAIL_BYTES + 1024)).decode("utf-8", "ignore")
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.info("Printer model: %s not readable: %s", name, e)
            return
        model = model_from_gcode_tail(text)
        if model and model != self.learned:
            log.info("Printer model from the print file: %s", model)
            self.learned = model
            try:
                save_json(self.path, {"model": model, "file": name})
            except OSError as e:
                log.warning("printer.json: %s", e)
