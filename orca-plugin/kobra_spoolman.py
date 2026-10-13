# /// script
# requires-python = ">=3.12"
#
# [tool.orcaslicer.plugin]
# name = "Kobra Spoolman"
# description = "Spoolman as the filament source: creates an Orca profile for every Spoolman filament, shows the ACE slots in a side panel and writes profile changes back to Spoolman after asking. Needs the ace-lane-bridge."
# author = "xNoVoSx"
# url = "https://github.com/xNoVoSx/kobra-spoolman"
# version = "0.7.1"
# ///
"""Kobra Spoolman - Orca plugin for the ace-lane-bridge.

Tasks
- Profile sync: per Spoolman filament (with an active spool) the bridge delivers the values from Spoolman. The
  plugin resolves the Orca base profile from the system profiles (JSON under <data folder>/system) and writes an
  own base profile (inherits "", filament_id SMxxxxxx) to <data folder>/user/<user>/filament/base/. Orca reads
  profiles only at start - new or changed profiles appear after a restart; the panel says so.
- Side panel: slots with spool, remaining weight, usage; a warning when filament 1-4 in Orca does not match
  slot 1-4.
- Back sync: when a managed profile is saved in Orca, the plugin asks whether the changes should go to Spoolman.
- Pairing: whatever writes to Spoolman (back sync, reporting base profiles) needs an own key. The panel asks once
  for a 6-digit code (app/web UI: Devices -> Add device); the key then lives in kobra_device.json next to the
  plugin.
- Usage forecast: after slicing the panel shows need / rest per slot (Orca's numbers as in the legend plus the
  firmware's purge per load) and warns when a spool is not enough or a used slot has no material at the printer
  (then the firmware cancels the print). Needs orca.host.slice_statistics (orca-kobra, patch 0003); without it
  only the forecast is missing.

Printing and the profile choice of the sync button are done by Orca's built-in Moonraker agent (with patch 0001 of
orca-kobra it picks the profile via lane_data.filament_id).

Language: English, German as the second language (setting "Language": auto = the bridge's language). The German
texts are in DE at the end of this file - the plugin is a single file. tests/test_i18n_plugin.py checks them.

Network and files run in an own background thread; the plugin reads preset objects only in the UI thread (panel
messages, events).
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import socket
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

import orca

PLUGIN_VERSION = "0.7.1"
MARKER = "kobra-spoolman"
DEFAULT_CONFIG = {
    "bridge_url": "http://localhost:7913",   # change in the plugin settings
    "user_folder": "default",       # sub folder in <data folder>/user (without an Orca login: default)
    "language": "auto",             # auto (the bridge's language) | en | de
    "sync_on_start": True,
    "open_panel_on_start": True,
    "ask_backsync": True,
    "poll_seconds": 5,
    "reserve_g": 5,                 # usage forecast: "tight" when less than this is left
    "warn_after_slice": True,       # Orca notification when a spool is not enough after slicing
}
ACTIVE_VARIANT = "Direct Drive Standard"    # printer_extruder_variant of the Kobra S1
# keys the plugin sets itself and that never go to Spoolman as a "change"
META_KEYS = {"name", "inherits", "from", "instantiation", "setting_id", "filament_id", "version", "type",
             "filament_settings_id", "compatible_printers", "compatible_printers_condition",
             "compatible_prints", "compatible_prints_condition", "filament_notes", "is_custom_defined",
             "base_id", "user_id", "updated_time", "filament_extruder_variant"}
FORBIDDEN = ("secret", "cert", "conf")   # Orca's sandbox blocks paths with these words

DATA_DIR = Path(__file__).resolve().parents[2]      # <data folder>/orca_plugins/<plugin>/<file>.py
PLUGIN_DIR = Path(__file__).resolve().parent
STATE_FILE = PLUGIN_DIR / "kobra_state.json"
DEVICE_FILE = PLUGIN_DIR / "kobra_device.json"       # this plugin's key at the bridge
WRITTEN_DIR = PLUGIN_DIR / "written"                 # profiles written last (for the back sync comparison)


# ====================================================================== language
LANG = {"current": "en"}


def tr(text, **params):
    """Translate an English text into the current language; {name} placeholders are filled from params."""
    s = DE.get(text, text) if LANG["current"] == "de" else text
    return s.format(**params) if params else s


def num(v, nd=1):
    """Number with nd decimals in the current language ("1.5" / "1,5"); None -> "–"."""
    if v is None:
        return "–"
    s = f"{v:.{nd}f}"
    return s.replace(".", ",") if LANG["current"] == "de" else s


def log(*args):
    print("[kobra-spoolman]", *args, flush=True)   # ends up in <data folder>/log/python_*.log


def notify(text, level="RegularNotificationLevel"):
    try:
        orca.host.ui.push_notification(getattr(orca.host.ui.NotificationLevel, level), text)
    except Exception as e:  # noqa: BLE001
        log("Notification not possible:", e, text)


# ====================================================================== helpers
def fmt_value(v):
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        s = f"{v:.6f}".rstrip("0").rstrip(".")
        return s if s not in ("", "-0") else "0"
    return str(v)


def as_list(v):
    """Profile value as a list: Orca 2.5 stores many filament values per extruder variant (6 entries).
    A text that is a JSON list (that is how it reached Spoolman via back sync before) becomes a list again."""
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v.strip().startswith("["):
        try:
            parsed = json.loads(v)
        except ValueError:
            return None
        if isinstance(parsed, list):
            return [fmt_value(x) for x in parsed]
    return None


def normalize(v):
    """Comparison form of a profile value (a list with one element or only equal values == single value)."""
    lst = as_list(v)
    if lst is not None:
        if len(lst) == 1 or (lst and all(str(x) == str(lst[0]) for x in lst)):
            v = lst[0] if lst else ""
        else:
            return json.dumps(lst, ensure_ascii=False)
    s = str(v).strip()
    try:
        f = float(s.rstrip("%"))
        return ("%" if s.endswith("%") else "") + fmt_value(f)
    except ValueError:
        return s


def safe_name(name, orca_id, material):
    name = re.sub(r'[\\/:*?"<>|]+', " ", name).strip()
    if not name or any(w in name.lower() for w in FORBIDDEN):
        name = f"Spoolman {material or 'Filament'}"
    return f"{name} ({orca_id})"


def base_key(name):
    """Comparison form of a base profile name: ignoring case, white space and the ending " @System"."""
    n = " ".join(str(name).split()).casefold()
    return n[:-len(" @system")] if n.endswith(" @system") else n


def fallback_base(prof):
    """Fallback when Spoolman names no Orca base profile (neither filament nor template): "Generic <type> @System".
    Bridges from 3.11.2 set it themselves; older bridges (2.x on Rinkhals) deliver base empty."""
    ftype = (prof.get("values") or {}).get("filament_type") or prof.get("material") or ""
    ftype = str(ftype[0] if isinstance(ftype, list) and ftype else ftype).strip()
    return f"Generic {ftype} @System" if ftype else None


class SystemProfiles:
    """Index of Orca's system filament profiles (JSON).

    Searched in this order:
      1. <data folder>/system            (copies of the vendor profiles kept by Orca)
      2. $APPDIR/resources/profiles      (profiles shipped in the AppImage, e.g. OrcaFilamentLibrary)
      3. folders Orca itself names for a base profile (Preset.file, from the UI thread)
    Profile files are named like the profile ("Generic PETG @System.json"); only when that does not fit is the
    content read.
    """

    def __init__(self, root: Path):
        self.roots = [root]
        appdir = os.environ.get("APPDIR")
        if appdir:
            self.roots.append(Path(appdir) / "resources" / "profiles")
        self.extra_roots = []
        self.by_vendor = {}   # (root, vendor) -> {name: path}
        self.loaded_at = 0.0

    def add_root(self, vendor_dir: Path):
        if vendor_dir.is_dir() and vendor_dir not in self.extra_roots:
            self.extra_roots.append(vendor_dir)
            return True
        return False

    def _vendor_dirs(self):
        for root in self.roots:
            if root.is_dir():
                for vendor_dir in sorted(root.iterdir()):
                    if (vendor_dir / "filament").is_dir():
                        yield vendor_dir
        for vendor_dir in self.extra_roots:
            yield vendor_dir

    def scan(self):
        self.by_vendor = {}
        for vendor_dir in self._vendor_dirs():
            index = {}
            for f in (vendor_dir / "filament").rglob("*.json"):
                index.setdefault(f.stem, f)
            key = (str(vendor_dir.parent), vendor_dir.name)
            if key not in self.by_vendor:
                self.by_vendor[key] = index
        self.loaded_at = time.time()

    def names(self):
        """Names of the selectable filament base profiles (for the choice in the Android app).
        Abstract parent profiles (fdm_..., ... @base) are left out."""
        if not self.by_vendor:
            self.scan()
        out = set()
        for index in self.by_vendor.values():
            out.update(n for n in index if not n.startswith("fdm_") and not n.endswith("@base"))
        return sorted(out)

    def _lookup(self, index, name):
        """Exact, else ignoring case and with/without " @System" ("eSun PLA+" -> "eSUN PLA+ @System")."""
        p = index.get(name)
        if p is not None:
            return p
        want = base_key(name)
        for n, p in index.items():
            if base_key(n) == want:
                return p
        return None

    def _find(self, name, prefer=None):
        keys = list(self.by_vendor)
        order = []
        if prefer:
            order += [k for k in keys if k == prefer]
            order += [k for k in keys if k[1] == prefer[1] and k != prefer]
        order += [k for k in keys if k[1] == "OrcaFilamentLibrary" and k not in order]
        order += [k for k in keys if k not in order]
        for k in order:
            p = self._lookup(self.by_vendor[k], name)
            if p:
                return k, p
        # slow fallback: the name is only inside the file
        for k in order:
            for p in self.by_vendor[k].values():
                try:
                    with open(p, encoding="utf-8") as fh:
                        if base_key(json.load(fh).get("name") or "") == base_key(name):
                            return k, p
                except Exception:
                    continue
        return None, None

    def resolve(self, name):
        """Fully resolved profile (inheritance merged) or None."""
        if not self.by_vendor:
            self.scan()
        chain = []
        key, path = self._find(name)
        seen = set()
        while path and str(path) not in seen:
            seen.add(str(path))
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            chain.append(data)
            parent = data.get("inherits")
            if not parent:
                break
            key, path = self._find(parent, key)
        if not chain:
            return None
        merged = {}
        for data in reversed(chain):
            merged.update(data)
        return merged


def profile_values(values):
    """The bridge's values for the profile. Orca drops filament_colour in filament presets and takes
    default_filament_colour on selection - an older bridge (up to 2.2.1) still delivers filament_colour."""
    values = dict(values)
    legacy = values.pop("filament_colour", None)
    if legacy not in (None, "") and values.get("default_filament_colour") in (None, ""):
        values["default_filament_colour"] = legacy
    return values


def build_profile_json(base, prof, name):
    """Orca base profile + Spoolman values -> complete own base profile."""
    out = {k: v for k, v in base.items()
           if k not in ("setting_id", "base_id", "user_id", "updated_time", "filament_colour")}
    for key, val in profile_values(prof["values"]).items():
        if key == "filament_id":
            continue
        cur = out.get(key)
        lst = as_list(val)
        if lst is not None:                       # a list (per variant) stays a list
            out[key] = lst
            continue
        s = fmt_value(val)
        out[key] = s if (cur is not None and not isinstance(cur, list)) else [s]
    out.update({
        "type": "filament",
        "name": name,
        "inherits": "",
        "from": "User",
        "instantiation": "true",
        "filament_id": prof["orca_id"],
        "filament_settings_id": [name],
        "compatible_printers": [],
        "compatible_printers_condition": "",
        "filament_notes": [f"{MARKER}: managed via Spoolman ({prof['orca_id']}, filament #{prof['filament_id']}). "
                           "Changes made here go to Spoolman after asking."],
    })
    out.setdefault("version", base.get("version", "2.5.0.0"))
    return out


def _variant_value(v, idx):
    """Value of the active extruder variant if v is a list per variant; else v unchanged."""
    lst = as_list(v)
    if lst is not None and len(lst) > 1:
        return lst[idx] if idx < len(lst) else lst[0]
    return v


def diff_profiles(written, saved):
    """Keys whose value the user changed in Orca: {key: new value (text)}.

    Only keys of our written file count: it contains the whole base profile. Whatever is missing there, Orca adds
    as its own default when saving (Orca 2.5: ~80 keys, many per extruder variant) - that is not a change by the
    user."""
    changes = {}
    idx_a, idx_b = active_variant_index(written), active_variant_index(saved)
    for key in written:
        if key in META_KEYS:
            continue
        a, b = written.get(key), saved.get(key)
        if b is None:
            continue
        # In its UI Orca changes only the active variant ("Direct Drive Standard" on the S1) - Spoolman holds one
        # value per field, so exactly that one counts (a list as text would otherwise clear the field).
        # Treat both sides the same: otherwise a list with different values per variant
        # (e.g. filament_max_volumetric_speed) is never equal and every sync rewrites the profile
        # (found by MineTech13, issue #2).
        a, b = _variant_value(a, idx_a), _variant_value(b, idx_b)
        if normalize(a) != normalize(b):
            v = as_list(b)
            v = v[0] if v else b
            changes[key] = v if isinstance(v, str) else fmt_value(v)
    return changes


def active_variant_index(profile):
    """Index of the printer's extruder variant in filament_extruder_variant (Kobra S1: Direct Drive Standard)."""
    variants = profile.get("filament_extruder_variant") or []
    try:
        return list(variants).index(ACTIVE_VARIANT)
    except ValueError:
        return 0


# ====================================================================== usage forecast
# Rinkhals: the Anycubic firmware purges by itself at every load and ignores Orca's matrix. The bridge sends its purge
# model (bridge purge.py, docs/findings.md); the colour formula is Orca's FlushVolCalculator::calc_flush_vol.
DEFAULT_FLUSH = {"flush_multiplier": 1.0, "flush_volume_min": 107.0, "flush_volume_max": 800.0}
AREA_175 = 3.141592653589793 * (1.75 / 2) ** 2


def _hex_rgb(color):
    h = str(color or "").strip().lstrip("#")[:6]
    if len(h) != 6:
        return None
    try:
        return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return None


def _hsv(r, g, b):
    import math
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
    return h, (0.0 if abs(cmax) < 0.001 else d / cmax), cmax


def purge_change_mm(src, dst, flush, offset_mm):
    """Firmware purge in mm (1.75 mm) for the change src -> dst (colours RRGGBB), None for an unknown colour.
    Same as the bridge's purge.change_mm."""
    import math
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
    vol = max(math.sqrt(hs_flush ** 2 + lumi_flush ** 2 + hs_flush * lumi_flush), 60.0)
    lo, hi = float(flush["flush_volume_min"]), float(flush["flush_volume_max"])
    vol = min(max(float(int(vol + lo)), lo), hi)
    return max(0.0, vol * float(flush["flush_multiplier"]) / AREA_175 + offset_mm)


def _firmware_purge(used, stats, slots, model):
    """mm of firmware purge per filament index: from Orca's transitions (patch 0003) or, without them, from the colours
    of the used filaments (first load shared, then the mean of the changes from the others)."""
    flush = {k: float(model.get(k, v)) for k, v in DEFAULT_FLUSH.items()}
    offset = float(model.get("offset_mm", -3.0))
    first = float(model.get("first_load_mm", 95.0))
    colours = {int(s["slot"]) - 1: (s.get("ace_color") or s.get("color")) for s in slots or [] if s.get("slot")}
    ids = [f["index"] for f in used]

    def change(i, j):
        mm = purge_change_mm(colours.get(i), colours.get(j), flush, offset)
        return first if mm is None else mm

    transitions = (stats or {}).get("transitions")
    if transitions:
        out = {i: 0.0 for i in ids}
        for t in transitions:
            to, n = int(t["to"]), int(t.get("count") or 1)
            out[to] = out.get(to, 0.0) + n * (first if t.get("from") is None else change(int(t["from"]), to))
        return out
    loads = {f["index"]: max(1, int(f.get("loads") or 1)) for f in used}
    share = 1.0 / len(ids) if ids else 0.0
    out = {}
    for j in ids:
        others = [change(i, j) for i in ids if i != j]
        per = sum(others) / len(others) if others else first
        out[j] = share * first + max(0.0, loads[j] - share) * per
    return out


def _mm_to_g(mm, diameter, density):
    r = (diameter or 1.75) / 2
    return mm * 3.141592653589793 * r * r * (density or 1.24) / 1000


def build_forecast(stats, slots, reserve_g=5.0, purge=None):
    """Need per slot for the sliced print.

    stats  - result of orca.host.slice_statistics() (volumes in mm3, filament index from 0)
    slots  - slots from /api/orca/state (slot, name, spool_id, remaining_weight)
    purge  - /api/orca/state "purge" of a Rinkhals bridge ({"model": ...}): the firmware purges by itself, the
             forecast adds it per colour change (purge_g); None under Klipper + ACEPRO (Orca's matrix is the purge)

    Filament N in Orca belongs to slot N (that is how the sync button sets it). The values are the same as in Orca's
    legend: model, support, flushed, tower, total = their sum (not total_volumes_per_extruder - that distributes
    the tower differently at a change). The ACE's purge is under "flushed": the printer profile's change-filament
    G-code reports it to Orca with "; EXTERNAL_PURGE <mm>" (load + purge volume from Orca's matrix). If that is
    missing although there are changes, purge_missing is set.
    """
    by_slot = {s["slot"]: s for s in slots or []}

    def orca_mm3(f):
        return sum(f.get(k) or 0 for k in ("model_mm3", "support_mm3", "flush_mm3", "tower_mm3"))

    used = [f for f in (stats or {}).get("filaments", []) if orca_mm3(f) > 0]
    transitions = (stats or {}).get("transitions") or []
    if transitions:                             # every change on its own (patch 0003), first load from=None
        loads = {f["index"]: 0 for f in used}
        for t in transitions:
            loads[int(t["to"])] = loads.get(int(t["to"]), 0) + int(t.get("count") or 1)
        changes = sum(int(t.get("count") or 1) for t in transitions if t.get("from") is not None)
    else:
        loads = {f["index"]: int(f.get("loads") or 0) for f in used}
        changes = int((stats or {}).get("total_filament_changes") or 0)
    purged = sum((f.get("flush_mm3") or 0) + (f.get("tower_mm3") or 0) for f in used)
    model = purge.get("model") if isinstance(purge, dict) else None
    firmware = _firmware_purge(used, stats, slots, model) if isinstance(model, dict) and used else None

    rows, short, tight = [], [], []
    for f in sorted(used, key=lambda x: x["index"]):
        slot_no = int(f["index"]) + 1
        dens = f.get("density") or 1.24

        def g(mm3, dens=dens):
            return (mm3 or 0) * dens / 1000

        row = {
            "slot": slot_no,
            "model_g": round(g(f.get("model_mm3")), 2),
            "support_g": round(g(f.get("support_mm3")), 2),
            "flush_g": round(g(f.get("flush_mm3")), 2),
            "tower_g": round(g(f.get("tower_mm3")), 2),
            "orca_g": round(g(orca_mm3(f)), 2),
            "loads": loads.get(f["index"], 0),
        }
        row["purge_g"] = round(firmware.get(f["index"], 0.0) * AREA_175 * dens / 1000, 2) if firmware else 0.0
        row["need_g"] = round(row["orca_g"] + row["purge_g"], 1)
        s = by_slot.get(slot_no)
        if s is None:
            row["status"] = "noslot"
        elif firmware is not None and s.get("present") and not s.get("ace_material"):
            row["status"] = "nomaterial"          # Rinkhals: GoKlipper cancels a print with an empty slot material
        elif not s.get("spool_id"):
            row["status"] = "nospool"
        else:
            row["name"] = s.get("name")
            rest = s.get("remaining_weight")
            row["remaining_g"] = None if rest is None else round(float(rest), 1)
            if rest is None:
                row["status"] = "unknown"
            elif rest < row["need_g"]:
                row["status"] = "short"
                short.append(slot_no)
            elif rest - row["need_g"] < max(float(reserve_g or 0), 0.05 * row["need_g"]):
                row["status"] = "tight"
                tight.append(slot_no)
            else:
                row["status"] = "ok"
        rows.append(row)
    return {
        "plate": (stats or {}).get("plate_index"),
        "rows": rows,
        "short": short,
        "tight": tight,
        "changes": changes,
        "loads_exact": bool(transitions),
        "firmware_purge": firmware is not None,
        "purge_missing": firmware is None and changes > 0 and purged <= 0,
        "total_g": round(sum(r["need_g"] for r in rows), 1),
    }


def forecast_warnings(fc):
    """Short texts for notifications and the panel."""
    out = []
    for r in fc.get("rows", []):
        if r["status"] == "short":
            out.append(tr("Slot {slot}: needs about {need} g, the spool has {rest} g left",
                          slot=r["slot"], need=num(r["need_g"], 0), rest=num(r["remaining_g"], 0)))
        elif r["status"] == "tight":
            out.append(tr("Slot {slot}: tight – needs about {need} g, {rest} g left",
                          slot=r["slot"], need=num(r["need_g"], 0), rest=num(r["remaining_g"], 0)))
        elif r["status"] == "nospool":
            out.append(tr("Slot {slot} is used but has no spool assigned", slot=r["slot"]))
        elif r["status"] == "noslot":
            out.append(tr("Filament {slot} has no ACE slot", slot=r["slot"]))
        elif r["status"] == "nomaterial":
            out.append(tr("Slot {slot}: no material is set at the printer – the print gets cancelled", slot=r["slot"]))
    if fc.get("purge_missing"):
        out.append(tr("The ACE purge is missing in Orca's numbers – create the printer profile again (make-profile.py)"))
    return out


def read_slice_statistics(require_valid=True):
    """orca.host.slice_statistics (orca-kobra patch 0003) - None if missing / not sliced."""
    fn = getattr(orca.host, "slice_statistics", None)
    if fn is None:
        return None
    try:
        return fn(-1, require_valid)
    except Exception as e:  # noqa: BLE001
        log("Slice statistics not readable:", e)
        return None


# ====================================================================== pairing
class NotPaired(Exception):
    """The bridge refuses: this plugin is not (or no longer) paired."""


class DeviceKey:
    """The plugin's key at the bridge. Valid only for the bridge address it was paired with."""

    def __init__(self, path: Path):
        self.path = path
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            self.data = {}

    def token(self, bridge_url):
        if self.data.get("token") and self.data.get("bridge_url") == str(bridge_url).rstrip("/"):
            return self.data["token"]
        return None

    def headers(self, bridge_url):
        t = self.token(bridge_url)
        return {"Authorization": f"Bearer {t}"} if t else {}

    def save(self, bridge_url, token, device):
        self.data = {"bridge_url": str(bridge_url).rstrip("/"), "token": token, "device": device}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def forget(self):
        self.data = {}
        self.path.unlink(missing_ok=True)


def device_name():
    try:
        host = socket.gethostname()
    except Exception:  # noqa: BLE001
        host = ""
    return f"Orca plugin ({host})" if host else "Orca plugin"


# ====================================================================== core
class Core:
    """One instance per Orca session: bridge queries, profile sync, state."""

    def __init__(self, get_config):
        self.get_config = get_config
        self.lock = threading.RLock()
        self.state = self._load_state()
        self.bridge_state = None
        self.bridge_error = None
        self.last_sync = None          # {"at", "written", "deleted", "errors"}
        self.restart_needed = False
        self.stop = threading.Event()
        self.sync_request = threading.Event()
        self.wake = threading.Event()
        self.saved_queue = queue.Queue()   # profile names saved in Orca (back sync)
        self.system = SystemProfiles(DATA_DIR / "system")
        self.thread = None
        self.missing_bases = set()     # base profiles not found in the last sync
        self.slice = None              # {"stats", "at", "from_event"} - last slice result
        self.slice_warned = None       # warnings a notification already came for
        self.key = DeviceKey(DEVICE_FILE)
        self.paired = None             # None = not checked yet
        self.paired_checked = 0.0
        self.pair_code = None          # from the panel, redeemed in the background
        self.pair_msg = None           # {"error": bool, "text": str}
        self.update_language()

    # ---------------------------------------------------------------- state
    def _load_state(self):
        try:
            with open(STATE_FILE, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {"profiles": {}}

    def _save_state(self):
        tmp = STATE_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.state, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE_FILE)

    def cfg(self, key):
        try:
            c = json.loads(self.get_config() or "{}")
        except Exception:
            c = {}
        return c.get(key, DEFAULT_CONFIG[key])

    def update_language(self):
        """Language of the plugin's texts: the setting, with auto = the bridge's language (bridge 3.12+)."""
        want = str(self.cfg("language") or "auto")
        if want not in ("en", "de"):
            want = (self.bridge_state or {}).get("language") or "en"
        LANG["current"] = want if want in ("en", "de") else "en"

    def user_filament_dir(self):
        return DATA_DIR / "user" / str(self.cfg("user_folder")) / "filament" / "base"

    def managed(self):
        """orca_id -> entry (name, file)"""
        return self.state.setdefault("profiles", {})

    def managed_by_name(self, name):
        for oid, e in self.managed().items():
            if e.get("name") == name:
                return oid, e
        return None, None

    # ---------------------------------------------------------------- HTTP
    def http(self, method, path, body=None, timeout=4):
        base = str(self.cfg("bridge_url")).rstrip("/")
        data = json.dumps(body).encode() if body is not None else None
        headers = dict(self.key.headers(base))
        if str(self.cfg("language")) in ("en", "de"):
            headers["X-Lang"] = str(self.cfg("language"))   # else the bridge answers in its own language
        if data:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode("utf-8")).get("error") or str(e)
            except Exception:  # noqa: BLE001
                msg = str(e)
            if e.code in (401, 403):
                self.paired = False
                raise NotPaired(msg) from None
            raise RuntimeError(f"{e.code}: {msg}") from None

    # ---------------------------------------------------------------- pairing
    def check_pairing(self, force=False):
        """Ask every few minutes whether the key is still valid (bridge only, never the printer)."""
        if not force and self.paired is not None and time.time() - self.paired_checked < 300:
            return
        self.paired_checked = time.time()
        if not self.key.token(self.cfg("bridge_url")):
            self.paired = False
            return
        try:
            st = self.http("GET", "/api/auth/status")
        except Exception:  # noqa: BLE001
            return
        self.paired = bool(st and st.get("device"))
        if not self.paired:
            log("Key no longer valid - pair again")
            self.key.forget()

    def redeem_pair_code(self):
        code, self.pair_code = self.pair_code, None
        base = str(self.cfg("bridge_url")).rstrip("/")
        try:
            res = self.http("POST", "/api/auth/pair", {"code": code, "name": device_name(), "kind": "plugin"}, timeout=6)
        except (NotPaired, RuntimeError) as e:
            self.pair_msg = {"error": True, "text": str(e)}
            self.paired = False
            return
        except Exception as e:  # noqa: BLE001
            self.pair_msg = {"error": True, "text": tr("Bridge not reachable ({error})", error=e)}
            return
        self.key.save(base, res["token"], res.get("device"))
        self.paired, self.paired_checked = True, time.time()
        self.pair_msg = {"error": False, "text": tr("Paired as “{name}”.",
                                                    name=(res.get("device") or {}).get("name", device_name()))}
        self.state.pop("bases_reported", None)   # report the base profiles now
        log("Paired with the bridge")

    # ---------------------------------------------------------------- background
    def start(self):
        if self.thread and self.thread.is_alive():
            return
        if self.cfg("sync_on_start"):
            self.sync_request.set()
        self.thread = threading.Thread(target=self._run, name="kobra-spoolman", daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stop.is_set():
            try:
                self.bridge_state = self.http("GET", "/api/orca/state")
                self.bridge_error = None
                known = self.state.get("profiles_hash")
                if known and self.bridge_state.get("profiles_hash") != known and not self.sync_request.is_set():
                    self.bridge_state["profiles_outdated"] = True
            except Exception as e:  # noqa: BLE001
                self.bridge_error = tr("Bridge not reachable ({error})", error=f"{e.__class__.__name__}: {e}")
            self.update_language()
            if self.pair_code:
                self.redeem_pair_code()
            if not self.bridge_error:
                self.check_pairing()
            if self.sync_request.is_set():
                self.sync_request.clear()
                try:
                    self.sync_profiles()
                except Exception as e:  # noqa: BLE001
                    log("Sync failed:", e, traceback.format_exc())
                    self.last_sync = {"at": time.strftime("%H:%M:%S"), "written": [], "deleted": [],
                                      "errors": [tr("Sync failed: {error}", error=e)]}
            while True:
                try:
                    name = self.saved_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    self.handle_saved(name)
                except Exception as e:  # noqa: BLE001
                    log("Back sync failed:", e, traceback.format_exc())
            self.wake.wait(max(2, int(self.cfg("poll_seconds"))))
            self.wake.clear()

    # ---------------------------------------------------------------- profile sync
    def sync_profiles(self):
        with self.lock:
            data = self.http("GET", "/api/orca/profiles", timeout=10)
            self.system.scan()
            target = self.user_filament_dir()
            target.mkdir(parents=True, exist_ok=True)
            WRITTEN_DIR.mkdir(parents=True, exist_ok=True)
            managed = self.managed()
            written, deleted, errors = [], [], []
            wanted = set()
            missing = set()
            for prof in data.get("profiles", []):
                oid = prof["orca_id"]
                wanted.add(oid)
                base_name = prof.get("base") or fallback_base(prof)
                base = self.system.resolve(base_name) if base_name else None
                if base is None:
                    if not base_name:
                        errors.append(tr("{name}: no Orca base profile in Spoolman and no material – set “Orca base "
                                         "profile” on the filament or create a template (spoolman_setup.py)",
                                         name=prof["display_name"]))
                        continue
                    missing.add(base_name)
                    if prof.get("base"):
                        errors.append(tr("{name}: Orca base profile “{base}” not found in Orca",
                                         name=prof["display_name"], base=base_name))
                    else:
                        errors.append(tr("{name}: Orca base profile “{base}” (fallback, because none is set in "
                                         "Spoolman) not found in Orca", name=prof["display_name"], base=base_name))
                    continue
                if not prof.get("base"):
                    log(f"{prof['display_name']}: no Orca base profile in Spoolman - using {base_name}")
                name = safe_name(prof["display_name"], oid, prof.get("material"))
                profile = build_profile_json(base, prof, name)
                old = managed.get(oid)
                path = target / f"{name}.json"
                if old and old.get("name") != name:          # renamed: old file goes
                    self._remove_files(Path(old["file"]))
                cache = WRITTEN_DIR / f"{oid}.json"
                prev = None
                if path.exists():
                    # Compare with the file on disk: if someone changed the profile in Orca and declined the back
                    # sync, the sync resets it to the Spoolman values.
                    try:
                        prev = json.loads(path.read_text(encoding="utf-8"))
                    except Exception:
                        prev = None
                if prev is not None and not diff_profiles(prev, profile) and not diff_profiles(profile, prev):
                    managed[oid] = {"name": name, "file": str(path), "hash": prof["hash"]}
                    continue
                text = json.dumps(profile, ensure_ascii=False, indent="\t")
                path.write_text(text + "\n", encoding="utf-8")
                path.with_suffix(".info").write_text(
                    f"sync_info = \nuser_id = \nsetting_id = \nbase_id = \nupdated_time = {int(time.time())}\n",
                    encoding="utf-8")
                cache.write_text(text, encoding="utf-8")
                managed[oid] = {"name": name, "file": str(path), "hash": prof["hash"]}
                written.append(name)
            # remove profiles of filaments without an active spool (own files only)
            for oid in [o for o in managed if o not in wanted]:
                entry = managed.pop(oid)
                if self._remove_files(Path(entry["file"])):
                    deleted.append(entry["name"])
                (WRITTEN_DIR / f"{oid}.json").unlink(missing_ok=True)
            self.state["profiles_hash"] = data.get("hash")
            self.missing_bases = missing
            self._report_bases()
            self._save_state()
            if written or deleted:
                self.restart_needed = True
            self.last_sync = {"at": time.strftime("%H:%M:%S"), "written": written, "deleted": deleted,
                              "errors": errors}
            log(f"Sync: {len(written)} written, {len(deleted)} removed, {len(errors)} errors")
            return self.last_sync

    def _report_bases(self):
        """Report the base profile names to the bridge, only when they changed."""
        names = self.system.names()
        digest = hashlib.sha1("\n".join(names).encode("utf-8")).hexdigest()[:12]
        if not names or self.state.get("bases_reported") == digest:
            return
        if self.paired is False:
            return   # the plugin reports after pairing
        try:
            self.http("POST", "/api/orca/bases", {"names": names}, timeout=10)
            self.state["bases_reported"] = digest
            log(f"{len(names)} Orca base profiles reported to the bridge")
        except NotPaired:
            log("Reporting base profiles: plugin not paired")
        except Exception as e:  # noqa: BLE001
            log("Reporting base profiles failed:", e)

    def _remove_files(self, path: Path):
        try:
            with open(path, encoding="utf-8") as fh:
                notes = json.load(fh).get("filament_notes") or []
            if not any(MARKER in str(n) for n in notes):
                return False   # not ours - never touch
        except Exception:
            return False
        path.unlink(missing_ok=True)
        path.with_suffix(".info").unlink(missing_ok=True)
        return True

    # ---------------------------------------------------------------- back sync
    def pending_changes(self, preset_name):
        """After saving in Orca: differences between Orca's file and our state."""
        oid, entry = self.managed_by_name(preset_name)
        if not oid:
            return None, None
        try:
            saved = json.loads(Path(entry["file"]).read_text(encoding="utf-8"))
            written = json.loads((WRITTEN_DIR / f"{oid}.json").read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            log("Back sync: files not readable:", e)
            return oid, None
        return oid, diff_profiles(written, saved)

    def handle_saved(self, name):
        """Back sync in the background thread (dialogs are thread-safe)."""
        oid, changes = self.pending_changes(name)
        if not oid or not changes:
            return
        _, entry = self.managed_by_name(name)
        lines = "\n".join(f"  {k} = {v}" for k, v in sorted(changes.items())[:25])
        more = "\n  " + tr("… and {n} more", n=len(changes) - 25) if len(changes) > 25 else ""
        if self.cfg("ask_backsync"):
            answer = orca.host.ui.message(
                tr("You changed the Spoolman profile “{name}”:", name=name) + f"\n\n{lines}{more}\n\n"
                + tr("Write it to Spoolman? With “No” the next sync resets the profile to the Spoolman values."),
                "Kobra Spoolman", buttons="yes_no", icon="question")
            if answer != "yes":
                return
        try:
            res = self.http("POST", "/api/orca/backsync", {"orca_id": oid, "changes": changes}, timeout=6)
            self.accept_saved(oid, entry)
            ign = res.get("ignored") or []
            applied = len(res.get("applied", {}))
            notify("Kobra Spoolman: " + (tr("written to Spoolman ({n} values, ignored: {keys})", n=applied,
                                            keys=", ".join(ign)) if ign
                                         else tr("written to Spoolman ({n} values)", n=applied)))
        except NotPaired:
            orca.host.ui.message(tr("Writing to Spoolman only works once the plugin is paired with the bridge.") + "\n\n"
                                 + tr("Get a code: app or web UI → Devices → Add device, enter it in the panel “Kobra "
                                      "Spoolman”, then save the profile once more."),
                                 "Kobra Spoolman", buttons="ok", icon="warning")
        except Exception as e:  # noqa: BLE001
            orca.host.ui.message(tr("Writing to Spoolman failed:") + f"\n{e}", "Kobra Spoolman",
                                 buttons="ok", icon="error")

    # ---------------------------------------------------------------- usage forecast (UI thread)
    def on_slice_complete(self):
        """Right after SlicingJobComplete: Orca sets the valid flag only afterwards."""
        stats = read_slice_statistics(require_valid=False)
        if stats is None:
            return None
        self.slice = {"stats": stats, "at": time.time(), "from_event": True, "stale": False}
        return self.forecast()

    def refresh_slice(self):
        """At every panel refresh: read the valid slice result of the current plate."""
        stats = read_slice_statistics(require_valid=True)
        now = time.time()
        if stats is not None:
            self.slice = {"stats": stats, "at": now, "from_event": False, "stale": False}
        elif self.slice and not self.slice["stale"]:
            if not (self.slice["from_event"] and now - self.slice["at"] < 8):
                self.slice["stale"] = True   # model/setting changed or another plate

    def forecast(self):
        st = self.bridge_state
        if not st or not self.slice or self.slice["stale"]:
            return None
        return build_forecast(self.slice["stats"], st.get("slots"), self.cfg("reserve_g"), st.get("purge"))

    def accept_saved(self, oid, entry):
        """The file Orca saved is now our state (after back sync)."""
        try:
            text = Path(entry["file"]).read_text(encoding="utf-8")
            (WRITTEN_DIR / f"{oid}.json").write_text(text, encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            log("Taking over the saved state failed:", e)


CONFIG_UI = r"""
<style>
  body { font: 13px system-ui, sans-serif; margin: 12px; color: var(--orca-fg, #222); background: var(--orca-bg, transparent); }
  label { display: block; margin: 10px 0 4px; font-weight: 600; }
  input[type=text], input[type=number], select { width: 100%; box-sizing: border-box; padding: 6px 8px; }
  .row { display: flex; gap: 8px; align-items: center; margin: 6px 0; }
  .row label { display: inline; margin: 0; font-weight: normal; }
  .hint { color: var(--orca-muted, #777); font-size: 12px; margin-top: 3px; }
  button { margin-top: 14px; padding: 6px 14px; }
</style>
<label for="bridge_url">{{Address of the ace-lane-bridge}}</label>
<input type="text" id="bridge_url" placeholder="http://192.168.1.10:7913">
<div class="hint">{{The page where you assign the ACE slots (port 7913).}}</div>
<label for="user_folder">{{Orca user folder}}</label>
<input type="text" id="user_folder" placeholder="default">
<div class="hint">{{Without an Orca login “default”. Profiles go to user/&lt;folder&gt;/filament/base.}}</div>
<label for="language">{{Language}}</label>
<select id="language"><option value="auto">{{Automatic (language of the bridge)}}</option>
  <option value="en">English</option><option value="de">Deutsch</option></select>
<label for="poll_seconds">{{Refresh (seconds)}}</label>
<input type="number" id="poll_seconds" min="2" max="60">
<div class="row"><input type="checkbox" id="sync_on_start"><label for="sync_on_start">{{Update profiles when Orca starts}}</label></div>
<div class="row"><input type="checkbox" id="open_panel_on_start"><label for="open_panel_on_start">{{Open the panel at start}}</label></div>
<div class="row"><input type="checkbox" id="ask_backsync"><label for="ask_backsync">{{Ask before writing back to Spoolman}}</label></div>
<div class="row"><input type="checkbox" id="warn_after_slice"><label for="warn_after_slice">{{Warn after slicing when a spool is not enough}}</label></div>
<label for="reserve_g">{{Reserve (g)}}</label>
<input type="number" id="reserve_g" min="0" max="200">
<div class="hint">{{If less than this stays on the spool after the print, the forecast shows “tight”.}}</div>
<button type="button" id="save">{{Save}}</button> <button type="button" id="defaults">{{Defaults}}</button>
<script>
(function () {
  var fields = ["bridge_url", "user_folder", "language", "poll_seconds", "reserve_g"], checks = ["sync_on_start", "open_panel_on_start", "ask_backsync", "warn_after_slice"];
  var defaults = __DEFAULTS__;
  function fill(cfg) {
    cfg = Object.assign({}, defaults, cfg || {});
    fields.forEach(function (k) { document.getElementById(k).value = cfg[k]; });
    checks.forEach(function (k) { document.getElementById(k).checked = !!cfg[k]; });
  }
  window.orca.onConfig(fill);
  document.getElementById("save").onclick = function () {
    var cfg = {};
    fields.forEach(function (k) { cfg[k] = document.getElementById(k).value.trim(); });
    cfg.poll_seconds = parseInt(cfg.poll_seconds, 10) || defaults.poll_seconds;
    cfg.reserve_g = parseFloat(cfg.reserve_g);
    if (isNaN(cfg.reserve_g)) cfg.reserve_g = defaults.reserve_g;
    checks.forEach(function (k) { cfg[k] = document.getElementById(k).checked; });
    window.orca.saveConfig(cfg);
  };
  document.getElementById("defaults").onclick = function () { window.orca.restoreDefaults(); };
})();
</script>
"""


# ====================================================================== panel
# Static texts carry data-t (English); every state message brings the translations (labels), so the panel follows a
# language change without being reopened.
PAGE = r"""
<style>
  body { margin:0; padding:10px; font-size:13px; }
  h3 { margin:0 0 6px; font-size:14px; }
  .muted { color: var(--orca-muted); font-size:12px; }
  .slot { border:1px solid var(--orca-border); border-radius:8px; padding:8px; margin-bottom:8px; display:flex; gap:8px; }
  .sw { width:22px; height:22px; border-radius:50%; flex:none; border:1px solid var(--orca-border); margin-top:2px; }
  .grow { flex:1; min-width:0; }
  .name { font-weight:600; overflow-wrap:anywhere; }
  .ok { color:#16a34a; } .bad { color:#dc2626; } .warn { color:#d97706; }
  .box { border-radius:8px; padding:8px; margin-bottom:8px; background: rgba(217,119,6,.12); border:1px solid rgba(217,119,6,.5); }
  .err { background: rgba(220,38,38,.1); border-color: rgba(220,38,38,.5); }
  .actions { display:flex; gap:6px; flex-wrap:wrap; margin:8px 0 2px; }
  .hint { margin-bottom:8px; }
  button.quiet { background:transparent; color:var(--orca-fg); border-color:var(--orca-border); }
  table { width:100%; border-collapse:collapse; } td { padding:2px 0; }
  td.r { text-align:right; }
  .fc { border:1px solid var(--orca-border); border-radius:8px; padding:8px; margin-bottom:8px; }
  .fc td { font-size:12px; } .fc tr.h td { font-weight:600; } .fc tr.s td { border-top:1px solid var(--orca-border); }
  .fc td + td { padding-left:5px; } .fc table td { font-size:11.5px; } .fc tr.h td { vertical-align:bottom; line-height:1.2; }
  .fch { display:flex; justify-content:space-between; gap:6px; margin-bottom:4px; }
  .fcl { display:flex; justify-content:space-between; gap:8px; padding:2px 0; }
  .fcn { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; min-width:0; }
  .fca { flex:none; font-variant-numeric:tabular-nums; }
  .fcw { font-size:12px; margin:0 0 2px 8px; }
  .fc details { margin-top:6px; } .fc summary { cursor:pointer; color:var(--orca-muted); font-size:12px; }
  .fct { margin:6px 0 2px; } .fcx { overflow-x:auto; }
</style>
<h3>Kobra Spoolman</h3>
<div id="status" class="muted" data-t="loading …">loading …</div>
<div id="boxes"></div>
<div id="pair" class="box" style="display:none">
  <b data-t="Pair the plugin">Pair the plugin</b>
  <div class="muted" style="margin:4px 0 6px" data-t="Needed for writing back to Spoolman. Code: app or web UI → Devices → Add device.">Needed for writing back to Spoolman. Code: app or web UI → Devices → Add device.</div>
  <div style="display:flex;gap:6px"><input id="paircode" inputmode="numeric" autocomplete="off" data-tp="6-digit code" placeholder="6-digit code" style="flex:1;min-width:0">
  <button type="button" id="pairbtn" data-t="Pair">Pair</button></div>
  <div id="pairmsg" class="muted" style="margin-top:4px"></div>
</div>
<div id="forecast"></div>
<div id="slots"></div>
<div class="actions">
  <button type="button" id="sync" data-t="Update profiles">Update profiles</button>
  <button type="button" id="refresh" class="quiet" data-t="Reload">Reload</button>
</div>
<div class="muted hint" data-t="“Update profiles” creates the Orca profiles from Spoolman. They reach the filament fields via Orca's sync icon in the filament area (for new profiles restart Orca first).">“Update profiles” creates the Orca profiles from Spoolman. They reach the filament fields via Orca's sync icon in the filament area (for new profiles restart Orca first).</div>
<div id="foot" class="muted"></div>
<script>
(function () {
  var L = {}, lang = "en";
  function t(s) { return L[s] || s; }
  function esc(v) { var s = document.createElement("span"); s.textContent = v == null ? "" : String(v); return s.innerHTML; }
  function g(v) { return v == null ? "?" : (Math.round(v * 10) / 10).toLocaleString(lang === "de" ? "de-DE" : "en-GB") + " g"; }
  function render(m) {
    L = m.labels || {}; lang = m.lang || "en";
    document.querySelectorAll("[data-t]").forEach(function (e) { if (e.id !== "status") e.textContent = t(e.getAttribute("data-t")); });
    document.querySelectorAll("[data-tp]").forEach(function (e) { e.placeholder = t(e.getAttribute("data-tp")); });
    document.getElementById("status").innerHTML = m.status;
    document.getElementById("boxes").innerHTML = (m.boxes || []).map(function (b) {
      return '<div class="box' + (b.error ? ' err' : '') + '">' + b.html + '</div>'; }).join("");
    document.getElementById("slots").innerHTML = (m.slots || []).map(function (s) {
      var sw = s.color ? 'style="background:#' + esc(s.color) + '"' : '';
      return '<div class="slot"><div class="sw" ' + sw + '></div><div class="grow">' +
        '<div><b>' + esc(t("Slot") + " " + s.slot) + '</b>' + (s.active ? ' · <span class="ok">' + esc(t("active")) + '</span>' : '') + '</div>' +
        '<div class="name">' + esc(s.name || t("not assigned")) + '</div>' +
        '<div class="muted">' + (s.spool_id ? '#' + s.spool_id + ' · ' + esc(s.material) + ' · ' + g(s.remaining_weight) : esc(s.ace || "")) + '</div>' +
        (s.check ? '<div class="' + s.check_cls + '">' + esc(s.check) + '</div>' : '') +
        (s.use ? '<div class="muted">' + esc(s.use) + '</div>' : '') +
        '</div></div>'; }).join("");
    // keep expanded details open across the regular refresh
    var d = document.getElementById("fcd"), open = d ? d.open : false;
    document.getElementById("forecast").innerHTML = m.forecast || "";
    d = document.getElementById("fcd");
    if (d) d.open = open;
    document.getElementById("foot").innerHTML = m.foot || "";
    // don't redraw the pairing field (the input would be lost), only show/hide it
    document.getElementById("pair").style.display = m.pair && m.pair.show ? "" : "none";
    var pm = document.getElementById("pairmsg");
    pm.textContent = (m.pair && m.pair.msg) || "";
    pm.className = m.pair && m.pair.error ? "bad" : "muted";
  }
  function pair() {
    var c = document.getElementById("paircode").value.replace(/\s/g, "");
    if (!c) return;
    document.getElementById("pairmsg").textContent = t("pairing …");
    orca.postMessage({ command: "pair", code: c });
  }
  document.getElementById("pairbtn").addEventListener("click", pair);
  document.getElementById("paircode").addEventListener("keydown", function (e) { if (e.key === "Enter") pair(); });
  orca.onMessage(function (m) { if (m && m.command === "state") render(m); });
  document.getElementById("sync").addEventListener("click", function () { orca.postMessage({ command: "sync" }); });
  document.getElementById("refresh").addEventListener("click", function () { orca.postMessage({ command: "refresh" }); });
  orca.postMessage({ command: "refresh" });
  setInterval(function () { orca.postMessage({ command: "refresh" }); }, 4000);
})();
</script>
"""

# texts the panel's script translates itself (data-t and t(...) in PAGE)
PANEL_TEXTS = ["loading …", "Pair the plugin", "Needed for writing back to Spoolman. Code: app or web UI → Devices → "
               "Add device.", "6-digit code", "Pair", "Update profiles", "Reload",
               "“Update profiles” creates the Orca profiles from Spoolman. They reach the filament fields via Orca's "
               "sync icon in the filament area (for new profiles restart Orca first).",
               "Slot", "active", "not assigned", "pairing …"]


def panel_labels():
    return {s: tr(s) for s in PANEL_TEXTS} if LANG["current"] != "en" else {}


def config_ui():
    """Settings page with the {{English}} texts translated."""
    page = re.sub(r"\{\{(.+?)\}\}", lambda m: tr(m.group(1)), CONFIG_UI)
    return page.replace("__DEFAULTS__", json.dumps(DEFAULT_CONFIG))


def _esc(s):
    return (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# symbol, CSS class, English label
FC_STATUS = {"ok": ("✓", "ok", "enough"), "tight": ("⚠", "warn", "tight"), "short": ("✗", "bad", "not enough"),
             "unknown": ("?", "muted", "rest unknown"), "nospool": ("✗", "bad", "no spool assigned"),
             "noslot": ("✗", "bad", "no ACE slot"), "nomaterial": ("✗", "bad", "no material at the printer")}


def forecast_html(fc):
    """Usage forecast: one line per slot (need / rest), breakdown to expand.
    The columns are named and computed like Orca's legend (filament, model, support, flushed, tower, total);
    "flushed" includes the ACE's purge at a colour change (EXTERNAL_PURGE in the change G-code)."""
    def g(v, nd=1):
        return num(v, nd)

    lines = []
    for r in fc["rows"]:
        sym, cls, label = FC_STATUS.get(r["status"], ("", "muted", ""))
        label = tr(label) if label else ""
        name = _esc(r.get("name") or tr("Filament {n}", n=r["slot"]))
        if r.get("remaining_g") is not None:
            amount = f"{g(r['need_g'])} / {g(r['remaining_g'])} g"
        else:
            amount = f"{g(r['need_g'])} g"
        lines.append(f"<div class='fcl' title='{_esc(label)}'><span class='fcn'><b>{_esc(tr('Slot {n}', n=r['slot']))}"
                     f"</b> · {name}</span><span class='fca'>{amount} <span class='{cls}'>{sym}</span></span></div>")
        if r["status"] not in ("ok", "unknown"):
            lines.append(f"<div class='{cls} fcw'>{_esc(label)}</div>")

    cols = [(tr("Model"), "model_g"), (tr("Support"), "support_g"), (tr("Flushed"), "flush_g"), (tr("Tower"), "tower_g"),
            (tr("Firmware purge"), "purge_g")]
    cols = [c for c in cols if c[1] == "model_g" or any(r[c[1]] for r in fc["rows"])]
    head = "".join(f"<td class='r'>{t}</td>" for t, _ in cols)
    body = "".join(
        f"<tr><td>{r['slot']}</td>" + "".join(f"<td class='r'>{g(r[k], 2)}</td>" for _, k in cols)
        + f"<td class='r'><b>{g(r['need_g'], 2)}</b></td><td class='r'>{g(r.get('remaining_g'), 0)}</td></tr>"
        for r in fc["rows"])
    orca_tab = (f"<div class='fcx'><table><tr class='h'><td>{tr('Filament')}</td>{head}<td class='r'>{tr('Total')}</td>"
                f"<td class='r'>{tr('Rest')}</td></tr>{body}"
                f"<tr class='s'><td>{tr('Sum')}</td>{'<td></td>' * len(cols)}<td class='r'>{g(fc['total_g'], 2)}</td>"
                "<td></td></tr></table></div>")
    if fc.get("firmware_purge"):
        how = tr("counted by Orca") if fc.get("loads_exact") else tr("total without order")
        purge_text = tr("{n} colour changes ({how}). “Firmware purge” is what the printer purges by itself at every "
                        "load (Rinkhals: Orca's matrix does not apply) – computed from the slot colours with the "
                        "bridge's model.", n=fc["changes"], how=how)
    elif fc.get("purge_missing"):
        purge_text = ("<span class='warn'>" + tr("The ACE purge is missing in these numbers: the printer profile's "
                      "change-filament G-code does not report it to Orca (EXTERNAL_PURGE). Create the profile again "
                      "with make-profile.py.") + "</span>")
    else:
        how = tr("counted by Orca") if fc.get("loads_exact") else tr("total without order")
        purge_text = tr("{n} colour changes ({how}). “Flushed” is the ACE purge: loading up to the nozzle plus the "
                        "purge volume from Orca's matrix (flushing volumes dialog).", n=fc["changes"], how=how)
    plate = tr("Plate {n}", n=fc["plate"] + 1) + " · " if isinstance(fc.get("plate"), int) else ""
    return (f"<div class='fc'><div class='fch'><b>{tr('Planned usage')}</b><span class='muted'>{plate}"
            f"{tr('grams')}</span></div>"
            + "".join(lines)
            + f"<details id='fcd'><summary>{tr('Details (like Orca’s legend)')}</summary>"
            f"<div class='muted fct'>{tr('Like Orca’s legend (preview → filament):')}</div>{orca_tab}"
            f"<div class='muted fct'>{purge_text} {tr('Rest = what is on the spool according to Spoolman.')}</div>"
            "</details></div>")


def build_panel_message(core: Core):
    """Runs in the UI thread (panel message): may read Orca presets."""
    st = core.bridge_state or {}
    boxes = []
    if core.bridge_error:
        boxes.append({"error": True, "html": _esc(core.bridge_error) + "<br>" +
                      tr("Address: {url} – change it under <b>Plugins → Kobra Spoolman → Configuration</b>.",
                         url=f"<code>{_esc(core.cfg('bridge_url'))}</code>")})
    for w in st.get("warnings") or []:
        boxes.append({"error": True, "html": _esc(w)})
    if core.restart_needed:
        boxes.append({"html": tr("<b>Profiles updated.</b> Restart Orca, then press Orca's sync icon in the filament area.")})
    elif st.get("profiles_outdated"):
        boxes.append({"html": tr("Something changed in Spoolman. <b>Update profiles</b> and restart Orca.")})
    ls = core.last_sync or {}
    for e in ls.get("errors") or []:
        boxes.append({"error": True, "html": _esc(e)})

    # current filament choice in Orca (filament 1..n <-> slot 1..n)
    selected, loaded = [], set()
    try:
        bundle = orca.host.preset_bundle()
        # base profiles the sync did not find: Orca knows where the file is
        found_new = False
        for base_name in list(core.missing_bases):
            p = bundle.filaments.find_preset(base_name)
            f = Path(p.file) if p is not None and p.file else None
            if f and f.suffix == ".json":
                vendor_dir = next((d for d in f.parents if (d / "filament").is_dir()), None)
                if vendor_dir and core.system.add_root(vendor_dir):
                    found_new = True
        if found_new:
            core.sync_request.set()
            core.wake.set()
        selected = list(bundle.current_filament_preset_names())
        for oid, e in core.managed().items():
            if bundle.filaments.find_preset(e["name"]) is not None:
                loaded.add(oid)
    except Exception as e:  # noqa: BLE001
        log("Presets not readable:", e)

    # usage forecast after slicing
    core.refresh_slice()
    fc = core.forecast()
    if fc:
        for r in fc["rows"]:
            if r["status"] in ("short", "nospool", "noslot", "nomaterial"):
                boxes.append({"error": True, "html": "<b>" + tr("Not enough:") + "</b> "
                              + _esc(forecast_warnings({"rows": [r]})[0])})

    live = ((st.get("usage") or {}).get("live") or {})
    live_by_slot = {x["slot"]: x for x in live.get("slots", [])}
    last_by_slot = (st.get("usage") or {}).get("last") or {}
    slots = []
    for s in st.get("slots") or []:
        item = dict(s)
        item["ace"] = "ACE: " + ((s.get("ace_material") or tr("empty")) if s.get("present") else tr("empty"))
        oid = s.get("orca_id")
        idx = s["slot"] - 1
        if oid:
            entry = core.managed().get(oid)
            if not entry:
                item["check"], item["check_cls"] = tr("No Orca profile – update profiles"), "warn"
            elif oid not in loaded:
                item["check"], item["check_cls"] = tr("Profile created – restart Orca"), "warn"
            elif idx < len(selected) and selected[idx] == entry["name"]:
                item["check"], item["check_cls"] = tr("Filament {n} in Orca: matches", n=s["slot"]), "ok"
            elif idx < len(selected):
                item["check"] = tr("Filament {n} in Orca is “{have}” – expected “{want}” (sync button in Orca)",
                                   n=s["slot"], have=selected[idx], want=entry["name"])
                item["check_cls"] = "bad"
        if s.get("present") and not s.get("ace_material"):
            item["check"] = tr("No material is set at the printer – a print with this slot gets cancelled")
            item["check_cls"] = "bad"
        lv = live_by_slot.get(s["slot"])
        la = last_by_slot.get(str(s["slot"])) or last_by_slot.get(s["slot"])
        if lv:
            item["use"] = tr("This print: {g} g", g=num(lv["g"]))
        elif la:
            item["use"] = tr("Last print: {g} g", g=num(la["g"]))
        slots.append(item)

    forecast = ""
    if fc and fc["rows"]:
        forecast = forecast_html(fc)
    elif core.slice and core.slice["stale"]:
        forecast = "<div class='muted'>" + tr("Forecast: the slice result is outdated – slice again.") + "</div>"
    status = []
    status.append("Bridge " + ("<span class='ok'>" + tr("connected") + "</span>" if st and not core.bridge_error
                               else "<span class='bad'>" + tr("disconnected") + "</span>"))
    if st and not core.bridge_error and core.paired is not None:
        status.append(tr("paired") if core.paired else "<span class='warn'>" + tr("not paired") + "</span>")
    if st:
        status.append(tr("Printer {state}", state=_esc(st.get("print_state") or "–")))
    foot = tr("Plugin {version} · bridge {bridge} · {n} profiles", version=PLUGIN_VERSION,
              bridge=_esc(st.get("version", "–")), n=len(core.managed()))
    if not hasattr(orca.host, "slice_statistics"):
        foot += " · " + tr("the usage forecast needs orca-kobra (patch 0003)")
    if ls.get("at"):
        foot += " · " + tr("sync {at}: {written} new/changed, {deleted} removed", at=ls["at"],
                           written=len(ls.get("written", [])), deleted=len(ls.get("deleted", [])))
    pm = core.pair_msg or {}
    pair = {"show": bool(st) and not core.bridge_error and core.paired is False,
            "msg": pm.get("text") if pm.get("error") else None, "error": pm.get("error", False)}
    if pm and not pm.get("error"):
        boxes.insert(0, {"html": _esc(pm["text"])})
        core.pair_msg = None
    return {"command": "state", "lang": LANG["current"], "labels": panel_labels(), "status": " · ".join(status),
            "boxes": boxes, "slots": slots, "forecast": forecast, "foot": foot, "pair": pair}


# ====================================================================== capabilities
_core = None


def core_for(cap):
    global _core
    if _core is None:
        _core = Core(cap.get_config)
    return _core


class KobraPanel(orca.script.ScriptPluginCapabilityBase):
    panel = None

    def get_name(self):
        return "Kobra Spoolman"

    def get_default_config(self):
        return dict(DEFAULT_CONFIG)

    def has_config_ui(self):
        return True

    def get_config_ui(self):
        core_for(self).update_language()
        return config_ui()

    def on_load(self):
        core = core_for(self)
        core.start()
        if core.cfg("open_panel_on_start"):
            # At Orca's start the plugin often loads before the main window is ready - then Orca silently drops the
            # panel. So keep trying in the background until it is open.
            threading.Thread(target=self._ensure_panel, name="kobra-spoolman-panel", daemon=True).start()

    def _ensure_panel(self):
        for _ in range(40):
            if _core is not None and _core.stop.is_set():
                return
            try:
                if self.panel is None or not self.panel.is_open():
                    self.panel = None
                    self.open_panel()
                time.sleep(3)
                if self.panel is not None and self.panel.is_open():
                    self.panel.show()
                    return
            except Exception as e:  # noqa: BLE001
                log("Opening the panel:", e)
                time.sleep(3)
        log("The panel could not be opened at start - start it from the plugins dialog")

    def on_unload(self):
        if _core:
            _core.stop.set()
        if self.panel is not None and self.panel.is_open():
            self.panel.close()

    def execute(self):
        self.open_panel()
        return orca.ExecutionResult.success(tr("Kobra Spoolman opened."))

    def open_panel(self):
        if self.panel is not None and self.panel.is_open():
            self.panel.show()
            return
        self.panel = orca.host.ui.create_dock_panel(html=PAGE, title="Kobra Spoolman", width=300, height=560,
                                                    on_message=self.on_message, on_close=self.on_close, dock="right")

    def on_message(self, message):
        core = core_for(self)
        cmd = (message or {}).get("command")
        if cmd == "sync":
            core.sync_request.set()
            core.wake.set()
        elif cmd == "pair":
            code = re.sub(r"\s", "", str((message or {}).get("code") or ""))
            if code:
                core.pair_msg = None
                core.pair_code = code
                core.start()
                core.wake.set()
        if self.panel is not None:
            self.panel.post(build_panel_message(core))

    def on_close(self):
        self.panel = None

    def on_lifecycle_event(self, event, ctx):
        if event == orca.LifecycleEvent.PresetSaved:
            core = core_for(self)
            if core.managed_by_name(ctx.name)[0]:
                core.start()
                core.saved_queue.put(ctx.name)
                core.wake.set()
        elif event == orca.LifecycleEvent.SlicingJobComplete:
            if ctx.code != orca.LifecycleEvtCode.Ok:
                return
            self._after_slice(core_for(self))

    def _after_slice(self, core):
        fc = core.on_slice_complete()
        if fc and core.cfg("warn_after_slice"):
            bad = forecast_warnings({"rows": [r for r in fc["rows"]
                                              if r["status"] in ("short", "nospool", "noslot", "nomaterial")]})
            if bad and bad != core.slice_warned:
                notify("Kobra Spoolman: " + " · ".join(bad), "WarningNotificationLevel")
            core.slice_warned = bad
        if self.panel is not None and self.panel.is_open():
            self.panel.post(build_panel_message(core))


class KobraSync(orca.script.ScriptPluginCapabilityBase):
    def get_name(self):
        return "Kobra Spoolman: update profiles"

    def execute(self):
        # network and files run in the background thread; the panel shows the result
        core = core_for(self)
        core.start()
        core.sync_request.set()
        core.wake.set()
        return orca.ExecutionResult.success(tr("Sync started - result in the panel “Kobra Spoolman”."))


@orca.plugin
class KobraSpoolmanPlugin(orca.base):
    def register_capabilities(self):
        orca.register_capability(KobraPanel)
        orca.register_capability(KobraSync)


# ====================================================================== German texts
DE = {
    "Slot {slot}: needs about {need} g, the spool has {rest} g left":
        "Slot {slot}: braucht ca. {need} g, auf der Spule sind noch {rest} g",
    "Slot {slot}: tight – needs about {need} g, {rest} g left": "Slot {slot}: knapp – braucht ca. {need} g, noch {rest} g",
    "Slot {slot} is used but has no spool assigned": "Slot {slot} wird benutzt, hat aber keine Spule zugeordnet",
    "Filament {slot} has no ACE slot": "Filament {slot} hat keinen ACE-Slot",
    "Slot {slot}: no material is set at the printer – the print gets cancelled":
        "Slot {slot}: Am Drucker ist kein Material eingetragen – der Druck bricht ab",
    "no material at the printer": "kein Material am Drucker",
    "Firmware purge": "Spülen Firmware",
    "{n} colour changes ({how}). “Firmware purge” is what the printer purges by itself at every load (Rinkhals: Orca's "
    "matrix does not apply) – computed from the slot colours with the bridge's model.":
        "{n} Farbwechsel ({how}). „Spülen Firmware“ ist, was der Drucker bei jedem Laden selbst spült (Rinkhals: Orcas "
        "Matrix gilt nicht) – aus den Slot-Farben mit dem Modell der Bridge gerechnet.",
    "The ACE purge is missing in Orca's numbers – create the printer profile again (make-profile.py)":
        "Spülen der ACE fehlt in Orcas Zahlen – Drucker-Profil neu anlegen (make-profile.py)",
    "Bridge not reachable ({error})": "Bridge nicht erreichbar ({error})",
    "Paired as “{name}”.": "Gekoppelt als „{name}“.",
    "Sync failed: {error}": "Sync fehlgeschlagen: {error}",
    "{name}: no Orca base profile in Spoolman and no material – set “Orca base profile” on the filament or create a "
    "template (spoolman_setup.py)":
        "{name}: kein Orca-Basisprofil in Spoolman und kein Material – am Filament „Orca base profile“ setzen oder "
        "eine Vorlage anlegen (spoolman_setup.py)",
    "{name}: Orca base profile “{base}” not found in Orca": "{name}: Orca-Basisprofil „{base}“ nicht in Orca gefunden",
    "{name}: Orca base profile “{base}” (fallback, because none is set in Spoolman) not found in Orca":
        "{name}: Orca-Basisprofil „{base}“ (Ersatz, weil in Spoolman keins gesetzt ist) nicht in Orca gefunden",
    "… and {n} more": "… und {n} weitere",
    "You changed the Spoolman profile “{name}”:": "Du hast das Spoolman-Profil „{name}“ geändert:",
    "Write it to Spoolman? With “No” the next sync resets the profile to the Spoolman values.":
        "Nach Spoolman übernehmen? Bei „Nein“ setzt der nächste Sync das Profil auf die Spoolman-Werte zurück.",
    "written to Spoolman ({n} values, ignored: {keys})": "nach Spoolman übernommen ({n} Werte, ignoriert: {keys})",
    "written to Spoolman ({n} values)": "nach Spoolman übernommen ({n} Werte)",
    "Writing to Spoolman only works once the plugin is paired with the bridge.":
        "Übernehmen nach Spoolman geht erst, wenn das Plugin mit der Bridge gekoppelt ist.",
    "Get a code: app or web UI → Devices → Add device, enter it in the panel “Kobra Spoolman”, then save the profile "
    "once more.":
        "Code holen: App oder Weboberfläche → Geräte → Gerät hinzufügen, dann im Panel „Kobra Spoolman“ eingeben und "
        "danach das Profil noch einmal speichern.",
    "Writing to Spoolman failed:": "Übernehmen nach Spoolman fehlgeschlagen:",
    "Address of the ace-lane-bridge": "Adresse der ace-lane-bridge",
    "The page where you assign the ACE slots (port 7913).": "Die Seite, auf der du die ACE-Slots zuordnest (Port 7913).",
    "Orca user folder": "Orca-Benutzerordner",
    "Without an Orca login “default”. Profiles go to user/&lt;folder&gt;/filament/base.":
        "Ohne Orca-Anmeldung „default“. Profile landen in user/&lt;ordner&gt;/filament/base.",
    "Language": "Sprache",
    "Automatic (language of the bridge)": "Automatisch (Sprache der Bridge)",
    "Refresh (seconds)": "Aktualisierung (Sekunden)",
    "Update profiles when Orca starts": "Profile beim Orca-Start aktualisieren",
    "Open the panel at start": "Panel beim Start öffnen",
    "Ask before writing back to Spoolman": "Vor dem Rücksync nach Spoolman fragen",
    "Warn after slicing when a spool is not enough": "Nach dem Slicen warnen, wenn eine Spule nicht reicht",
    "Reserve (g)": "Reserve (g)",
    "If less than this stays on the spool after the print, the forecast shows “tight”.":
        "Bleibt nach dem Druck weniger als das auf der Spule, zeigt die Vorschau „knapp“.",
    "Save": "Speichern",
    "Defaults": "Standardwerte",
    "loading …": "lade …",
    "Pair the plugin": "Plugin koppeln",
    "Needed for writing back to Spoolman. Code: app or web UI → Devices → Add device.":
        "Nötig für den Rücksync nach Spoolman. Code: App oder Weboberfläche → Geräte → Gerät hinzufügen.",
    "6-digit code": "6-stelliger Code",
    "Pair": "Koppeln",
    "Update profiles": "Profile aktualisieren",
    "Reload": "Neu laden",
    "“Update profiles” creates the Orca profiles from Spoolman. They reach the filament fields via Orca's sync icon in "
    "the filament area (for new profiles restart Orca first).":
        "„Profile aktualisieren“ legt die Orca-Profile aus Spoolman an. In die Filament-Felder kommen sie danach über "
        "Orcas Sync-Symbol im Filament-Bereich (bei neuen Profilen erst Orca neu starten).",
    "Slot": "Slot",
    "active": "aktiv",
    "not assigned": "nicht zugeordnet",
    "pairing …": "koppelt …",
    "enough": "reicht",
    "tight": "knapp",
    "not enough": "reicht nicht",
    "rest unknown": "Rest unbekannt",
    "no spool assigned": "keine Spule zugeordnet",
    "no ACE slot": "kein ACE-Slot",
    "Filament {n}": "Filament {n}",
    "Slot {n}": "Slot {n}",
    "Model": "Modell",
    "Support": "Stützen",
    "Flushed": "Gereinigt",
    "Tower": "Turm",
    "Filament": "Filament",
    "Total": "Gesamt",
    "Rest": "Rest",
    "Sum": "Summe",
    "The ACE purge is missing in these numbers: the printer profile's change-filament G-code does not report it to Orca "
    "(EXTERNAL_PURGE). Create the profile again with make-profile.py.":
        "Das Spülen der ACE fehlt in diesen Zahlen: Der Filamentwechsel-G-Code des Drucker-Profils meldet es Orca nicht "
        "(EXTERNAL_PURGE). Profil mit make-profile.py neu anlegen.",
    "counted by Orca": "von Orca gezählt",
    "total without order": "Gesamtzahl ohne Reihenfolge",
    "{n} colour changes ({how}). “Flushed” is the ACE purge: loading up to the nozzle plus the purge volume from "
    "Orca's matrix (flushing volumes dialog).":
        "{n} Farbwechsel ({how}). „Gereinigt“ ist das Spülen der ACE: Laden bis zur Düse plus Spülmenge aus Orcas "
        "Matrix (Spülmengen-Dialog).",
    "Plate {n}": "Platte {n}",
    "Planned usage": "Geplanter Verbrauch",
    "grams": "Gramm",
    "Details (like Orca’s legend)": "Details (wie Orcas Legende)",
    "Like Orca’s legend (preview → filament):": "Wie Orcas Legende (Vorschau → Filament):",
    "Rest = what is on the spool according to Spoolman.": "Rest = was laut Spoolman auf der Spule ist.",
    "Address: {url} – change it under <b>Plugins → Kobra Spoolman → Configuration</b>.":
        "Adresse: {url} – anpassen unter <b>Plugins → Kobra Spoolman → Konfiguration</b>.",
    "<b>Profiles updated.</b> Restart Orca, then press Orca's sync icon in the filament area.":
        "<b>Profile aktualisiert.</b> Orca neu starten, dann Orcas Sync-Symbol im Filament-Bereich drücken.",
    "Something changed in Spoolman. <b>Update profiles</b> and restart Orca.":
        "In Spoolman hat sich etwas geändert. <b>Profile aktualisieren</b> und Orca neu starten.",
    "Not enough:": "Reicht nicht:",
    "empty": "leer",
    "No Orca profile – update profiles": "Kein Orca-Profil – Profile aktualisieren",
    "Profile created – restart Orca": "Profil angelegt – Orca neu starten",
    "Filament {n} in Orca: matches": "Filament {n} in Orca: passt",
    "Filament {n} in Orca is “{have}” – expected “{want}” (sync button in Orca)":
        "Filament {n} in Orca ist „{have}“ – erwartet „{want}“ (Sync-Knopf in Orca)",
    "No material is set at the printer – a print with this slot gets cancelled":
        "Am Drucker ist kein Material eingetragen – ein Druck mit diesem Slot bricht ab",
    "This print: {g} g": "Dieser Druck: {g} g",
    "Last print: {g} g": "Letzter Druck: {g} g",
    "Forecast: the slice result is outdated – slice again.": "Vorschau: Slice-Ergebnis nicht mehr aktuell – neu slicen.",
    "connected": "verbunden",
    "disconnected": "getrennt",
    "paired": "gekoppelt",
    "not paired": "nicht gekoppelt",
    "Printer {state}": "Drucker {state}",
    "Plugin {version} · bridge {bridge} · {n} profiles": "Plugin {version} · Bridge {bridge} · {n} Profile",
    "the usage forecast needs orca-kobra (patch 0003)": "Verbrauchsvorschau braucht orca-kobra (Patch 0003)",
    "sync {at}: {written} new/changed, {deleted} removed": "Sync {at}: {written} neu/geändert, {deleted} entfernt",
    "Kobra Spoolman opened.": "Kobra Spoolman geöffnet.",
    "Sync started - result in the panel “Kobra Spoolman”.": "Sync gestartet - Ergebnis im Panel „Kobra Spoolman“.",
}
