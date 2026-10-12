"""Translations (acebridge/i18n.py): English source, German catalog, language per request.

The checks at the bottom keep the code English: every tr() template needs a German entry (and nothing unused stays in
the catalog), and no German may be left in strings, comments or docstrings. A line that must stay German (it matches
output of the private Klipper modules, which are German) carries the marker ``i18n: printer text``.
"""

from __future__ import annotations

import ast
import io
import json
import re
import string
import tokenize
from pathlib import Path

import pytest

from acebridge import i18n
from acebridge.i18n import localize, request_lang, tr

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "bridge" / "app" / "acebridge"
CATALOG = PKG / "locale" / "de.json"
KEEP = "i18n: printer text"

# Words that only appear in German text (lower case, whole words). Kept short and unambiguous.
GERMAN_WORDS = {
    "und", "der", "die", "das", "nicht", "wenn", "fuer", "für", "ueber", "über", "mit", "ist", "sind", "wird",
    "werden", "kein", "keine", "noch", "auch", "oder", "beim", "nach", "vom", "zum", "zur", "dann", "sonst",
    "aber", "schon", "nur", "jetzt", "bis", "wie", "sich", "einen", "eine", "ein", "dem", "den", "des", "auf",
    "aus", "bei", "hier", "alle", "alles", "gibt", "kann", "muss", "soll", "darf", "neu", "waehrend", "während",
}
UMLAUT = re.compile(r"[äöüÄÖÜß„]")


@pytest.fixture(autouse=True)
def default_en():
    i18n.bind(lambda: "en")
    yield
    i18n.bind(lambda: "en")


# ------------------------------------------------------------------ behaviour
def test_text_is_english_str_and_renders_german(monkeypatch):
    monkeypatch.setitem(i18n._catalogs, "de", {"Spool {n} assigned to slot {slot}": "Spule {n} in Slot {slot}",
                                               "dryer": "Trockner"})
    t = tr("Spool {n} assigned to slot {slot}", n=7, slot=tr("dryer"))
    assert t == "Spool 7 assigned to slot dryer" and isinstance(t, str)
    assert t.render("de") == "Spule 7 in Slot Trockner"
    assert localize({"a": [t, 1, None]}, "de") == {"a": ["Spule 7 in Slot Trockner", 1, None]}
    assert localize({"a": t}, "en") == {"a": "Spool 7 assigned to slot dryer"}
    assert tr("Not in the catalog").render("de") == "Not in the catalog"      # missing -> English


def test_language_of_request_and_default():
    assert request_lang({"X-Lang": "de"}) == "de"
    assert request_lang({"Accept-Language": "fr-FR,de;q=0.8,en;q=0.5"}) == "de"
    assert request_lang({"X-Lang": "de"}, {"lang": "en"}) == "en"
    assert request_lang({}) is None
    i18n.bind(lambda: "de")
    assert i18n.current_lang() == "de"
    token = i18n.use("en")
    assert i18n.current_lang() == "en"
    i18n.reset(token)
    i18n.bind(lambda: "xx")
    assert i18n.current_lang() == "en"


def test_response_follows_device_language(cfg, monkeypatch):
    import asyncio

    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from acebridge.web import language
    from acebridge.webcommon import json_response
    monkeypatch.setitem(i18n._catalogs, "de", {"Dryer": "Trockner"})

    async def handler(_):
        return json_response({"label": tr("Dryer")})

    async def main():
        app = web.Application(middlewares=[language])
        app.router.add_get("/x", handler)
        async with TestClient(TestServer(app)) as c:
            out = []
            for headers in ({}, {"X-Lang": "de"}, {"Accept-Language": "de-DE"}):
                out.append((await (await c.get("/x", headers=headers)).json())["label"])
            return out
    assert asyncio.run(main()) == ["Dryer", "Trockner", "Trockner"]


# ------------------------------------------------------------------ the code stays English
def _sources():
    return sorted(PKG.rglob("*.py"))


def _templates():
    """Every tr("literal", ...) in the package -> {template: [file:line]}."""
    found = {}
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "tr"
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                found.setdefault(node.args[0].value, []).append(f"{path.name}:{node.lineno}")
    return found


def _fields(s):
    return sorted(f for _, f, _, _ in string.Formatter().parse(s) if f)


def test_catalog_complete_and_consistent():
    cat = json.loads(CATALOG.read_text(encoding="utf-8"))
    used = _templates()
    missing = {t: w for t, w in used.items() if t not in cat}
    unused = sorted(t for t in cat if t not in used)
    bad = {t: (_fields(t), _fields(cat[t])) for t in used if t in cat and _fields(t) != _fields(cat[t])}
    assert not missing, f"tr() without German entry in locale/de.json: {missing}"
    assert not unused, f"catalog entries no tr() uses any more: {unused}"
    assert not bad, f"placeholders differ: {bad}"


def _german(text):
    words = set(re.findall(r"[a-zäöüß]+", text.lower()))
    return bool(UMLAUT.search(text)) or len(words & GERMAN_WORDS) >= 2


def _german_lines(path):
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    hits = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type not in (tokenize.COMMENT, tokenize.STRING):
            continue
        row = tok.start[0]
        if KEEP in lines[row - 1] or (tok.type == tokenize.STRING and KEEP in lines[min(row, len(lines) - 1)]):
            continue
        if _german(tok.string):
            hits.append(f"{path.relative_to(ROOT)}:{row}")
    return hits


def test_no_german_left_in_bridge_code():
    hits = [h for p in _sources() for h in _german_lines(p)]
    per_file = {}
    for h in hits:
        per_file[h.rsplit(":", 1)[0]] = per_file.get(h.rsplit(":", 1)[0], 0) + 1
    assert not hits, f"German text left (file: lines): {per_file}\nfirst: {hits[:20]}"


def test_decimal_comma_in_german(monkeypatch):
    monkeypatch.setitem(i18n._catalogs, "de", {"{rh:g} % for {min:.1f} min": "{rh:g} % seit {min:.1f} min"})
    t = tr("{rh:g} % for {min:.1f} min", rh=45.5, min=2.25)
    assert t == "45.5 % for 2.2 min" and t.render("de") == "45,5 % seit 2,2 min"
