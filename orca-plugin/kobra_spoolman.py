# /// script
# requires-python = ">=3.12"
#
# [tool.orcaslicer.plugin]
# name = "Kobra Spoolman"
# description = "Spoolman als Filament-Quelle: legt fuer jedes Spoolman-Filament ein Orca-Profil an, zeigt die ACE-Slots im Seitenpanel und uebernimmt Profil-Aenderungen nach Rueckfrage nach Spoolman. Braucht die ace-lane-bridge."
# author = "xNoVoSx"
# url = "https://github.com/xNoVoSx/kobra-spoolman"
# version = "0.5.1"
# ///
"""Kobra Spoolman - Orca-Plugin zur ace-lane-bridge (Etappe 3).

Aufgaben
- Profil-Sync: Die Bridge liefert pro Spoolman-Filament (mit aktiver Spule) die Werte aus
  Spoolman. Das Plugin loest das Orca-Basisprofil aus den System-Profilen auf (JSON unter
  <datenordner>/system) und schreibt ein eigenes Basisprofil (inherits "", filament_id SMxxxxxx)
  nach <datenordner>/user/<benutzer>/filament/base/. Orca liest Profile nur beim Start - neue
  oder geaenderte Profile erscheinen nach einem Neustart; das Panel sagt Bescheid.
- Seitenpanel: Slots mit Spule, Restgewicht, Verbrauch; Warnung, wenn Filament 1-4 in Orca
  nicht zu Slot 1-4 passt.
- Ruecksync: Speichert man ein verwaltetes Profil in Orca, fragt das Plugin, ob die
  Aenderungen nach Spoolman sollen.
- Koppeln: Was in Spoolman schreibt (Ruecksync, Basisprofile melden), braucht einen eigenen
  Schluessel. Das Panel fragt einmal nach einem 6-stelligen Code (App/Weboberflaeche: Geraete ->
  Geraet hinzufuegen); der Schluessel liegt danach in kobra_device.json neben dem Plugin.
- Verbrauchsvorschau: Nach dem Slicen zeigt das Panel pro Slot Bedarf / Rest (Orcas Zahlen wie in
  der Legende plus das Spuelen der Firmware pro Ladevorgang) und warnt, wenn eine Spule nicht reicht
  oder ein benutzter Slot am Drucker kein Material hat (dann bricht die Firmware den Druck ab).
  Braucht orca.host.slice_statistics (orca-kobra, Patch 0003); ohne fehlt nur die Vorschau.

Drucken und die Profilwahl beim Sync-Knopf macht Orcas eingebauter Moonraker-Agent
(mit Patch 0001 aus orca-kobra waehlt er das Profil ueber lane_data.filament_id).

Netzwerk und Dateien laufen in einem eigenen Hintergrund-Thread; Preset-Objekte liest das
Plugin nur im UI-Thread (Panel-Nachrichten, Ereignisse).
"""

from __future__ import annotations

import hashlib
import json
import math
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

PLUGIN_VERSION = "0.5.1"
MARKER = "kobra-spoolman"
DEFAULT_CONFIG = {
    "bridge_url": "http://localhost:7913",   # in den Plugin-Einstellungen anpassen
    "user_folder": "default",       # Unterordner in <datenordner>/user (ohne Orca-Login: default)
    "sync_on_start": True,
    "open_panel_on_start": True,
    "ask_backsync": True,
    "poll_seconds": 5,
    "reserve_g": 5,                 # Verbrauchsvorschau: "knapp", wenn weniger als das uebrig bleibt
    "warn_after_slice": True,       # Orca-Hinweis, wenn eine Spule nach dem Slicen nicht reicht
}
# Schluessel, die das Plugin selbst setzt und die nie als "Aenderung" nach Spoolman gehen
META_KEYS = {"name", "inherits", "from", "instantiation", "setting_id", "filament_id", "version", "type",
             "filament_settings_id", "compatible_printers", "compatible_printers_condition",
             "compatible_prints", "compatible_prints_condition", "filament_notes", "is_custom_defined",
             "base_id", "user_id", "updated_time", "filament_extruder_variant"}
FORBIDDEN = ("secret", "cert", "conf")   # Orcas Sandbox sperrt Pfade mit diesen Woertern
# Mehrverbrauch pro Ladevorgang, solange die Bridge noch keinen fertigen Druck gemessen hat
# (erster Testdruck: 451 mm beim Start + 195 mm beim Wechsel, 2 Ladevorgaenge)
DEFAULT_PURGE_PER_LOAD_MM = 320.0

DATA_DIR = Path(__file__).resolve().parents[2]      # <datenordner>/orca_plugins/<plugin>/<datei>.py
PLUGIN_DIR = Path(__file__).resolve().parent
STATE_FILE = PLUGIN_DIR / "kobra_state.json"
DEVICE_FILE = PLUGIN_DIR / "kobra_device.json"       # Schluessel dieses Plugins bei der Bridge
WRITTEN_DIR = PLUGIN_DIR / "written"                 # zuletzt geschriebene Profile (fuer den Ruecksync-Vergleich)


def log(*args):
    print("[kobra-spoolman]", *args, flush=True)   # landet in <datenordner>/log/python_*.log


def notify(text, level="RegularNotificationLevel"):
    try:
        orca.host.ui.push_notification(getattr(orca.host.ui.NotificationLevel, level), text)
    except Exception as e:  # noqa: BLE001
        log("Hinweis nicht moeglich:", e, text)


# ====================================================================== Hilfen
def fmt_value(v):
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        s = f"{v:.6f}".rstrip("0").rstrip(".")
        return s if s not in ("", "-0") else "0"
    return str(v)


def as_list(v):
    """Profilwert als Liste: Orca 2.5 speichert viele Filamentwerte je Extruder-Variante (6 Eintraege).
    Ein Text, der eine JSON-Liste ist (so kam er frueher per Ruecksync nach Spoolman), wird wieder zur Liste."""
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
    """Vergleichsform eines Profilwerts (Liste mit einem Element oder lauter gleichen Werten == Einzelwert)."""
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


class SystemProfiles:
    """Index der Orca-System-Filamentprofile (JSON).

    Gesucht wird in dieser Reihenfolge:
      1. <datenordner>/system            (von Orca gepflegte Kopien der Herstellerprofile)
      2. $APPDIR/resources/profiles      (im AppImage mitgelieferte Profile, u.a. OrcaFilamentLibrary)
      3. Ordner, die Orca selbst fuer ein Basisprofil nennt (Preset.file, aus dem UI-Thread)
    Profildateien heissen wie das Profil ("Generic PETG @System.json"); nur wenn das nicht
    passt, wird der Inhalt gelesen.
    """

    def __init__(self, root: Path):
        self.roots = [root]
        appdir = os.environ.get("APPDIR")
        if appdir:
            self.roots.append(Path(appdir) / "resources" / "profiles")
        self.extra_roots = []
        self.by_vendor = {}   # (wurzel, vendor) -> {name: pfad}
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
        """Namen der waehlbaren Filament-Basisprofile (fuer die Auswahl in der Android-App).
        Abstrakte Elternprofile (fdm_..., ... @base) bleiben weg."""
        if not self.by_vendor:
            self.scan()
        out = set()
        for index in self.by_vendor.values():
            out.update(n for n in index if not n.startswith("fdm_") and not n.endswith("@base"))
        return sorted(out)

    def _lookup(self, index, name):
        p = index.get(name)
        if p is not None:
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
        # langsamer Rueckfall: Name steht nur in der Datei
        for k in order:
            for p in self.by_vendor[k].values():
                try:
                    with open(p, encoding="utf-8") as fh:
                        if json.load(fh).get("name") == name:
                            return k, p
                except Exception:
                    continue
        return None, None

    def resolve(self, name):
        """Voll aufgeloestes Profil (Vererbung zusammengefuehrt) oder None."""
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
    """Werte der Bridge fuer das Profil. Orca verwirft filament_colour in Filament-Presets und nimmt
    beim Auswaehlen default_filament_colour - eine aeltere Bridge (bis 2.2.1) liefert noch filament_colour."""
    values = dict(values)
    legacy = values.pop("filament_colour", None)
    if legacy not in (None, "") and values.get("default_filament_colour") in (None, ""):
        values["default_filament_colour"] = legacy
    return values


def build_profile_json(base, prof, name):
    """Orca-Basisprofil + Spoolman-Werte -> vollstaendiges eigenes Basisprofil."""
    out = {k: v for k, v in base.items()
           if k not in ("setting_id", "base_id", "user_id", "updated_time", "filament_colour")}
    for key, val in profile_values(prof["values"]).items():
        if key == "filament_id":
            continue
        cur = out.get(key)
        lst = as_list(val)
        if lst is not None:                       # Liste (je Variante) bleibt Liste
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
        "filament_notes": [f"{MARKER}: verwaltet ueber Spoolman ({prof['orca_id']}, Filament #{prof['filament_id']}). "
                           "Aenderungen hier werden nach Rueckfrage nach Spoolman uebernommen."],
    })
    out.setdefault("version", base.get("version", "2.5.0.0"))
    return out


def diff_profiles(written, saved):
    """Schluessel, deren Wert der Nutzer in Orca geaendert hat: {key: neuer Wert (Text)}.

    Nur Schluessel aus unserer geschriebenen Datei zaehlen: Sie enthaelt das ganze Basisprofil. Was dort fehlt,
    fuegt Orca beim Speichern als eigenen Standardwert hinzu (Orca 2.5: ~80 Schluessel, viele je Extruder-Variante)
    - das ist keine Aenderung des Nutzers."""
    changes = {}
    for key in written:
        if key in META_KEYS:
            continue
        a, b = written.get(key), saved.get(key)
        if b is None:
            continue
        nb = normalize(b)
        if normalize(a) != nb:
            lst = as_list(b)
            if lst is not None and len(lst) > 1 and len(set(map(str, lst))) > 1:
                changes[key] = json.dumps(lst, ensure_ascii=False)   # echte Unterschiede je Variante
            else:
                v = lst[0] if lst else b
                changes[key] = v if isinstance(v, str) else fmt_value(v)
    return changes


# ====================================================================== Spuelen der ACE
# Gleiche Rechnung wie die Bridge (bridge/app/acebridge/purge.py, docs/findings.md): Die Firmware
# nimmt Orcas Farbformel + flush_volume_min, begrenzt auf min..max, mal flush_multiplier.
# Beide Stellen gleich halten (tests/test_plugin_purge.py vergleicht sie).
_AREA_175 = math.pi * (1.75 / 2) ** 2
DEFAULT_FLUSH = {"flush_multiplier": 1.0, "flush_volume_min": 107.0, "flush_volume_max": 800.0}


def _hex_rgb(color):
    h = str(color or "").strip().lstrip("#")[:6]
    if len(h) != 6:
        return None
    try:
        return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return None


def _hsv(r, g, b):
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


def orca_colour_volume(src, dst):
    """Orcas FlushVolCalculator::calc_flush_vol (mm3) ohne Orcas Mindestwert; None bei unbekannter Farbe."""
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
    return max(math.sqrt(hs_flush ** 2 + lumi_flush ** 2 + hs_flush * lumi_flush), 60.0)


def purge_change_mm(src, dst, flush, offset_mm):
    """Spuelen der ACE in mm (1,75 mm) fuer den Wechsel src -> dst; None bei unbekannter Farbe."""
    raw = orca_colour_volume(src, dst)
    if raw is None:
        return None
    lo, hi = float(flush["flush_volume_min"]), float(flush["flush_volume_max"])
    vol = min(max(float(int(raw + lo)), lo), hi)        # Orca schneidet auf ganze mm3 ab
    return max(0.0, vol * float(flush["flush_multiplier"]) / _AREA_175 + offset_mm)


def _purge_per_filament(used, load_counts, stats, slots, purge, per_load_mm):
    """mm Spuelen pro Filament-Index und die Methode ("transitions", "colours", "average").

    transitions - neuer Patch 0003: jeder Wechsel von -> nach mit Anzahl, pro Wechsel gerechnet
    colours     - Farben bekannt, Reihenfolge nicht: pro Filament der Mittelwert der Wechsel von
                  den anderen benutzten Filamenten her; der erste Ladevorgang anteilig
    average     - Bridge ohne Spuel-Modell: gemessener Mittelwert pro Ladevorgang
    """
    model = (purge or {}).get("model")
    ids = [f["index"] for f in used]
    if not isinstance(model, dict) or not ids:
        return {i: per_load_mm * load_counts[i] for i in ids}, "average"
    flush = {k: float(model.get(k, v)) for k, v in DEFAULT_FLUSH.items()}
    offset = float(model.get("offset_mm", -3.0))
    first = float(model.get("first_load_mm", 95.0))
    # Firmware rechnet mit den Farben, die die ACE meldet
    colours = {int(s["slot"]) - 1: (s.get("ace_color") or s.get("color")) for s in slots or []}

    def change(i, j):
        mm = purge_change_mm(colours.get(i), colours.get(j), flush, offset)
        return per_load_mm if mm is None else mm

    transitions = (stats or {}).get("transitions")
    if transitions:
        out = {i: 0.0 for i in ids}
        for t in transitions:
            to, n = int(t["to"]), int(t.get("count") or 1)
            mm = first if t.get("from") is None else change(int(t["from"]), to)
            out[to] = out.get(to, 0.0) + mm * n
        return out, "transitions"
    out = {}
    share = 1.0 / len(ids)                     # wer zuerst geladen wird, sagt erst der neue Patch
    for j in ids:
        others = [change(i, j) for i in ids if i != j]
        per = sum(others) / len(others) if others else first
        out[j] = share * first + max(0.0, load_counts[j] - share) * per
    return out, "colours"


def _mm_to_g(mm, diameter, density):
    r = (diameter or 1.75) / 2
    return mm * 3.141592653589793 * r * r * (density or 1.24) / 1000


def build_forecast(stats, slots, purge=None, reserve_g=5.0):
    """Bedarf pro Slot fuer den gesliceten Druck.

    stats  - Ergebnis von orca.host.slice_statistics() (Volumen in mm3, Filament-Index ab 0)
    slots  - Slots aus /api/orca/state (slot, name, spool_id, remaining_weight)
    purge  - /api/orca/state usage.purge: "model" (Spuel-Modell der Bridge) oder nur
             overhead_per_load_mm (aeltere Bridge)

    Filament N in Orca gehoert zu Slot N (so setzt es der Sync-Knopf). Die Orca-Werte sind
    dieselben wie in Orcas Legende: Modell, Stuetzen, Gereinigt, Turm, Gesamt = Summe davon
    (nicht total_volumes_per_extruder - das verteilt den Turm beim Wechsel anders). Dazu kommt
    das Spuelen der Firmware beim Laden, das Orca nicht kennt: pro Farbwechsel aus den Slot-Farben
    gerechnet (_purge_per_filament), sonst gemessene Menge pro Ladevorgang mal Ladevorgaenge.
    Wechsel und Ladevorgaenge zaehlt Orca ("transitions", "loads" aus Patch 0003); fehlen sie,
    werden die Wechsel gleichmaessig auf die benutzten Filamente verteilt.
    """
    by_slot = {s["slot"]: s for s in slots or []}

    def orca_mm3(f):
        return sum(f.get(k) or 0 for k in ("model_mm3", "support_mm3", "flush_mm3", "tower_mm3"))

    used = [f for f in (stats or {}).get("filaments", []) if orca_mm3(f) > 0]
    purge = purge or {}
    per_load_mm = purge.get("overhead_per_load_mm") if purge.get("jobs") else None
    measured = per_load_mm is not None
    if per_load_mm is None:
        per_load_mm = DEFAULT_PURGE_PER_LOAD_MM
    per_load_mm = max(0.0, float(per_load_mm))
    loads_exact = bool(used) and all("loads" in f for f in used)
    if loads_exact:
        load_counts = {f["index"]: max(1, int(f["loads"] or 0)) for f in used}
    else:
        changes = int((stats or {}).get("total_filament_changes") or 0)
        extra = (max(len(used), changes + 1) - len(used)) / len(used) if used else 0.0
        load_counts = {f["index"]: 1 + extra for f in used}

    transitions = (stats or {}).get("transitions")
    if transitions and used:
        counted = {f["index"]: 0 for f in used}
        for t in transitions:
            counted[int(t["to"])] = counted.get(int(t["to"]), 0) + int(t.get("count") or 1)
        load_counts = {i: max(1, counted.get(i, 0)) for i in load_counts}
        loads_exact = True
    purge_mm, purge_method = _purge_per_filament(used, load_counts, stats, slots, purge, per_load_mm)

    rows, short, tight = [], [], []
    for f in sorted(used, key=lambda x: x["index"]):
        slot_no = int(f["index"]) + 1
        density, diameter = f.get("density"), f.get("diameter")
        dens = density or 1.24

        def g(mm3, dens=dens):
            return (mm3 or 0) * dens / 1000

        slot_loads = load_counts[f["index"]]
        row = {
            "slot": slot_no,
            "model_g": round(g(f.get("model_mm3")), 2),
            "support_g": round(g(f.get("support_mm3")), 2),
            "flush_g": round(g(f.get("flush_mm3")), 2),
            "tower_g": round(g(f.get("tower_mm3")), 2),
            "orca_g": round(g(orca_mm3(f)), 2),
            "loads": round(slot_loads, 1),
            "purge_g": round(_mm_to_g(purge_mm.get(f["index"], 0.0), diameter, density), 1),
        }
        row["need_g"] = round(row["orca_g"] + row["purge_g"], 1)
        s = by_slot.get(slot_no)
        if s is None:
            row["status"] = "noslot"
        elif s.get("present") and not s.get("ace_material"):
            # Rinkhals meldet beim Start material_type "" - GoKlipper bricht den Druck ab
            row["status"] = "nomaterial"
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
        "loads": round(sum(load_counts.values())),
        "loads_exact": loads_exact,
        "per_load_mm": round(per_load_mm, 1),
        "per_load_g": round(_mm_to_g(per_load_mm, 1.75, 1.24), 2),
        "purge_measured": measured,
        "purge_jobs": purge.get("jobs", 0),
        "purge_method": purge_method,
        "purge_model": purge.get("model") if purge_method != "average" else None,
        "orca_g": round(sum(r["orca_g"] for r in rows), 2),
        "total_g": round(sum(r["need_g"] for r in rows), 1),
    }


def forecast_warnings(fc):
    """Kurze Texte fuer Hinweise und das Panel."""
    out = []
    for r in fc.get("rows", []):
        if r["status"] == "short":
            out.append(f"Slot {r['slot']}: braucht ca. {r['need_g']:.0f} g, auf der Spule sind noch "
                       f"{r['remaining_g']:.0f} g")
        elif r["status"] == "tight":
            out.append(f"Slot {r['slot']}: knapp – braucht ca. {r['need_g']:.0f} g, "
                       f"noch {r['remaining_g']:.0f} g")
        elif r["status"] == "nospool":
            out.append(f"Slot {r['slot']} wird benutzt, hat aber keine Spule zugeordnet")
        elif r["status"] == "noslot":
            out.append(f"Filament {r['slot']} hat keinen ACE-Slot")
        elif r["status"] == "nomaterial":
            out.append(f"Slot {r['slot']}: am Drucker ist kein Material eingetragen – der Druck bricht beim Start ab")
    return out


def read_slice_statistics(require_valid=True):
    """orca.host.slice_statistics (orca-kobra Patch 0003) - None, wenn nicht vorhanden/nicht gesliced."""
    fn = getattr(orca.host, "slice_statistics", None)
    if fn is None:
        return None
    try:
        return fn(-1, require_valid)
    except Exception as e:  # noqa: BLE001
        log("Slice-Statistik nicht lesbar:", e)
        return None


# ====================================================================== Kopplung
class NotPaired(Exception):
    """Die Bridge lehnt ab: dieses Plugin ist nicht (mehr) gekoppelt."""


class DeviceKey:
    """Schluessel des Plugins bei der Bridge. Gilt nur fuer die Bridge-Adresse, bei der gekoppelt wurde."""

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
    return f"Orca-Plugin ({host})" if host else "Orca-Plugin"


# ====================================================================== Kern
class Core:
    """Ein Exemplar pro Orca-Sitzung: Bridge-Abfragen, Profil-Sync, Zustand."""

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
        self.saved_queue = queue.Queue()   # in Orca gespeicherte Profilnamen (Ruecksync)
        self.system = SystemProfiles(DATA_DIR / "system")
        self.thread = None
        self.missing_bases = set()     # Basisprofile, die im letzten Sync nicht gefunden wurden
        self.slice = None              # {"stats", "at", "from_event"} - letztes Slice-Ergebnis
        self.slice_warned = None       # Warnungen, fuer die schon ein Hinweis kam
        self.key = DeviceKey(DEVICE_FILE)
        self.paired = None             # None = noch nicht geprueft
        self.paired_checked = 0.0
        self.pair_code = None          # vom Panel, wird im Hintergrund eingeloest
        self.pair_msg = None           # {"error": bool, "text": str}

    # ---------------------------------------------------------------- Zustand
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

    def user_filament_dir(self):
        return DATA_DIR / "user" / str(self.cfg("user_folder")) / "filament" / "base"

    def managed(self):
        """orca_id -> Eintrag (name, file)"""
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

    # ---------------------------------------------------------------- Koppeln
    def check_pairing(self, force=False):
        """Alle paar Minuten fragen, ob der Schluessel noch gilt (nur Bridge, nie der Drucker)."""
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
            log("Schluessel gilt nicht mehr - neu koppeln")
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
            self.pair_msg = {"error": True, "text": f"Bridge nicht erreichbar ({e})"}
            return
        self.key.save(base, res["token"], res.get("device"))
        self.paired, self.paired_checked = True, time.time()
        self.pair_msg = {"error": False, "text": f"Gekoppelt als „{(res.get('device') or {}).get('name', device_name())}“."}
        self.state.pop("bases_reported", None)   # Basisprofile jetzt melden
        log("Mit der Bridge gekoppelt")

    # ---------------------------------------------------------------- Hintergrund
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
                self.bridge_error = f"Bridge nicht erreichbar ({e.__class__.__name__}: {e})"
            if self.pair_code:
                self.redeem_pair_code()
            if not self.bridge_error:
                self.check_pairing()
            if self.sync_request.is_set():
                self.sync_request.clear()
                try:
                    self.sync_profiles()
                except Exception as e:  # noqa: BLE001
                    log("Sync fehlgeschlagen:", e, traceback.format_exc())
                    self.last_sync = {"at": time.strftime("%H:%M:%S"), "written": [], "deleted": [],
                                      "errors": [f"Sync fehlgeschlagen: {e}"]}
            while True:
                try:
                    name = self.saved_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    self.handle_saved(name)
                except Exception as e:  # noqa: BLE001
                    log("Ruecksync fehlgeschlagen:", e, traceback.format_exc())
            self.wake.wait(max(2, int(self.cfg("poll_seconds"))))
            self.wake.clear()

    # ---------------------------------------------------------------- Profil-Sync
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
                base_name = prof.get("base")
                base = self.system.resolve(base_name) if base_name else None
                if base is None:
                    missing.add(base_name)
                    errors.append(f"{prof['display_name']}: Orca-Basisprofil „{base_name or '–'}“ nicht gefunden")
                    continue
                name = safe_name(prof["display_name"], oid, prof.get("material"))
                profile = build_profile_json(base, prof, name)
                old = managed.get(oid)
                path = target / f"{name}.json"
                if old and old.get("name") != name:          # umbenannt: alte Datei weg
                    self._remove_files(Path(old["file"]))
                cache = WRITTEN_DIR / f"{oid}.json"
                prev = None
                if path.exists():
                    # Vergleich mit der Datei auf der Platte: hat jemand das Profil in Orca geaendert und
                    # den Ruecksync abgelehnt, setzt der Sync es auf die Spoolman-Werte zurueck.
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
            # Profile von Filamenten ohne aktive Spule entfernen (nur eigene Dateien)
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
            log(f"Sync: {len(written)} geschrieben, {len(deleted)} entfernt, {len(errors)} Fehler")
            return self.last_sync

    def _report_bases(self):
        """Basisprofil-Namen an die Bridge melden, nur wenn sie sich geaendert haben."""
        names = self.system.names()
        digest = hashlib.sha1("\n".join(names).encode("utf-8")).hexdigest()[:12]
        if not names or self.state.get("bases_reported") == digest:
            return
        if self.paired is False:
            return   # meldet das Plugin nach dem Koppeln
        try:
            self.http("POST", "/api/orca/bases", {"names": names}, timeout=10)
            self.state["bases_reported"] = digest
            log(f"{len(names)} Orca-Basisprofile an die Bridge gemeldet")
        except NotPaired:
            log("Basisprofile melden: Plugin nicht gekoppelt")
        except Exception as e:  # noqa: BLE001
            log("Basisprofile melden fehlgeschlagen:", e)

    def _remove_files(self, path: Path):
        try:
            with open(path, encoding="utf-8") as fh:
                notes = json.load(fh).get("filament_notes") or []
            if not any(MARKER in str(n) for n in notes):
                return False   # nicht von uns - nie anfassen
        except Exception:
            return False
        path.unlink(missing_ok=True)
        path.with_suffix(".info").unlink(missing_ok=True)
        return True

    # ---------------------------------------------------------------- Ruecksync
    def pending_changes(self, preset_name):
        """Nach dem Speichern in Orca: Unterschiede zwischen Orca-Datei und unserem Stand."""
        oid, entry = self.managed_by_name(preset_name)
        if not oid:
            return None, None
        try:
            saved = json.loads(Path(entry["file"]).read_text(encoding="utf-8"))
            written = json.loads((WRITTEN_DIR / f"{oid}.json").read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            log("Ruecksync: Dateien nicht lesbar:", e)
            return oid, None
        return oid, diff_profiles(written, saved)

    def handle_saved(self, name):
        """Ruecksync im Hintergrund-Thread (Dialoge sind thread-sicher)."""
        oid, changes = self.pending_changes(name)
        if not oid or not changes:
            return
        _, entry = self.managed_by_name(name)
        lines = "\n".join(f"  {k} = {v}" for k, v in sorted(changes.items())[:25])
        more = f"\n  … und {len(changes) - 25} weitere" if len(changes) > 25 else ""
        if self.cfg("ask_backsync"):
            answer = orca.host.ui.message(
                f"Du hast das Spoolman-Profil „{name}“ geändert:\n\n{lines}{more}\n\n"
                "Nach Spoolman übernehmen? Bei „Nein“ setzt der nächste Sync das Profil auf die Spoolman-Werte zurück.",
                "Kobra Spoolman", buttons="yes_no", icon="question")
            if answer != "yes":
                return
        try:
            res = self.http("POST", "/api/orca/backsync", {"orca_id": oid, "changes": changes}, timeout=6)
            self.accept_saved(oid, entry)
            ign = res.get("ignored") or []
            notify(f"Kobra Spoolman: nach Spoolman übernommen ({len(res.get('applied', {}))} Werte"
                   + (f", ignoriert: {', '.join(ign)}" if ign else "") + ")")
        except NotPaired:
            orca.host.ui.message("Übernehmen nach Spoolman geht erst, wenn das Plugin mit der Bridge gekoppelt ist.\n\n"
                                 "Code holen: App oder Weboberfläche → Geräte → Gerät hinzufügen, dann im Panel "
                                 "„Kobra Spoolman“ eingeben und danach das Profil noch einmal speichern.",
                                 "Kobra Spoolman", buttons="ok", icon="warning")
        except Exception as e:  # noqa: BLE001
            orca.host.ui.message(f"Übernehmen nach Spoolman fehlgeschlagen:\n{e}", "Kobra Spoolman",
                                 buttons="ok", icon="error")

    # ---------------------------------------------------------------- Verbrauchsvorschau (UI-Thread)
    def on_slice_complete(self):
        """Direkt nach SlicingJobComplete: Orca setzt das Gueltig-Flag erst danach."""
        stats = read_slice_statistics(require_valid=False)
        if stats is None:
            return None
        self.slice = {"stats": stats, "at": time.time(), "from_event": True, "stale": False}
        return self.forecast()

    def refresh_slice(self):
        """Bei jeder Panel-Aktualisierung: gueltiges Slice-Ergebnis der aktuellen Platte lesen."""
        stats = read_slice_statistics(require_valid=True)
        now = time.time()
        if stats is not None:
            self.slice = {"stats": stats, "at": now, "from_event": False, "stale": False}
        elif self.slice and not self.slice["stale"]:
            if not (self.slice["from_event"] and now - self.slice["at"] < 8):
                self.slice["stale"] = True   # Modell/Einstellung geaendert oder andere Platte

    def forecast(self):
        st = self.bridge_state
        if not st or not self.slice or self.slice["stale"]:
            return None
        return build_forecast(self.slice["stats"], st.get("slots"), (st.get("usage") or {}).get("purge"),
                              self.cfg("reserve_g"))

    def accept_saved(self, oid, entry):
        """Die von Orca gespeicherte Datei ist jetzt unser Stand (nach Ruecksync)."""
        try:
            text = Path(entry["file"]).read_text(encoding="utf-8")
            (WRITTEN_DIR / f"{oid}.json").write_text(text, encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            log("Stand uebernehmen fehlgeschlagen:", e)


CONFIG_UI = r"""
<style>
  body { font: 13px system-ui, sans-serif; margin: 12px; color: var(--orca-fg, #222); background: var(--orca-bg, transparent); }
  label { display: block; margin: 10px 0 4px; font-weight: 600; }
  input[type=text], input[type=number] { width: 100%; box-sizing: border-box; padding: 6px 8px; }
  .row { display: flex; gap: 8px; align-items: center; margin: 6px 0; }
  .row label { display: inline; margin: 0; font-weight: normal; }
  .hint { color: var(--orca-muted, #777); font-size: 12px; margin-top: 3px; }
  button { margin-top: 14px; padding: 6px 14px; }
</style>
<label for="bridge_url">Adresse der ace-lane-bridge</label>
<input type="text" id="bridge_url" placeholder="http://192.168.1.10:7913">
<div class="hint">Die Seite, auf der du die ACE-Slots zuordnest (Port 7913).</div>
<label for="user_folder">Orca-Benutzerordner</label>
<input type="text" id="user_folder" placeholder="default">
<div class="hint">Ohne Orca-Anmeldung „default“. Profile landen in user/&lt;ordner&gt;/filament/base.</div>
<label for="poll_seconds">Aktualisierung (Sekunden)</label>
<input type="number" id="poll_seconds" min="2" max="60">
<div class="row"><input type="checkbox" id="sync_on_start"><label for="sync_on_start">Profile beim Orca-Start aktualisieren</label></div>
<div class="row"><input type="checkbox" id="open_panel_on_start"><label for="open_panel_on_start">Panel beim Start öffnen</label></div>
<div class="row"><input type="checkbox" id="ask_backsync"><label for="ask_backsync">Vor dem Rücksync nach Spoolman fragen</label></div>
<div class="row"><input type="checkbox" id="warn_after_slice"><label for="warn_after_slice">Nach dem Slicen warnen, wenn eine Spule nicht reicht</label></div>
<label for="reserve_g">Reserve (g)</label>
<input type="number" id="reserve_g" min="0" max="200">
<div class="hint">Bleibt nach dem Druck weniger als das auf der Spule, zeigt die Vorschau „knapp“.</div>
<button type="button" id="save">Speichern</button> <button type="button" id="defaults">Standardwerte</button>
<script>
(function () {
  var fields = ["bridge_url", "user_folder", "poll_seconds", "reserve_g"], checks = ["sync_on_start", "open_panel_on_start", "ask_backsync", "warn_after_slice"];
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


# ====================================================================== Panel
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
  .fch { display:flex; justify-content:space-between; gap:6px; margin-bottom:4px; }
  .fcl { display:flex; justify-content:space-between; gap:8px; padding:2px 0; }
  .fcn { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; min-width:0; }
  .fca { flex:none; font-variant-numeric:tabular-nums; }
  .fcw { font-size:12px; margin:0 0 2px 8px; }
  .fc details { margin-top:6px; } .fc summary { cursor:pointer; color:var(--orca-muted); font-size:12px; }
  .fct { margin:6px 0 2px; }
</style>
<h3>Kobra Spoolman</h3>
<div id="status" class="muted">lade …</div>
<div id="boxes"></div>
<div id="pair" class="box" style="display:none">
  <b>Plugin koppeln</b>
  <div class="muted" style="margin:4px 0 6px">Nötig für den Rücksync nach Spoolman. Code: App oder Weboberfläche → Geräte → Gerät hinzufügen.</div>
  <div style="display:flex;gap:6px"><input id="paircode" inputmode="numeric" autocomplete="off" placeholder="6-stelliger Code" style="flex:1;min-width:0">
  <button type="button" id="pairbtn">Koppeln</button></div>
  <div id="pairmsg" class="muted" style="margin-top:4px"></div>
</div>
<div id="forecast"></div>
<div id="slots"></div>
<div class="actions">
  <button type="button" id="sync">Profile aktualisieren</button>
  <button type="button" id="refresh" class="quiet">Neu laden</button>
</div>
<div class="muted hint">„Profile aktualisieren“ legt die Orca-Profile aus Spoolman an. In die Filament-Felder kommen sie danach über Orcas Sync-Symbol im Filament-Bereich (bei neuen Profilen erst Orca neu starten).</div>
<div id="usage"></div>
<div id="foot" class="muted"></div>
<script>
(function () {
  function esc(v) { var s = document.createElement("span"); s.textContent = v == null ? "" : String(v); return s.innerHTML; }
  function g(v) { return v == null ? "?" : (Math.round(v * 10) / 10).toLocaleString("de-DE") + " g"; }
  function render(m) {
    document.getElementById("status").innerHTML = m.status;
    document.getElementById("boxes").innerHTML = (m.boxes || []).map(function (b) {
      return '<div class="box' + (b.error ? ' err' : '') + '">' + b.html + '</div>'; }).join("");
    document.getElementById("slots").innerHTML = (m.slots || []).map(function (s) {
      var sw = s.color ? 'style="background:#' + esc(s.color) + '"' : '';
      return '<div class="slot"><div class="sw" ' + sw + '></div><div class="grow">' +
        '<div><b>Slot ' + s.slot + '</b>' + (s.active ? ' · <span class="ok">aktiv</span>' : '') + '</div>' +
        '<div class="name">' + esc(s.name || "nicht zugeordnet") + '</div>' +
        '<div class="muted">' + (s.spool_id ? '#' + s.spool_id + ' · ' + esc(s.material) + ' · ' + g(s.remaining_weight) : esc(s.ace || "")) + '</div>' +
        (s.check ? '<div class="' + s.check_cls + '">' + esc(s.check) + '</div>' : '') +
        (s.use ? '<div class="muted">' + esc(s.use) + '</div>' : '') +
        '</div></div>'; }).join("");
    // aufgeklappte Details ueber die regelmaessige Aktualisierung hinweg offen halten
    var d = document.getElementById("fcd"), open = d ? d.open : false;
    document.getElementById("forecast").innerHTML = m.forecast || "";
    d = document.getElementById("fcd");
    if (d) d.open = open;
    document.getElementById("usage").innerHTML = m.usage || "";
    document.getElementById("foot").innerHTML = m.foot || "";
    // Kopplungsfeld nicht neu zeichnen (sonst ginge die Eingabe verloren), nur ein-/ausblenden
    document.getElementById("pair").style.display = m.pair && m.pair.show ? "" : "none";
    var pm = document.getElementById("pairmsg");
    pm.textContent = (m.pair && m.pair.msg) || "";
    pm.className = m.pair && m.pair.error ? "bad" : "muted";
  }
  function pair() {
    var c = document.getElementById("paircode").value.replace(/\s/g, "");
    if (!c) return;
    document.getElementById("pairmsg").textContent = "koppelt …";
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


def _mm175_to_g(mm):
    return _mm_to_g(mm, 1.75, 1.24)


def _de(v, nd=1):
    return "–" if v is None else f"{v:.{nd}f}".replace(".", ",")


def _esc(s):
    return (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


FC_STATUS = {"ok": ("✓", "ok", "reicht"), "tight": ("⚠", "warn", "knapp"), "short": ("✗", "bad", "reicht nicht"),
             "unknown": ("?", "muted", "Rest unbekannt"), "nospool": ("✗", "bad", "keine Spule zugeordnet"),
             "noslot": ("✗", "bad", "kein ACE-Slot"),
             "nomaterial": ("✗", "bad", "am Drucker kein Material eingetragen")}


def forecast_html(fc):
    """Verbrauchsvorschau: pro Slot eine Zeile (Bedarf / Rest), Aufschluesselung zum Aufklappen.
    Die Orca-Spalten heissen und rechnen wie Orcas Legende (Filament, Modell, Stuetzen,
    Gereinigt, Turm, Gesamt); "Laden" ist das Spuelen der Firmware, das Orca nicht kennt."""
    def g(v, nd=1):
        return _de(v, nd)

    lines = []
    for r in fc["rows"]:
        sym, cls, label = FC_STATUS.get(r["status"], ("", "muted", ""))
        name = _esc(r.get("name") or f"Filament {r['slot']}")
        if r.get("remaining_g") is not None:
            amount = f"{g(r['need_g'])} / {g(r['remaining_g'])} g"
        else:
            amount = f"{g(r['need_g'])} g"
        lines.append(f"<div class='fcl' title='{_esc(label)}'><span class='fcn'><b>Slot {r['slot']}</b> · {name}</span>"
                     f"<span class='fca'>{amount} <span class='{cls}'>{sym}</span></span></div>")
        if r["status"] not in ("ok", "unknown"):
            lines.append(f"<div class='{cls} fcw'>{_esc(label)}</div>")

    cols = [("Modell", "model_g"), ("Stützen", "support_g"), ("Gereinigt", "flush_g"), ("Turm", "tower_g")]
    cols = [c for c in cols if c[1] == "model_g" or any(r[c[1]] for r in fc["rows"])]
    head = "".join(f"<td class='r'>{t}</td>" for t, _ in cols)
    body = "".join(
        f"<tr><td>{r['slot']}</td>" + "".join(f"<td class='r'>{g(r[k], 2)}</td>" for _, k in cols)
        + f"<td class='r'>{g(r['orca_g'], 2)}</td></tr>" for r in fc["rows"])
    orca_tab = (f"<table><tr class='h'><td>Filament</td>{head}<td class='r'>Gesamt</td></tr>{body}"
                f"<tr class='s'><td>Summe</td>{'<td></td>' * len(cols)}<td class='r'>{g(fc['orca_g'], 2)}</td></tr></table>")

    loads = lambda n: _de(n, 0) if float(n).is_integer() else _de(n, 1)  # noqa: E731
    load_rows = "".join(
        f"<tr><td>{r['slot']}</td><td class='r'>{loads(r['loads'])}×</td><td class='r'>{g(r['purge_g'])}</td>"
        f"<td class='r'><b>{g(r['need_g'])}</b></td><td class='r'>{g(r.get('remaining_g'))}</td></tr>"
        for r in fc["rows"])
    load_tab = ("<table><tr class='h'><td>Filament</td><td class='r'>Laden</td><td class='r'>g</td>"
                f"<td class='r'>Bedarf</td><td class='r'>Rest</td></tr>{load_rows}</table>")

    how = ("von Orca gezählt" if fc.get("loads_exact")
           else "gleichmäßig verteilt – genaue Zahl braucht einen neueren orca-kobra-Build")
    m = fc.get("purge_model") or {}
    if fc.get("purge_method") in ("transitions", "colours"):
        learned = m.get("learned_from") or 0
        tuned = (f"an {learned} Druck{'en' if learned != 1 else ''} eingemessen" if learned
                 else "Werte aus den Messungen")
        order = ("pro Farbwechsel" if fc["purge_method"] == "transitions"
                 else "aus den Farben gemittelt – genaue Reihenfolge braucht einen neueren orca-kobra-Build")
        purge_text = (f"{fc['loads']} Ladevorgänge ({how}), {order} aus den Slot-Farben berechnet wie die "
                      f"Firmware (Multiplikator {_de(m.get('flush_multiplier', 1.0), 2)}, {tuned}).")
    else:
        basis = (f"gemessen aus {fc['purge_jobs']} Druck{'en' if fc['purge_jobs'] != 1 else ''}"
                 if fc["purge_measured"] else "Schätzwert, bis die Bridge einen fertigen Druck gemessen hat")
        purge_text = f"{fc['loads']} Ladevorgänge ({how}), je ca. {_de(fc['per_load_g'], 2)} g ({basis})."
    plate = f"Platte {fc['plate'] + 1} · " if isinstance(fc.get("plate"), int) else ""
    return (f"<div class='fc'><div class='fch'><b>Geplanter Verbrauch</b><span class='muted'>{plate}Gramm</span></div>"
            + "".join(lines)
            + "<details id='fcd'><summary>Details (Orca-Legende + Laden)</summary>"
            f"<div class='muted fct'>Wie Orcas Legende (Vorschau → Filament):</div>{orca_tab}"
            f"<div class='muted fct'>Dazu Laden: Die Firmware spült bei jedem Einlegen, das kennt Orca nicht. "
            f"{purge_text}</div>{load_tab}"
            f"<div class='muted fct'>Bedarf = Orca Gesamt + Laden. Rest = was laut Spoolman auf der Spule ist.</div>"
            "</details></div>")


def build_panel_message(core: Core):
    """Laeuft im UI-Thread (Panel-Nachricht): darf Orca-Presets lesen."""
    st = core.bridge_state or {}
    boxes = []
    if core.bridge_error:
        boxes.append({"error": True, "html": _esc(core.bridge_error) +
                      f"<br>Adresse: <code>{_esc(core.cfg('bridge_url'))}</code> – anpassen unter "
                      "<b>Plugins → Kobra Spoolman → Konfiguration</b>."})
    for w in st.get("warnings") or []:
        boxes.append({"error": True, "html": _esc(w)})
    if core.restart_needed:
        boxes.append({"html": "<b>Profile aktualisiert.</b> Orca neu starten, dann Orcas Sync-Symbol im Filament-Bereich drücken."})
    elif st.get("profiles_outdated"):
        boxes.append({"html": "In Spoolman hat sich etwas geändert. <b>Profile aktualisieren</b> und Orca neu starten."})
    ls = core.last_sync or {}
    for e in ls.get("errors") or []:
        boxes.append({"error": True, "html": _esc(e)})

    # aktuelle Filament-Auswahl in Orca (Filament 1..n <-> Slot 1..n)
    selected, loaded = [], set()
    try:
        bundle = orca.host.preset_bundle()
        # Basisprofile, die der Sync nicht gefunden hat: Orca weiss, wo die Datei liegt
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
        log("Presets nicht lesbar:", e)

    # Verbrauchsvorschau nach dem Slicen
    core.refresh_slice()
    fc = core.forecast()
    if fc:
        for r in fc["rows"]:
            if r["status"] in ("short", "nospool", "noslot", "nomaterial"):
                title = "Druck bricht ab:" if r["status"] == "nomaterial" else "Reicht nicht:"
                boxes.append({"error": True, "html": f"<b>{title}</b> " + _esc(forecast_warnings({"rows": [r]})[0])})

    live = ((st.get("usage") or {}).get("live") or {})
    live_by_slot = {x["slot"]: x for x in live.get("slots", [])}
    last_by_slot = (st.get("usage") or {}).get("last") or {}
    slots = []
    for s in st.get("slots") or []:
        item = dict(s)
        item["ace"] = ("ACE: " + (s.get("ace_material") or "leer")) if s.get("present") else "ACE: leer"
        oid = s.get("orca_id")
        idx = s["slot"] - 1
        if oid:
            entry = core.managed().get(oid)
            if not entry:
                item["check"], item["check_cls"] = "Kein Orca-Profil – Profile aktualisieren", "warn"
            elif oid not in loaded:
                item["check"], item["check_cls"] = "Profil angelegt – Orca neu starten", "warn"
            elif idx < len(selected) and selected[idx] == entry["name"]:
                item["check"], item["check_cls"] = f"Filament {s['slot']} in Orca: passt", "ok"
            elif idx < len(selected):
                item["check"] = f"Filament {s['slot']} in Orca ist „{selected[idx]}“ – erwartet „{entry['name']}“ (Sync-Knopf in Orca)"
                item["check_cls"] = "bad"
        if s.get("present") and not s.get("ace_material"):
            item["check"] = "Am Drucker ist kein Material eingetragen – ein Druck mit diesem Slot bricht ab"
            item["check_cls"] = "bad"
        lv = live_by_slot.get(s["slot"])
        la = last_by_slot.get(str(s["slot"])) or last_by_slot.get(s["slot"])
        if lv:
            item["use"] = f"Dieser Druck: {_de(lv['g'])} g"
        elif la:
            item["use"] = f"Letzter Druck: {_de(la['g'])} g"
        slots.append(item)

    purge = (st.get("usage") or {}).get("purge") or {}
    usage = ""
    model = purge.get("model") if isinstance(purge.get("model"), dict) else None
    if model and not (fc and fc["rows"]):
        learned = model.get("learned_from") or 0
        usage = (f"<div class='muted'>Spülen der ACE: Multiplikator {_de(model.get('flush_multiplier', 1.0), 2)}, "
                 "pro Farbwechsel aus den Slot-Farben berechnet"
                 + (f" (an {learned} Druck{'en' if learned != 1 else ''} eingemessen)" if learned else "")
                 + ".</div>")
    elif purge.get("jobs") and not (fc and fc["rows"]):
        usage = (f"<div class='muted'>Mehrverbrauch (Spülen/Anfahren) bisher im Schnitt "
                 f"{_de(_mm175_to_g(purge['overhead_per_load_mm']))} g pro Laden "
                 f"({purge['jobs']} Druck{'e' if purge['jobs'] != 1 else ''}).</div>")
    forecast = ""
    if fc and fc["rows"]:
        forecast = forecast_html(fc)
    elif core.slice and core.slice["stale"]:
        forecast = "<div class='muted'>Vorschau: Slice-Ergebnis nicht mehr aktuell – neu slicen.</div>"
    status = []
    status.append("Bridge " + ("<span class='ok'>verbunden</span>" if st and not core.bridge_error else "<span class='bad'>getrennt</span>"))
    if st and not core.bridge_error and core.paired is not None:
        status.append("gekoppelt" if core.paired else "<span class='warn'>nicht gekoppelt</span>")
    if st:
        status.append(f"Drucker {_esc(st.get('print_state') or '–')}")
    foot = f"Plugin {PLUGIN_VERSION} · Bridge {_esc(st.get('version', '–'))} · {len(core.managed())} Profile"
    if not hasattr(orca.host, "slice_statistics"):
        foot += " · Verbrauchsvorschau braucht orca-kobra (Patch 0003)"
    if ls.get("at"):
        foot += f" · Sync {ls['at']}: {len(ls.get('written', []))} neu/geändert, {len(ls.get('deleted', []))} entfernt"
    pm = core.pair_msg or {}
    pair = {"show": bool(st) and not core.bridge_error and core.paired is False,
            "msg": pm.get("text") if pm.get("error") else None, "error": pm.get("error", False)}
    if pm and not pm.get("error"):
        boxes.insert(0, {"html": _esc(pm["text"])})
        core.pair_msg = None
    return {"command": "state", "status": " · ".join(status), "boxes": boxes, "slots": slots,
            "forecast": forecast, "usage": usage, "foot": foot, "pair": pair}


# ====================================================================== Capabilities
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
        return CONFIG_UI.replace("__DEFAULTS__", json.dumps(DEFAULT_CONFIG))

    def on_load(self):
        core = core_for(self)
        core.start()
        if core.cfg("open_panel_on_start"):
            # Beim Orca-Start laedt das Plugin oft, bevor das Hauptfenster fertig ist - dann
            # verwirft Orca das Panel still. Deshalb im Hintergrund nachfassen, bis es offen ist.
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
                log("Panel oeffnen:", e)
                time.sleep(3)
        log("Panel konnte beim Start nicht geoeffnet werden - ueber den Plugins-Dialog starten")

    def on_unload(self):
        if _core:
            _core.stop.set()
        if self.panel is not None and self.panel.is_open():
            self.panel.close()

    def execute(self):
        self.open_panel()
        return orca.ExecutionResult.success("Kobra Spoolman geöffnet.")

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
        return "Kobra Spoolman: Profile aktualisieren"

    def execute(self):
        # Netzwerk und Dateien laufen im Hintergrund-Thread; das Ergebnis zeigt das Panel.
        core = core_for(self)
        core.start()
        core.sync_request.set()
        core.wake.set()
        return orca.ExecutionResult.success("Sync gestartet - Ergebnis im Panel „Kobra Spoolman“.")


@orca.plugin
class KobraSpoolmanPlugin(orca.base):
    def register_capabilities(self):
        orca.register_capability(KobraPanel)
        orca.register_capability(KobraSync)
