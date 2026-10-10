"""Druckdateien am Drucker fuers Display: Liste mit Vorschaubild, Druck starten (mit Blick auf die Slots), erneut drucken.

Quelle ist Moonraker (Dateiliste + Metadaten, die Moonraker beim Hochladen aus dem G-Code liest: Druckzeit, Gewicht,
Vorschaubilder, Filamenttyp/-farbe je Werkzeug). Metadaten werden je Datei und Aenderungszeit zwischengespeichert.
Vor dem Start vergleicht die Bridge die Werkzeuge der Datei mit den Slots (ACEPRO: Werkzeug T<n> = Slot n+1):
Material gleich? Farbe ungefaehr gleich? Hinweise, kein Verbot - gestartet wird erst nach Bestaetigung.
"""

from __future__ import annotations

import logging
import posixpath
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from .slots import base_type

if TYPE_CHECKING:
    from .moonraker import Moonraker
    from .slots import SlotManager

log = logging.getLogger("files")

LIST_MAX = 60                # so viele neueste Dateien zeigt das Display
COLOUR_LIMIT = 140           # RGB-Abstand, ab dem eine Farbe "deutlich anders" ist (wie printcheck)
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
    """Werkzeuge der Datei mit Typ und Farbe. referenced_tools (Moonraker) = wirklich benutzt; ohne: alle mit Typ."""
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
        except Exception as e:  # noqa: BLE001 - Datei ohne Metadaten bleibt trotzdem in der Liste
            log.debug("Metadaten %s: %s", path, e)
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
        # groesstes Bild bis 300 px (das Display zeigt hoechstens ~250 px), sonst das kleinste
        fit = [t for t in thumbs if (t.get("width") or 0) <= 300]
        pick = max(fit, key=lambda t: t.get("width") or 0) if fit else min(thumbs, key=lambda t: t.get("width") or 0)
        rel = posixpath.normpath(posixpath.join(posixpath.dirname(path), pick["relative_path"]))
        if rel.startswith("..") or rel.startswith("/"):
            return None
        return await self.moon.get_bytes("/server/files/gcodes/" + quote(rel))

    async def check(self, path: str) -> Dict[str, Any]:
        """Werkzeuge der Datei neben den Slots, mit Hinweisen (Material, Farbe, leerer Slot)."""
        meta = await self._metadata(path, (self._meta.get(path) or (0, {}))[0])
        if not meta:
            raise FileError(404, "Datei unbekannt")
        assigned, _ = self.slots.assignments()
        rows = []
        for t in tools_of(meta):
            spool = assigned.get(t["slot"]) or {}
            fil = spool.get("filament") or {}
            have_type = base_type(fil.get("material") or "") if spool else ""
            have_col = (fil.get("color_hex") or "")[:6] or None
            hints = []
            if not spool:
                hints.append("keine Spule im Slot")
            else:
                if t["type"] and have_type and base_type(t["type"]).upper() != have_type.upper():
                    hints.append(f"Datei {t['type']}, Slot {have_type}")
                if colour_far(t["color"], have_col):
                    hints.append("Farbe weicht ab")
            rows.append({**t, "have_type": have_type or None, "have_color": have_col,
                         "have_name": fil.get("name") or None, "hints": hints})
        return {"path": path, "est_s": meta.get("estimated_time"), "weight_g": meta.get("filament_weight_total"),
                "tools": rows, "ok": not any(r["hints"] for r in rows)}

    async def start(self, path: str, confirm: bool, source: str) -> Dict[str, Any]:
        state = (self.moon.status.get("print_stats") or {}).get("state")
        if not self.moon.klippy_ready:
            raise FileError(503, "Klipper ist nicht bereit")
        if state not in IDLE:
            raise FileError(409, "Es läuft schon ein Druck")
        info = await self.check(path)
        if not confirm:
            raise FileError(409, "Druck starten?", confirm="start")
        if self.moon.console is not None:
            self.moon.console.add("command", f"Druck starten: {path}", source)
        await self.moon.post_json("/printer/print/start", {"filename": path})
        return {"ok": True, "path": path, "warnings": [h for r in info["tools"] for h in r["hints"]]}
