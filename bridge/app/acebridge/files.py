"""Print files on the printer for the display: list with thumbnails, start a print (checked against the slots), reprint.

The source is Moonraker (file list + the metadata Moonraker reads from the G-code on upload: print time, weight,
thumbnails, filament type/colour per tool). Metadata is cached per file and modification time.
Before starting, the bridge compares the file's tools with the slots (ACEPRO: tool T<n> = slot n+1): same material?
roughly the same colour? Hints, not a block - the print starts only after confirmation.
"""

from __future__ import annotations

import logging
import posixpath
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from .i18n import tr
from .slots import base_type

if TYPE_CHECKING:
    from .moonraker import Moonraker
    from .slots import SlotManager

log = logging.getLogger("files")

LIST_MAX = 60                # the display shows this many newest files
COLOUR_LIMIT = 140           # RGB distance from which a colour is "clearly different" (like printcheck)
IDLE = ("standby", "complete", "cancelled", "error", "", None)


class FileError(Exception):
    def __init__(self, status: int, msg: str, confirm: Optional[str] = None):
        super().__init__(msg)
        self.status = status
        self.confirm = confirm


def _split(v: Any) -> List[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v]
    return [x.strip() for x in str(v or "").split(";")] if v else []


def _rgb(h: Optional[str]) -> Optional[Tuple[int, int, int]]:
    h = (h or "").strip().lstrip("#")[:6]
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except (ValueError, IndexError):
        return None


def colour_far(a: Optional[str], b: Optional[str]) -> bool:
    ra, rb = _rgb(a), _rgb(b)
    if not ra or not rb:
        return False
    return sum((x - y) ** 2 for x, y in zip(ra, rb, strict=True)) ** 0.5 > COLOUR_LIMIT


def tools_of(meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Tools of the file with type and colour. referenced_tools (Moonraker) = really used; without: all with a type."""
    types = _split(meta.get("filament_type"))
    colours = _split(meta.get("filament_colors") or meta.get("extruder_colors"))
    names = _split(meta.get("filament_name"))
    used = meta.get("referenced_tools")
    idx = [t for t in used if isinstance(t, int)] if isinstance(used, list) and used else list(range(len(types) or 1))
    out = []
    for t in idx:
        out.append({"tool": t, "slot": t + 1,
                    "type": types[t] if t < len(types) else (types[0] if len(types) == 1 else ""),
                    "color": (colours[t] if t < len(colours) else "").lstrip("#")[:6] or None,
                    "name": names[t] if t < len(names) else ""})
    return out


class Files:
    def __init__(self, moon: "Moonraker", slots: "SlotManager"):
        self.moon, self.slots = moon, slots
        self._meta: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    async def _metadata(self, path: str, modified: float) -> Dict[str, Any]:
        hit = self._meta.get(path)
        if hit and hit[0] == modified:
            return hit[1]
        try:
            meta = await self.moon.get_json("/server/files/metadata?filename=" + quote(path)) or {}
        except Exception as e:  # noqa: BLE001 - a file without metadata stays in the list anyway
            log.debug("Metadata %s: %s", path, e)
            meta = {}
        self._meta[path] = (modified, meta)
        return meta

    async def list(self) -> List[Dict[str, Any]]:
        raw = await self.moon.get_json("/server/files/list?root=gcodes") or []
        files = sorted((f for f in raw if str(f.get("path", "")).lower().endswith(".gcode")),
                       key=lambda f: f.get("modified") or 0, reverse=True)[:LIST_MAX]
        known = {f["path"] for f in files}
        for gone in [p for p in self._meta if p not in known]:
            del self._meta[gone]
        out = []
        for f in files:
            meta = await self._metadata(f["path"], f.get("modified") or 0)
            out.append({"path": f["path"], "modified": f.get("modified"), "size": f.get("size"),
                        "est_s": meta.get("estimated_time"), "weight_g": meta.get("filament_weight_total"),
                        "layer_height": meta.get("layer_height"), "thumb": bool(meta.get("thumbnails")),
                        "tools": tools_of(meta)})
        return out

    async def thumbnail(self, path: str) -> Optional[bytes]:
        meta = await self._metadata(path, (self._meta.get(path) or (0, {}))[0])
        thumbs = [t for t in meta.get("thumbnails") or [] if t.get("relative_path")]
        if not thumbs:
            return None
        # largest image up to 300 px (the display shows at most ~250 px), else the smallest
        fit = [t for t in thumbs if (t.get("width") or 0) <= 300]
        pick = max(fit, key=lambda t: t.get("width") or 0) if fit else min(thumbs, key=lambda t: t.get("width") or 0)
        rel = posixpath.normpath(posixpath.join(posixpath.dirname(path), pick["relative_path"]))
        if rel.startswith("..") or rel.startswith("/"):
            return None
        return await self.moon.get_bytes("/server/files/gcodes/" + quote(rel))

    async def check(self, path: str) -> Dict[str, Any]:
        """Tools of the file next to the slots, with hints (material, colour, empty slot)."""
        meta = await self._metadata(path, (self._meta.get(path) or (0, {}))[0])
        if not meta:
            raise FileError(404, tr("Unknown file"))
        assigned, _ = self.slots.assignments()
        rows = []
        for t in tools_of(meta):
            spool = assigned.get(t["slot"]) or {}
            fil = spool.get("filament") or {}
            have_type = base_type(fil.get("material") or "") if spool else ""
            have_col = (fil.get("color_hex") or "")[:6] or None
            hints = []
            if not spool:
                hints.append(tr("no spool in the slot"))
            else:
                if t["type"] and have_type and base_type(t["type"]).upper() != have_type.upper():
                    hints.append(tr("file {file}, slot {slot}", file=t["type"], slot=have_type))
                if colour_far(t["color"], have_col):
                    hints.append(tr("colour differs"))
            rows.append({**t, "have_type": have_type or None, "have_color": have_col,
                         "have_name": fil.get("name") or None, "hints": hints})
        return {"path": path, "est_s": meta.get("estimated_time"), "weight_g": meta.get("filament_weight_total"),
                "tools": rows, "ok": not any(r["hints"] for r in rows)}

    async def start(self, path: str, confirm: bool, source: str) -> Dict[str, Any]:
        state = (self.moon.status.get("print_stats") or {}).get("state")
        if not self.moon.klippy_ready:
            raise FileError(503, tr("Klipper is not ready"))
        if state not in IDLE:
            raise FileError(409, tr("A print is already running"))
        info = await self.check(path)
        if not confirm:
            raise FileError(409, tr("Start the print?"), confirm="start")
        if self.moon.console is not None:
            self.moon.console.add("command", tr("Start print: {file}", file=path), source)
        await self.moon.post_json("/printer/print/start", {"filename": path})
        return {"ok": True, "path": path, "warnings": [h for r in info["tools"] for h in r["hints"]]}
