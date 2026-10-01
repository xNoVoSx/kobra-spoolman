"""Spuelmenge der ACE pro Farbwechsel (docs/findings.md, "The firmware's own flush setting").

Bei Drucken ueber Moonraker (nackter G-Code) ignoriert die Firmware die Spuelmatrix des Slicers und
rechnet selbst - gemessen und bestaetigt:

    Farbvolumen = clamp(Orca-Farbformel(von, nach) + flush_volume_min, min, max)   [mm3]
    Spuelen     = Farbvolumen * flush_multiplier / 2,405 + Abzug                    [mm, 1,75 mm]
    erster Ladevorgang eines Drucks: fester Wert (~95 mm)

Die Orca-Farbformel ist FlushVolCalculator::calc_flush_vol aus OrcaSlicer (src/libslic3r/
FlushVolCalc.cpp, von Bambu Studio), hier ohne Orcas eigenes Minimum. Die Farben sind die, die die
ACE fuer die Slots meldet. Abzug und erster Ladevorgang lernt die Bridge aus fertigen Orca-Drucken
(dort ist "gemessen - G-Code-Soll" genau das Spuelen der Firmware).
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

log = logging.getLogger("purge")

AREA_175 = math.pi * (1.75 / 2) ** 2           # mm2, 2,405
DEFAULT_FLUSH = {"flush_multiplier": 1.0, "flush_volume_min": 107.0, "flush_volume_max": 800.0}
DEFAULT_OFFSET_MM = -3.0                        # gemessen am Orca-Druck vom 24.09.
DEFAULT_FIRST_LOAD_MM = 95.0                    # erster Ladevorgang eines Drucks
LEARN_JOBS = 20                                 # so viele fertige Orca-Drucke zum Einmessen
CONFIG_REFRESH_S = 600.0


# ====================================================================== Orca-Farbformel
def _hex_rgb(color: Optional[str]) -> Optional[Tuple[float, float, float]]:
    h = str(color or "").strip().lstrip("#")[:6]
    if len(h) != 6:
        return None
    try:
        return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return None


def _hsv(r: float, g: float, b: float) -> Tuple[float, float, float]:
    cmax, cmin = max(r, g, b), min(r, g, b)
    d = cmax - cmin
    if abs(d) < 0.001:
        h = 0.0
    elif cmax == r:
        h = 60.0 * math.fmod((g - b) / d, 6.0)
    elif cmax == g:
        h = 60.0 * ((b - r) / d + 2)
    else:
        h = 60.0 * ((r - g) / d + 4)
    s = 0.0 if abs(cmax) < 0.001 else d / cmax
    return h, s, cmax


def orca_colour_volume(src: Optional[str], dst: Optional[str]) -> Optional[float]:
    """Orcas Spuelvolumen (mm3) fuer den Wechsel src -> dst, ohne Orcas Mindestwert. None bei
    unbekannter Farbe."""
    a, b = _hex_rgb(src), _hex_rgb(dst)
    if a is None or b is None:
        return None
    h1, s1, v1 = _hsv(*a)
    h2, s2, v2 = _hsv(*b)
    dx = math.cos(math.radians(h1)) * s1 * v1 - math.cos(math.radians(h2)) * s2 * v2
    dy = math.sin(math.radians(h1)) * s1 * v1 - math.sin(math.radians(h2)) * s2 * v2
    hs_dist = min(1.2, math.hypot(dx, dy))
    from_lumi = a[0] * 0.3 + a[1] * 0.59 + a[2] * 0.11
    to_lumi = b[0] * 0.3 + b[1] * 0.59 + b[2] * 0.11
    if to_lumi >= from_lumi:
        lumi_flush = (to_lumi - from_lumi) ** 0.7 * 560.0
    else:
        lumi_flush = (from_lumi - to_lumi) * 80.0
        hs_dist = min(0.67 * v2 + 0.33 * v1, hs_dist)
    hs_flush = 230.0 * hs_dist
    # dritte Seite eines Dreiecks mit 120 Grad zwischen den beiden Anteilen
    vol = math.sqrt(hs_flush ** 2 + lumi_flush ** 2 + hs_flush * lumi_flush)
    return max(vol, 60.0)


def firmware_volume(src: Optional[str], dst: Optional[str], flush: Dict[str, float]) -> Optional[float]:
    """Farbvolumen (mm3) wie die Firmware es vor dem Multiplikator nimmt."""
    raw = orca_colour_volume(src, dst)
    if raw is None:
        return None
    lo, hi = float(flush["flush_volume_min"]), float(flush["flush_volume_max"])
    return min(max(raw + lo, lo), hi)


def change_mm(src: Optional[str], dst: Optional[str], flush: Dict[str, float], offset_mm: float) -> Optional[float]:
    """Spuelen in mm Filament (1,75 mm) fuer einen Farbwechsel, ohne Abzug-Untergrenze unter 0."""
    vol = firmware_volume(src, dst, flush)
    if vol is None:
        return None
    return max(0.0, vol * float(flush["flush_multiplier"]) / AREA_175 + offset_mm)


# ====================================================================== Modell mit Einmessen
class PurgeModel:
    """Firmware-Werte (vom Drucker) plus eingemessener Abzug und erster Ladevorgang."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.flush: Dict[str, float] = dict(DEFAULT_FLUSH)
        self.flush_source = "default"
        self.flush_read_at = 0.0
        self.offset_mm = DEFAULT_OFFSET_MM
        self.first_load_mm = DEFAULT_FIRST_LOAD_MM
        self.learned_from = 0

    # ------------------------------------------------------------ Firmware-Werte
    def set_flush_config(self, cfg: Dict[str, Any]) -> None:
        try:
            new = {"flush_multiplier": float(cfg["flush_multiplier"]),
                   "flush_volume_min": float(cfg["flush_volume_min"]),
                   "flush_volume_max": float(cfg["flush_volume_max"])}
        except (KeyError, TypeError, ValueError):
            log.warning("Spuel-Einstellung der Firmware unvollstaendig: %s", cfg)
            return
        if new != self.flush or self.flush_source != "printer":
            log.info("Spuel-Einstellung der Firmware: Multiplikator %.2f, %d–%d mm3", new["flush_multiplier"],
                     new["flush_volume_min"], new["flush_volume_max"])
        self.flush, self.flush_source, self.flush_read_at = new, "printer", self.clock()

    def config_due(self) -> bool:
        return self.flush_source != "printer" or self.clock() - self.flush_read_at > CONFIG_REFRESH_S

    # ------------------------------------------------------------ Vorhersage
    def predict(self, transitions: Iterable[Dict[str, Any]]) -> Dict[int, float]:
        """mm pro Ziel-Slot fuer Wechsel {from_color, to_color, to_slot, count}; from_color None = erster."""
        out: Dict[int, float] = {}
        for t in transitions:
            n = int(t.get("count") or 1)
            if t.get("from_slot") is None:
                mm = self.first_load_mm
            else:
                mm = change_mm(t.get("from_color"), t.get("to_color"), self.flush, self.offset_mm)
                if mm is None:
                    continue
            out[int(t["to_slot"])] = out.get(int(t["to_slot"]), 0.0) + mm * n
        return out

    # ------------------------------------------------------------ Einmessen
    def learn(self, history: List[Dict[str, Any]]) -> None:
        """Abzug pro Wechsel und ersten Ladevorgang aus fertigen Orca-Drucken (Kleinste Quadrate).

        Pro Slot und Druck: Mehrverbrauch - Summe(Farbvolumen * Multiplikator / 2,405) =
        Wechsel * Abzug + erste Ladevorgaenge * erster."""
        rows: List[Tuple[float, float, float]] = []
        jobs = 0
        for h in history:
            if jobs >= LEARN_JOBS:
                break
            if h.get("state") != "complete" or h.get("slicer") != "OrcaSlicer" or not h.get("transitions"):
                continue
            flush = h.get("flush") or None
            if not flush:
                continue
            used = False
            for s in h.get("slots") or []:
                over = s.get("overhead_mm")
                if over is None or s.get("slot", 0) <= 0:
                    continue
                base, changes, firsts, ok = 0.0, 0.0, 0.0, True
                for t in h["transitions"]:
                    if t.get("to_slot") != s["slot"]:
                        continue
                    n = float(t.get("count") or 1)
                    if t.get("from_slot") is None:
                        firsts += n
                        continue
                    vol = firmware_volume(t.get("from_color"), t.get("to_color"), flush)
                    if vol is None:
                        ok = False
                        break
                    base += n * vol * float(flush["flush_multiplier"]) / AREA_175
                    changes += n
                if ok and (changes or firsts):
                    rows.append((over - base, changes, firsts))
                    used = True
            jobs += used
        offset, first = _fit(rows)
        if offset is not None:
            self.offset_mm = max(-60.0, min(60.0, offset))
        if first is not None:
            self.first_load_mm = max(0.0, min(300.0, first))
        self.learned_from = jobs

    def state(self) -> Dict[str, Any]:
        return {"model": "colour", **{k: round(v, 3) for k, v in self.flush.items()},
                "flush_source": self.flush_source, "offset_mm": round(self.offset_mm, 1),
                "first_load_mm": round(self.first_load_mm, 1), "learned_from": self.learned_from}


def _fit(rows: List[Tuple[float, float, float]]) -> Tuple[Optional[float], Optional[float]]:
    """y = c * a + f * b, a = Abzug, b = erster Ladevorgang. Zu wenig Daten -> None fuer das Unbekannte."""
    scc = sum(c * c for _, c, _ in rows)
    sff = sum(f * f for _, _, f in rows)
    scf = sum(c * f for _, c, f in rows)
    syc = sum(y * c for y, c, _ in rows)
    syf = sum(y * f for y, _, f in rows)
    det = scc * sff - scf * scf
    if scc > 0 and sff > 0 and abs(det) > 1e-6 * max(1.0, scc * sff):
        return (syc * sff - syf * scf) / det, (scc * syf - scf * syc) / det
    # nur eine Sorte Daten: die andere Groesse bleibt beim Standardwert
    if scc > 0 and sff == 0:
        return syc / scc, None
    if sff > 0 and scc == 0:
        return None, syf / sff
    return None, None
