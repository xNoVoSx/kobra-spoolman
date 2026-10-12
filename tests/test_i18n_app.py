"""Translations of the Android app (data/I18n.kt, app/src/main/assets/i18n/de.json).

Every tr("...") in the Kotlin code needs a German entry with the same {placeholders}, nothing unused stays in the
catalog, no tr() text uses Kotlin string templates ($x would change the text before the lookup), and no German is
left in the code (strings, comments). A line that must stay German (test data, e.g. a Spoolman colour name) carries
the marker ``i18n: keep``. Android resources: values/ and values-de/ have the same names.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from test_i18n_web import FIELD, _german

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "android" / "app" / "src"
CATALOG = APP / "main" / "assets" / "i18n" / "de.json"
KEEP = "i18n: keep"
TR_CALL = re.compile(r"\btr\(\s*(\"(?:[^\"\\]|\\.)*\")")


def _literal(raw: str) -> str:
    return json.loads(raw.replace("\\$", "$"))


def _templates():
    found = {}
    for path in sorted((APP / "main" / "kotlin").rglob("*.kt")):
        if path.name == "I18n.kt":                   # its comment shows an example call
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for m in TR_CALL.finditer(line):
                found.setdefault(m.group(1), []).append(f"{path.name}:{i}")
    return found


def test_app_catalog_complete_and_consistent():
    cat = json.loads(CATALOG.read_text(encoding="utf-8"))
    raw = _templates()
    templated = {k: v for k, v in raw.items() if re.search(r"(?<!\\)\$", k)}
    assert not templated, f"tr() with a Kotlin string template - use {{name}} placeholders: {templated}"
    used = {_literal(k): v for k, v in raw.items()}
    missing = {k: v for k, v in used.items() if k not in cat}
    unused = sorted(k for k in cat if k not in used)
    bad = {k: (sorted(FIELD.findall(k)), sorted(FIELD.findall(cat[k]))) for k in used
           if k in cat and sorted(FIELD.findall(k)) != sorted(FIELD.findall(cat[k]))}
    assert not missing, f"tr() without German entry in assets/i18n/de.json: {missing}"
    assert not unused, f"catalog entries no tr() uses any more: {unused}"
    assert not bad, f"placeholders differ: {bad}"


def test_no_german_left_in_app_code():
    files = (sorted(APP.rglob("*.kt")) + [APP / "main" / "AndroidManifest.xml"]
             + sorted((APP / "main" / "res").rglob("*.xml")))
    hits = {}
    for path in files:
        if "values-de" in path.parts:
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if KEEP in line:
                continue
            if _german(TR_CALL.sub("tr()", line)):
                hits.setdefault(str(path.relative_to(APP)), []).append(i)
    assert not hits, "German left (file: lines): " + str({k: v[:15] for k, v in hits.items()})


def test_android_resources_translated():
    def names(folder):
        tree = ET.parse(APP / "main" / "res" / folder / "strings.xml")
        return {e.get("name") for e in tree.getroot() if e.get("translatable") != "false"}
    assert names("values") == names("values-de")
