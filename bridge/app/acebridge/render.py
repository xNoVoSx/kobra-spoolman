"""Preview of the running print file - calculated by the bridge, not by the printer.

At print start the bridge downloads the file once through Moonraker (throttled so the printer notices nothing), splits
the G-code into extrusion segments and draws a 3D image from them in the colours the ACE reports for the slots.
Already printed parts are strong, the rest pale; the boundary comes from virtual_sdcard.file_position (byte position in
the file) - more exact than the percentage.
Plus the thumbnail the slicer writes into the file header ("; thumbnail begin ...").
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
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

import aiohttp

from . import acemodel

if TYPE_CHECKING:
    from .config import Config
    from .moonraker import Moonraker

log = logging.getLogger("render")

BED_MM = 250.0                   # Kobra S1
MAX_SEGMENTS = 600_000           # thinned out above this
BACKGROUND = (16, 18, 21)
CHECKPOINT_BYTES = 256 * 1024    # checkpoints for the remaining consumption
_MOVE = re.compile(r"^G[0123](?:\s|$)")
_AXIS = re.compile(r"([XYZEF])(-?\d*\.?\d+)")
_TOOL = re.compile(r"^T(\d+)\s*$")
_PURGE = re.compile(r"^ACE_SET_PURGE_AMOUNT\b.*\bPURGELENGTH=(-?\d*\.?\d+)")   # Orca's change G-code before every T
_THUMB = re.compile(r"^;\s*thumbnail(?:_PNG)?\s+begin\s+(\d+)x(\d+)\s+(\d+)", re.I)


# ====================================================================== G-Code zerlegen
class GcodeModel:
    """Extrusion segments (in arrays, compact) plus thumbnail and slicer colours."""

    def __init__(self) -> None:
        self.x0, self.y0, self.x1, self.y1, self.z = (array("f") for _ in range(5))
        self.tool = array("B")
        self.ext = array("f")          # filament (mm) per segment - gives the line width for the 3D view
        self.offset = array("Q")       # byte position at the end of the segment
        self.diameter = 1.75           # from "; filament_diameter = 1.75;..."
        self.layers: List[float] = []
        self.thumbnail: Optional[bytes] = None
        self._thumb_size = 0
        self.colours: List[str] = []   # from "; filament_colour = #..;#.."
        self.types: List[str] = []     # from "; filament_type = PETG;PLA" (check at print start)
        # consumption per tool (net mm, retractions subtracted) and tool changes - for "is the spool enough?"
        self.e_total: Dict[int, float] = {}
        # (byte position, from, to, purge mm from ACE_SET_PURGE_AMOUNT or None); from None = first
        self.changes: List[Tuple[int, Optional[int], int, Optional[float]]] = []
        self._purge_next: Optional[float] = None
        self._cp_off = array("Q")                                   # checkpoints: position -> consumption up to there
        self._cp_e: List[Dict[int, float]] = []
        self._tool_seen = False
        # state while reading
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
        elif code.startswith("ACE_SET_PURGE_AMOUNT"):
            m = _PURGE.match(code)
            self._purge_next = float(m.group(1)) if m else None
        else:
            m = _TOOL.match(code)
            if m:
                t = min(255, int(m.group(1)))
                if not self._tool_seen or t != self._t:
                    self.changes.append((end_offset, self._t if self._tool_seen else None, t, self._purge_next))
                    self._checkpoint(end_offset)
                self._t, self._tool_seen = t, True
                self._purge_next = None
                self._dir = None
        if self._cp_off and end_offset - self._cp_off[-1] >= CHECKPOINT_BYTES or not self._cp_off:
            self._checkpoint(end_offset)

    def _checkpoint(self, offset: int) -> None:
        self._cp_off.append(offset)
        self._cp_e.append(dict(self.e_total))

    def remaining(self, offset: Optional[int]) -> Tuple[Dict[int, float],
                                                       List[Tuple[Optional[int], int, Optional[float]]]]:
        """mm still to print per tool and the tool changes still to come (from, to, purge length) from the byte
        position on.
        Precision: one checkpoint every CHECKPOINT_BYTES and at every change."""
        import bisect
        offset = offset or 0
        i = bisect.bisect_right(self._cp_off, offset) - 1
        done = self._cp_e[i] if i >= 0 else {}
        rest = {t: max(0.0, mm - done.get(t, 0.0)) for t, mm in self.e_total.items()}
        later = [(src, dst, purge) for off, src, dst, purge in self.changes if off > offset]
        return rest, later

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
        if line.startswith("; filament_diameter ="):
            try:
                self.diameter = float(line.split("=", 1)[1].split(";")[0].split(",")[0])
            except ValueError:
                pass
        if line.startswith("; filament_type =") and not self.types:
            self.types = [t.strip() for t in line.split("=", 1)[1].split(";")]
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
        de = 0.0
        if e is not None:
            de = e - self._e if self._abs_e else e
            self._e = e if self._abs_e else self._e + e
            extruding = de > 0.0001
            self.e_total[self._t] = self.e_total.get(self._t, 0.0) + de
        dx, dy = x - self._x, y - self._y
        if extruding and (dx or dy):
            if not self.layers or abs(z - self.layers[-1]) > 1e-4:
                if not self.layers or z > self.layers[-1]:
                    self.layers.append(z)
            self._add(self._x, self._y, x, y, z, end_offset, dx, dy, de)
        else:
            self._dir = None
        self._x, self._y, self._z = x, y, z

    def _add(self, x0, y0, x1, y1, z, off, dx, dy, de=0.0) -> None:
        length = math.hypot(dx, dy)
        d = (dx / length, dy / length)
        n = len(self.x0)
        # extend a straight continuing segment instead of adding a new one (saves a lot of memory)
        if (n and self._dir is not None and self.tool[n - 1] == self._t and abs(self.z[n - 1] - z) < 1e-4
                and abs(self.x1[n - 1] - x0) < 1e-3 and abs(self.y1[n - 1] - y0) < 1e-3
                and d[0] * self._dir[0] + d[1] * self._dir[1] > 0.995):
            self.x1[n - 1], self.y1[n - 1], self.offset[n - 1] = x1, y1, off
            self.ext[n - 1] += de
            return
        self.x0.append(x0); self.y0.append(y0); self.x1.append(x1); self.y1.append(y1)  # noqa: E702
        self.z.append(z); self.tool.append(self._t); self.offset.append(off); self.ext.append(de)  # noqa: E702
        self._dir = d

    def done_index(self, offset: Optional[int]) -> int:
        """Number of segments already printed at this byte position (for the 3D view)."""
        if not offset or not len(self):
            return 0
        import bisect
        return bisect.bisect_right(self.offset, offset)

    def layer_at(self, offset: int) -> int:
        """Number (from 1) of the layer the byte position is in."""
        if not len(self):
            return 0
        lo, hi = 0, len(self) - 1
        while lo < hi:                       # first segment that ends after the position
            mid = (lo + hi) // 2
            if self.offset[mid] < offset:
                lo = mid + 1
            else:
                hi = mid
        z = self.z[lo]
        import bisect
        return bisect.bisect_left(self.layers, z - 1e-4) + 1


GEOM_MAGIC = b"KSG1"
GEOM_VERSION = 2
DEFAULT_WIDTH_MM = 0.45
MAX_GEOMETRY = 1_500_000         # the bridge sends no more segments to browser/app (thinned out)


SIMPLIFY_TOLERANCES = (0.02, 0.05, 0.1, 0.2)      # mm deviation when merging (arc height)
MAX_TURN = math.radians(35)                       # sharper bends are never merged


def simplify(model: GcodeModel, max_segments: int = MAX_GEOMETRY) -> array:
    """Merge segments for the 3D view instead of dropping them: consecutive, connected pieces of the same path (same
    tool, same height) become one segment while the arc height (chord * turn angle / 8) stays below the tolerance -
    curves made of many small pieces are reduced a lot this way, without holes.
    Result: index of the last original segment per merged segment. If even the largest tolerance is not enough,
    segments are dropped evenly (only for huge files)."""
    n = len(model)
    x0, y0, x1, y1, z, tool = model.x0, model.y0, model.x1, model.y1, model.z, model.tool
    ends = array("I")
    for tol in SIMPLIFY_TOLERANCES:
        ends = array("I")
        i = 0
        while i < n:
            sx, sy = x0[i], y0[i]
            dx, dy = x1[i] - x0[i], y1[i] - y0[i]
            prev = math.atan2(dy, dx)
            turned = 0.0
            j = i
            while j + 1 < n:
                k = j + 1
                if (tool[k] != tool[i] or abs(z[k] - z[i]) > 1e-4 or abs(x0[k] - x1[j]) > 1e-3
                        or abs(y0[k] - y1[j]) > 1e-3):
                    break
                ang = math.atan2(y1[k] - y0[k], x1[k] - x0[k])
                d = abs((ang - prev + math.pi) % (2 * math.pi) - math.pi)
                if d > MAX_TURN:
                    break
                chord = math.hypot(x1[k] - sx, y1[k] - sy)
                if chord * (turned + d) / 8 > tol:
                    break
                turned += d
                prev = ang
                j = k
            ends.append(j)
            i = j + 1
        if len(ends) <= max_segments:
            return ends
    step = -(-len(ends) // max_segments)
    return array("I", ends[::step])


def geometry_bin(model: GcodeModel, max_segments: int = MAX_GEOMETRY, ends: Optional[array] = None) -> bytes:
    """Segments for the 3D view in the browser - compact, little-endian:

    header: "KSG1", u16 version 2, u16 free, u32 segments, u32 layers, u32 step (always 1: "done" in /api/print/info
          already counts merged segments), f32 bed mm, f32 Z maximum, then f32[layers] (Z per layer)
    columns per segment: u16 x0, y0, x1, y1 (0..65535 = 0..bed mm), u16 z (0..65535 = 0..Z max), u16 layer,
          u8 tool, u8 line width (1/100 mm; 0 = unknown).  14 bytes per segment - 1.5 million ~ 21 MB, compressed
          ~ 10 MB. Version 1 had no width.
    Segments are merged (simplify); ends = index of the last original segment per segment.
    """
    import bisect
    import struct
    import sys
    if ends is None:
        ends = simplify(model, max_segments)
    starts = [0] + [e + 1 for e in ends[:-1]]
    runs = list(zip(starts, ends, strict=True))
    layers = model.layers or [0.0]
    zmax = max(max(layers), 0.01)
    q = 65535.0 / BED_MM
    qz = 65535.0 / zmax

    def col(vals, scale):
        return array("H", (min(65535, max(0, int(v * scale + 0.5))) for v in vals))
    cols = [col((model.x0[a] for a, _ in runs), q), col((model.y0[a] for a, _ in runs), q),
            col((model.x1[b] for _, b in runs), q), col((model.y1[b] for _, b in runs), q),
            col((model.z[b] for _, b in runs), qz),
            array("H", (min(65535, bisect.bisect_left(layers, model.z[b] - 1e-4)) for _, b in runs))]
    tools = array("B", (model.tool[b] for _, b in runs))
    heights = [layers[0]] + [b - a for a, b in zip(layers, layers[1:], strict=False)]
    widths = array("B", (strand_width(model, a, heights, layers, b) for a, b in runs))
    if sys.byteorder != "little":
        for c in cols:
            c.byteswap()
    head = GEOM_MAGIC + struct.pack("<HHIIIff", GEOM_VERSION, 0, len(tools), len(layers), 1, BED_MM, zmax)
    return (head + array("f", layers).tobytes() + b"".join(c.tobytes() for c in cols) + tools.tobytes()
            + widths.tobytes())


def strand_width(model: GcodeModel, i: int, heights: List[float], layers: List[float], last: Optional[int] = None) -> int:
    """Line width (1/100 mm) from filament amount, length and layer height - cross section like in Slic3r/Orca:
    a rectangle with half-round sides, so area = (w - h) * h + pi * (h/2)^2."""
    import bisect
    last = i if last is None else last
    length = ext = 0.0
    for k in range(i, last + 1):                 # merged segment: add up length and filament
        length += math.hypot(model.x1[k] - model.x0[k], model.y1[k] - model.y0[k])
        ext += model.ext[k]
    k = min(len(heights) - 1, bisect.bisect_left(layers, model.z[i] - 1e-4))
    h = heights[k] if heights[k] > 0.02 else 0.2
    if length < 0.05 or ext <= 0:
        return round(DEFAULT_WIDTH_MM * 100)
    area = ext * math.pi * (model.diameter / 2) ** 2 / length
    w = area / h + h * (1 - math.pi / 4)
    return max(5, min(255, round(w * 100)))


def parse_bytes(data: bytes) -> GcodeModel:
    """The whole file at once (tests, small files)."""
    m = GcodeModel()
    pos = 0
    for raw in data.splitlines(keepends=True):
        pos += len(raw)
        m.feed_line(raw.decode("utf-8", "ignore"), pos)
    return m


# ====================================================================== drawing
def _rgb(hexcol: Optional[str]) -> Tuple[int, int, int]:
    h = str(hexcol or "").lstrip("#")[:6]
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except (ValueError, IndexError):
        return 150, 150, 150


def display_rgb(hexcol: Optional[str]) -> Tuple[int, int, int]:
    """Filament colour for the dark background: lighten dark colours (black, dark grey) so the model stays visible;
    light colours stay as they are."""
    r, g, b = _rgb(hexcol)
    lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    if lum < 0.32:
        lift = 0.30 * (0.32 - lum) / 0.32 + 0.16
        r, g, b = (int(v + (235 - v) * lift) for v in (r, g, b))
    return r, g, b


GHOST = (44, 48, 56)


def render_png(model: GcodeModel, position: Optional[int], colours: List[Optional[str]],
               width: int = 900, height: int = 700, angle_deg: float = 32.0) -> bytes:
    """3D image (slightly angled from the front) as PNG. position = byte position of the printer (None = all printed)."""
    from PIL import Image, ImageDraw

    ss = 2                                         # draw twice as large, then scale down smoothly
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
        return xr, -(yr * TILT + z * ZK), yr          # image coordinates (before scaling) and depth

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
    # crop to the object from the second layer on - the prime line at the bed edge (first layer only)
    # would make the image small otherwise. Single-layer prints take everything.
    first = model.layers[0] if len(model.layers) > 1 else None
    for i in idx:
        z = model.z[i]
        ax, ay, d0 = proj(model.x0[i], model.y0[i], z)
        bx, by, d1 = proj(model.x1[i], model.y1[i], z)
        pts.append((z, -(d0 + d1) / 2, i, ax, ay, bx, by))
        if first is None or z > first + 1e-4:
            minx, maxx = min(minx, ax, bx), max(maxx, ax, bx)
            miny, maxy = min(miny, ay, by), max(maxy, ay, by)
    if first is not None:       # the object's foot (first layer) belongs into the crop
        maxy += 2.0
    margin = 0.08
    span = max(maxx - minx, (maxy - miny) * W / H, 1e-6)
    scale = W * (1 - 2 * margin) / span
    scale = min(scale, H * (1 - 2 * margin) / max(maxy - miny, 1e-6))
    ox = W / 2 - (minx + maxx) / 2 * scale
    oy = H / 2 - (miny + maxy) / 2 * scale

    # print bed as an outline (orientation)
    corners = [proj(0, 0, 0), proj(BED_MM, 0, 0), proj(BED_MM, BED_MM, 0), proj(0, BED_MM, 0)]
    poly = [(c[0] * scale + ox, c[1] * scale + oy) for c in corners]
    draw.polygon(poly, outline=(46, 51, 58), width=ss * 2)

    pts.sort(key=lambda p: (p[0], p[1]))        # bottom first, within the layer back first
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
            if not printed:       # not printed yet: light, slightly tinted shadow
                c = tuple(int(v * ghost_mix + g * (1 - ghost_mix) * f) for v, g in zip(c, GHOST, strict=True))
            col = cache[key] = c  # type: ignore[assignment]
        draw.line((ax * scale + ox, ay * scale + oy, bx * scale + ox, by * scale + oy), fill=col, width=lw)
        if printed and (last_printed is None or model.offset[i] > model.offset[last_printed[0]]):
            last_printed = (i, bx * scale + ox, by * scale + oy)
    if position is not None and last_printed is not None:     # nozzle
        _, nx, ny = last_printed
        r = ss * 6
        draw.ellipse((nx - r, ny - r, nx + r, ny + r), outline=(245, 184, 61), width=ss * 2)
    img = img.resize((width, height), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "PNG", optimize=False)
    return out.getvalue()


# ====================================================================== flow in the bridge
class PrintPreview:
    """Loads the file of the running print, keeps the model and a current image."""

    def __init__(self, cfg: "Config", moon: "Moonraker", session: aiohttp.ClientSession):
        self.cfg = cfg
        self.moon = moon
        self.session = session
        self.file: Optional[str] = None
        self.on_ready: Optional[Callable[[str, Dict[int, float]], None]] = None   # file read -> expected values
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

    # ------------------------------------------------------------ loading
    def watch(self, status: Dict[str, Dict[str, Any]]) -> None:
        """On every status: new print -> load the file."""
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
        self._ends, self._ends_key = None, None
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
                    log.info("Preview: %s is %.0f MB - thumbnail only", name, self.size / 1e6)
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
                    await asyncio.sleep(0.02)      # throttling (~10 MB/s): the printer should notice nothing
                if rest:
                    pos += len(rest)
                    model.feed_line(rest.decode("utf-8", "ignore"), pos)
            limit = getattr(self.cfg, "geometry_max_segments", MAX_GEOMETRY)
            ends = await asyncio.get_running_loop().run_in_executor(None, simplify, model, limit)
            self._ends, self._ends_key = ends, (len(model), limit)
            self.model, self.status = model, "ready"
            if self.on_ready:
                self.on_ready(name, dict(model.e_total))
            log.info("Preview: %s loaded (%d segments, %d layers, 3D: %d segments)", name, len(model),
                     len(model.layers), len(ends))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            self.status, self.error = "error", str(e)
            log.warning("Preview: %s cannot be loaded: %s", name, e)

    async def geometry(self) -> Optional[bytes]:
        """Segments for the 3D view - calculated once per print (in a background thread)."""
        m = self.model
        if not m or not len(m) or self.status != "ready":
            return None
        ends = await self._simplified()
        key = (self.file, len(m), len(ends))
        if getattr(self, "_geom_key", None) != key:
            self._geom = await asyncio.get_running_loop().run_in_executor(None, geometry_bin, m, len(ends), ends)
            self._geom_key = key
        return self._geom

    async def _simplified(self) -> array:
        """Merged segments (simplify) - again when the limit in the settings changed."""
        m = self.model
        limit = getattr(self.cfg, "geometry_max_segments", MAX_GEOMETRY)
        if getattr(self, "_ends_key", None) != (len(m), limit):
            self._ends = await asyncio.get_running_loop().run_in_executor(None, simplify, m, limit)
            self._ends_key = (len(m), limit)
        return self._ends

    def _done_runs(self, pos: Optional[int]) -> int:
        """Progress in merged segments: a segment is done when its last piece is printed."""
        import bisect
        m = self.model
        ends = getattr(self, "_ends", None)
        d = m.done_index(pos)
        if ends is None or getattr(self, "_ends_key", (None,))[0] != len(m):
            return d
        return bisect.bisect_left(ends, d)

    async def _thumbnail_only(self, r: aiohttp.ClientResponse) -> None:
        model = GcodeModel()
        pos = 0
        async for raw in r.content:
            pos += len(raw)
            model.feed_line(raw.decode("utf-8", "ignore"), pos)
            if model.thumbnail and pos > 2_000_000 or pos > 8_000_000:
                break
        self.model = model if model.thumbnail else None

    # ------------------------------------------------------------ drawing
    def colours(self, status: Dict[str, Dict[str, Any]]) -> List[Optional[str]]:
        """Colour per tool: ACE colour of the tool's slot (ACEPRO: T<n> = slot n+1, Rinkhals: ttg_map), else from the
        G-code."""
        out: List[Optional[str]] = []
        m = self.model
        n = acemodel.num_slots(status)
        for t in range(max(n, len(m.colours) if m else 0, 1)):
            g = acemodel.tool_slot(status, t)
            ace = acemodel.slot(status, g)["color"] if g < n else ""
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
                "done": self._done_runs(pos) if m and len(m) else 0,
                "geometry": f"{self.file}:{len(m)}:{len(getattr(self, '_ends', []) or [])}"
                if m and len(m) and self.status == "ready" else None,
                # colour per tool for the 3D view, lightened like in the bridge image (dark filament visible)
                "colours": ["%02x%02x%02x" % display_rgb(c) for c in self.colours(status)] if m else [],
                "filament_colours": ["%02x%02x%02x" % _rgb(c) for c in self.colours(status)] if m else [],
                "layer": m.layer_at(pos) if m and pos and len(m) else None,
                "thumbnail": bool(m and m.thumbnail), "size": self.size, "loaded": self.loaded_bytes}
