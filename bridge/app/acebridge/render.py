"""Vorschau der laufenden Druckdatei - gerechnet von der Bridge, nicht vom Drucker.

Beim Druckstart laedt die Bridge die Datei einmal ueber Moonraker (gedrosselt, damit der schwache Drucker
nichts merkt), zerlegt den G-Code in Extrusionsstrecken und zeichnet daraus ein 3D-Bild in den Farben,
die die ACE fuer die Slots meldet. Schon Gedrucktes ist kraeftig, der Rest blass; die Grenze kommt aus
virtual_sdcard.file_position (Byte-Position in der Datei) - genauer als die Prozentzahl.
Dazu das Vorschaubild, das der Slicer in den Dateikopf schreibt ("; thumbnail begin ...").
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import math
import re
import time
from array import array
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import aiohttp

if TYPE_CHECKING:
    from .config import Config
    from .moonraker import Moonraker

log = logging.getLogger("render")

BED_MM = 250.0                   # Kobra S1
MAX_SEGMENTS = 600_000           # darueber wird ausgeduennt
BACKGROUND = (16, 18, 21)
_MOVE = re.compile(r"^G[0123](?:\s|$)")
_AXIS = re.compile(r"([XYZEF])(-?\d*\.?\d+)")
_TOOL = re.compile(r"^T(\d+)\s*$")
_THUMB = re.compile(r"^;\s*thumbnail(?:_PNG)?\s+begin\s+(\d+)x(\d+)\s+(\d+)", re.I)


# ====================================================================== G-Code zerlegen
class GcodeModel:
    """Extrusionsstrecken (in Arrays, sparsam) plus Vorschaubild und Slicer-Farben."""

    def __init__(self) -> None:
        self.x0, self.y0, self.x1, self.y1, self.z = (array("f") for _ in range(5))
        self.tool = array("B")
        self.offset = array("Q")       # Byte-Position am Ende der Strecke
        self.layers: List[float] = []
        self.thumbnail: Optional[bytes] = None
        self._thumb_size = 0
        self.colours: List[str] = []   # aus "; filament_colour = #..;#.."
        # Zustand beim Lesen
        self._x = self._y = self._z = 0.0
        self._e = 0.0
        self._abs_xyz = True
        self._abs_e = True
        self._t = 0
        self._dir: Optional[Tuple[float, float]] = None
        self._thumb: Optional[List[str]] = None
        self._thumb_wh = 0

    def __len__(self) -> int:
        return len(self.x0)

    def feed_line(self, raw: str, end_offset: int) -> None:
        line = raw.strip()
        if not line:
            return
        if line[0] == ";":
            self._comment(line)
            return
        code = line.split(";", 1)[0].strip().upper()
        if not code:
            return
        if _MOVE.match(code):
            self._move(code, end_offset)
        elif code.startswith("G90"):
            self._abs_xyz = True
            self._abs_e = True
        elif code.startswith("G91"):
            self._abs_xyz = False
            self._abs_e = False
        elif code.startswith("M82"):
            self._abs_e = True
        elif code.startswith("M83"):
            self._abs_e = False
        elif code.startswith("G92"):
            for k, v in _AXIS.findall(code):
                if k == "E":
                    self._e = float(v)
                elif k == "Z":
                    self._z = float(v)
        else:
            m = _TOOL.match(code)
            if m:
                self._t = min(255, int(m.group(1)))
                self._dir = None

    def _comment(self, line: str) -> None:
        if self._thumb is not None:
            if re.match(r"^;\s*thumbnail(?:_PNG)?\s+end", line, re.I):
                try:
                    data = base64.b64decode("".join(self._thumb))
                    if data.startswith(b"\x89PNG") and self._thumb_wh > self._thumb_size:
                        self.thumbnail, self._thumb_size = data, self._thumb_wh
                except ValueError:
                    pass
                self._thumb = None
            else:
                self._thumb.append(line[1:].strip())
            return
        m = _THUMB.match(line)
        if m:
            self._thumb, self._thumb_wh = [], int(m.group(1)) * int(m.group(2))
            return
        if line.startswith(("; filament_colour =", "; extruder_colour =")) and not self.colours:
            self.colours = [c.strip().lstrip("#")[:6] for c in line.split("=", 1)[1].split(";")]

    def _move(self, code: str, end_offset: int) -> None:
        x, y, z, e = self._x, self._y, self._z, None
        for k, v in _AXIS.findall(code):
            f = float(v)
            if k == "X":
                x = f if self._abs_xyz else self._x + f
            elif k == "Y":
                y = f if self._abs_xyz else self._y + f
            elif k == "Z":
                z = f if self._abs_xyz else self._z + f
            elif k == "E":
                e = f
        extruding = False
        if e is not None:
            de = e - self._e if self._abs_e else e
            self._e = e if self._abs_e else self._e + e
            extruding = de > 0.0001
        dx, dy = x - self._x, y - self._y
        if extruding and (dx or dy):
            if not self.layers or abs(z - self.layers[-1]) > 1e-4:
                if not self.layers or z > self.layers[-1]:
                    self.layers.append(z)
            self._add(self._x, self._y, x, y, z, end_offset, dx, dy)
        else:
            self._dir = None
        self._x, self._y, self._z = x, y, z

    def _add(self, x0, y0, x1, y1, z, off, dx, dy) -> None:
        length = math.hypot(dx, dy)
        d = (dx / length, dy / length)
        n = len(self.x0)
        # gerade weiterlaufende Strecke verlaengern statt eine neue anzulegen (spart viel Speicher)
        if (n and self._dir is not None and self.tool[n - 1] == self._t and abs(self.z[n - 1] - z) < 1e-4
                and abs(self.x1[n - 1] - x0) < 1e-3 and abs(self.y1[n - 1] - y0) < 1e-3
                and d[0] * self._dir[0] + d[1] * self._dir[1] > 0.995):
            self.x1[n - 1], self.y1[n - 1], self.offset[n - 1] = x1, y1, off
            return
        self.x0.append(x0); self.y0.append(y0); self.x1.append(x1); self.y1.append(y1)  # noqa: E702
        self.z.append(z); self.tool.append(self._t); self.offset.append(off)  # noqa: E702
        self._dir = d

    def layer_at(self, offset: int) -> int:
        """Nummer (ab 1) der Schicht, in der die Byte-Position liegt."""
        if not len(self):
            return 0
        lo, hi = 0, len(self) - 1
        while lo < hi:                       # erste Strecke, die nach der Position endet
            mid = (lo + hi) // 2
            if self.offset[mid] < offset:
                lo = mid + 1
            else:
                hi = mid
        z = self.z[lo]
        import bisect
        return bisect.bisect_left(self.layers, z - 1e-4) + 1


def parse_bytes(data: bytes) -> GcodeModel:
    """Ganze Datei auf einmal (Tests, kleine Dateien)."""
    m = GcodeModel()
    pos = 0
    for raw in data.splitlines(keepends=True):
        pos += len(raw)
        m.feed_line(raw.decode("utf-8", "ignore"), pos)
    return m


# ====================================================================== Zeichnen
def _rgb(hexcol: Optional[str]) -> Tuple[int, int, int]:
    h = str(hexcol or "").lstrip("#")[:6]
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except (ValueError, IndexError):
        return 150, 150, 150


def display_rgb(hexcol: Optional[str]) -> Tuple[int, int, int]:
    """Filamentfarbe fuer den dunklen Hintergrund: dunkle Farben (Schwarz, Dunkelgrau) aufhellen, damit das
    Modell sichtbar bleibt; helle Farben bleiben wie sie sind."""
    r, g, b = _rgb(hexcol)
    lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    if lum < 0.32:
        lift = 0.30 * (0.32 - lum) / 0.32 + 0.16
        r, g, b = (int(v + (235 - v) * lift) for v in (r, g, b))
    return r, g, b


GHOST = (44, 48, 56)


def render_png(model: GcodeModel, position: Optional[int], colours: List[Optional[str]],
               width: int = 900, height: int = 700, angle_deg: float = 32.0) -> bytes:
    """3D-Bild (leicht schraeg von vorn) als PNG. position = Byte-Position des Druckers (None = alles gedruckt)."""
    from PIL import Image, ImageDraw

    ss = 2                                         # doppelt so gross zeichnen, dann glatt verkleinern
    W, H = width * ss, height * ss
    img = Image.new("RGB", (W, H), BACKGROUND)
    draw = ImageDraw.Draw(img)
    n = len(model)
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    TILT, ZK = 0.42, 1.0

    def proj(x: float, y: float, z: float) -> Tuple[float, float, float]:
        xr = (x - BED_MM / 2) * ca - (y - BED_MM / 2) * sa
        yr = (x - BED_MM / 2) * sa + (y - BED_MM / 2) * ca
        return xr, -(yr * TILT + z * ZK), yr          # Bildkoordinaten (vor Skalierung) und Tiefe

    if n == 0:
        img = img.resize((width, height))
        out = io.BytesIO()
        img.save(out, "PNG")
        return out.getvalue()

    step = max(1, n // MAX_SEGMENTS)
    idx = range(0, n, step)
    pts = []
    minx = miny = math.inf
    maxx = maxy = -math.inf
    for i in idx:
        z = model.z[i]
        ax, ay, d0 = proj(model.x0[i], model.y0[i], z)
        bx, by, d1 = proj(model.x1[i], model.y1[i], z)
        pts.append((z, -(d0 + d1) / 2, i, ax, ay, bx, by))
        minx, maxx = min(minx, ax, bx), max(maxx, ax, bx)
        miny, maxy = min(miny, ay, by), max(maxy, ay, by)
    margin = 0.08
    span = max(maxx - minx, (maxy - miny) * W / H, 1e-6)
    scale = W * (1 - 2 * margin) / span
    scale = min(scale, H * (1 - 2 * margin) / max(maxy - miny, 1e-6))
    ox = W / 2 - (minx + maxx) / 2 * scale
    oy = H / 2 - (miny + maxy) / 2 * scale

    # Druckbett als Umriss (Orientierung)
    corners = [proj(0, 0, 0), proj(BED_MM, 0, 0), proj(BED_MM, BED_MM, 0), proj(0, BED_MM, 0)]
    poly = [(c[0] * scale + ox, c[1] * scale + oy) for c in corners]
    draw.polygon(poly, outline=(46, 51, 58), width=ss * 2)

    pts.sort(key=lambda p: (p[0], p[1]))        # unten zuerst, innerhalb der Schicht hinten zuerst
    light = math.radians(35)
    lw = max(1, int(round(ss * 1.6)))
    ghost_mix = 0.20
    cache: Dict[Tuple[int, bool, int], Tuple[int, int, int]] = {}
    last_printed = None
    for _z, _, i, ax, ay, bx, by in pts:
        t = model.tool[i]
        printed = position is None or model.offset[i] <= position
        ang = math.atan2(model.y1[i] - model.y0[i], model.x1[i] - model.x0[i])
        shade = int((0.72 + 0.28 * abs(math.cos(ang - light))) * 20)
        key = (t, printed, shade)
        col = cache.get(key)
        if col is None:
            base = display_rgb(colours[t] if t < len(colours) else None)
            f = shade / 20
            c = tuple(min(255, int(v * f)) for v in base)
            if not printed:       # noch nicht gedruckt: heller, leicht eingefaerbter Schatten
                c = tuple(int(v * ghost_mix + g * (1 - ghost_mix) * f) for v, g in zip(c, GHOST, strict=True))
            col = cache[key] = c  # type: ignore[assignment]
        draw.line((ax * scale + ox, ay * scale + oy, bx * scale + ox, by * scale + oy), fill=col, width=lw)
        if printed and (last_printed is None or model.offset[i] > model.offset[last_printed[0]]):
            last_printed = (i, bx * scale + ox, by * scale + oy)
    if position is not None and last_printed is not None:     # Duese
        _, nx, ny = last_printed
        r = ss * 6
        draw.ellipse((nx - r, ny - r, nx + r, ny + r), outline=(245, 184, 61), width=ss * 2)
    img = img.resize((width, height), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "PNG", optimize=False)
    return out.getvalue()


# ====================================================================== Ablauf in der Bridge
class PrintPreview:
    """Laedt die Datei des laufenden Drucks, haelt das Modell und ein aktuelles Bild."""

    def __init__(self, cfg: "Config", moon: "Moonraker", session: aiohttp.ClientSession):
        self.cfg = cfg
        self.moon = moon
        self.session = session
        self.file: Optional[str] = None
        self.status = "idle"            # idle | loading | ready | too_big | error | off
        self.error: Optional[str] = None
        self.model: Optional[GcodeModel] = None
        self.png: Optional[bytes] = None
        self.png_position: Optional[int] = None
        self.rendered_at = 0.0
        self.size = 0
        self.loaded_bytes = 0
        self._task: Optional[asyncio.Task] = None
        self._render_lock = asyncio.Lock()

    # ------------------------------------------------------------ Laden
    def watch(self, status: Dict[str, Dict[str, Any]]) -> None:
        """Bei jedem Status: neuer Druck -> Datei laden."""
        if not self.cfg.render:
            self.status = "off"
            return
        ps = status.get("print_stats") or {}
        name = ps.get("filename") or ""
        if ps.get("state") in ("printing", "paused") and name and name != self.file:
            self.start(name)

    def start(self, name: str) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self.file, self.status, self.error = name, "loading", None
        self.model, self.png, self.png_position, self.loaded_bytes, self.size = None, None, None, 0, 0
        self._task = asyncio.create_task(self._load(name))

    async def _load(self, name: str) -> None:
        url = f"{self.cfg.moonraker_url}/server/files/gcodes/{quote(name)}"
        try:
            async with self.session.get(url, headers=self.moon._headers(),
                                        timeout=aiohttp.ClientTimeout(total=None, sock_read=60)) as r:
                r.raise_for_status()
                self.size = int(r.headers.get("Content-Length") or 0)
                if self.size and self.size > self.cfg.render_max_mb * 1e6:
                    self.status = "too_big"
                    log.info("Vorschau: %s ist %.0f MB - nur das Vorschaubild", name, self.size / 1e6)
                    await self._thumbnail_only(r)
                    return
                model = GcodeModel()
                pos, rest = 0, b""
                async for chunk in r.content.iter_chunked(256 * 1024):
                    lines = (rest + chunk).split(b"\n")
                    rest = lines.pop()
                    for raw in lines:
                        pos += len(raw) + 1
                        model.feed_line(raw.decode("utf-8", "ignore"), pos)
                    self.loaded_bytes = pos
                    await asyncio.sleep(0.02)      # Drosselung (~10 MB/s): der Drucker soll nichts merken
                if rest:
                    pos += len(rest)
                    model.feed_line(rest.decode("utf-8", "ignore"), pos)
            self.model, self.status = model, "ready"
            log.info("Vorschau: %s geladen (%d Strecken, %d Schichten)", name, len(model), len(model.layers))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            self.status, self.error = "error", str(e)
            log.warning("Vorschau: %s nicht ladbar: %s", name, e)

    async def _thumbnail_only(self, r: aiohttp.ClientResponse) -> None:
        model = GcodeModel()
        pos = 0
        async for raw in r.content:
            pos += len(raw)
            model.feed_line(raw.decode("utf-8", "ignore"), pos)
            if model.thumbnail and pos > 2_000_000 or pos > 8_000_000:
                break
        self.model = model if model.thumbnail else None

    # ------------------------------------------------------------ Zeichnen
    def colours(self, status: Dict[str, Dict[str, Any]]) -> List[Optional[str]]:
        """Farbe pro Werkzeug: ACE-Farbe des zugeordneten Slots, sonst die Farbe aus dem G-Code."""
        mmu = status.get("mmu") or {}
        gate_colors = mmu.get("gate_color") or []
        ttg = mmu.get("ttg_map") or list(range(len(gate_colors)))
        out: List[Optional[str]] = []
        m = self.model
        for t in range(max(len(ttg), len(m.colours) if m else 0, 1)):
            g = ttg[t] if t < len(ttg) else t
            ace = gate_colors[g] if isinstance(g, int) and 0 <= g < len(gate_colors) else None
            ace = (ace or "")[:6] or None
            out.append(ace or (m.colours[t] if m and t < len(m.colours) else None))
        return out

    async def render(self, status: Dict[str, Dict[str, Any]], force: bool = False) -> Optional[bytes]:
        if self.status != "ready" or not self.model:
            return self.png
        vsd = status.get("virtual_sdcard") or {}
        ps = status.get("print_stats") or {}
        printing = ps.get("state") in ("printing", "paused")
        pos = vsd.get("file_position") if printing else None
        if not force and self.png is not None and pos == self.png_position:
            return self.png
        if not force and self.png is not None and time.monotonic() - self.rendered_at < self.cfg.render_interval_s:
            return self.png
        async with self._render_lock:
            model, cols = self.model, self.colours(status)
            png = await asyncio.get_running_loop().run_in_executor(None, render_png, model, pos, cols)
            self.png, self.png_position, self.rendered_at = png, pos, time.monotonic()
        return self.png

    def info(self, status: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        m = self.model
        pos = (status.get("virtual_sdcard") or {}).get("file_position")
        return {"file": self.file, "status": self.status, "error": self.error,
                "segments": len(m) if m else 0, "layers": len(m.layers) if m else 0,
                "layer": m.layer_at(pos) if m and pos and len(m) else None,
                "thumbnail": bool(m and m.thumbnail), "size": self.size, "loaded": self.loaded_bytes}
