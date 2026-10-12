"""Translations of web UI and display (static/js/i18n.js, static/i18n/de.json).

Every t("...") in the JavaScript needs a German entry with the same {placeholders}, nothing unused stays in the catalog,
and no German is left in the code (strings, comments, markup). A line that must stay German carries the marker
``i18n: printer text``. t() takes double-quoted literals only, so this test finds them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "bridge" / "app" / "acebridge" / "static"
CATALOG = STATIC / "i18n" / "de.json"
KEEP = "i18n: printer text"
T_CALL = re.compile(r"\bt\(\s*(\"(?:[^\"\\]|\\.)*\")")
FIELD = re.compile(r"\{(\w+)\}")
UMLAUT = re.compile(r"[äöüÄÖÜß„]")
GERMAN_WORDS = {
    "und", "der", "die", "das", "nicht", "wenn", "fuer", "für", "ueber", "über", "mit", "ist", "sind", "wird",
    "werden", "kein", "keine", "noch", "auch", "oder", "beim", "nach", "vom", "zum", "zur", "dann", "sonst",
    "aber", "schon", "nur", "jetzt", "bis", "wie", "sich", "einen", "eine", "ein", "dem", "den", "des", "auf",
    "aus", "bei", "hier", "alle", "alles", "gibt", "kann", "muss", "soll", "darf", "neu", "waehrend", "während",
}


def _sources():
    files = sorted((STATIC / "js").glob("*.js")) + sorted(STATIC.glob("*.html"))
    return files


def _templates():
    found = {}
    for path in sorted((STATIC / "js").glob("*.js")):
        if path.name == "i18n.js":                   # its comment shows an example call
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for m in T_CALL.finditer(line):
                found.setdefault(json.loads(m.group(1)), []).append(f"{path.name}:{i}")
    return found


def test_web_catalog_complete_and_consistent():
    cat = json.loads(CATALOG.read_text(encoding="utf-8"))
    used = _templates()
    missing = {k: v for k, v in used.items() if k not in cat}
    unused = sorted(k for k in cat if k not in used)
    bad = {k: (sorted(FIELD.findall(k)), sorted(FIELD.findall(cat[k]))) for k in used
           if k in cat and sorted(FIELD.findall(k)) != sorted(FIELD.findall(cat[k]))}
    assert not missing, f"t() without German entry in static/i18n/de.json: {missing}"
    assert not unused, f"catalog entries no t() uses any more: {unused}"
    assert not bad, f"placeholders differ: {bad}"


def _german(text):
    words = set(re.findall(r"[a-zäöüß]+", text.lower()))
    return bool(UMLAUT.search(text)) or len(words & GERMAN_WORDS) >= 2


def test_no_german_left_in_web_code():
    hits = {}
    for path in _sources():
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if KEEP in line:
                continue
            code = T_CALL.sub("t()", line)          # the English source texts may contain any word
            if _german(code):
                hits.setdefault(path.name, []).append(i)
    assert not hits, "German left (file: lines): " + str({k: v[:15] for k, v in hits.items()})
