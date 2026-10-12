"""Translations of the Orca plugin (orca-plugin/kobra_spoolman.py, German texts in DE at its end).

Every text the plugin translates - tr("...") calls (found with ast, so implicitly joined strings count as one),
the panel's data-t texts (PANEL_TEXTS), the {{...}} texts of the settings page and the forecast labels - needs a
German entry with the same {placeholders}; nothing unused stays in DE, and no German is left outside DE.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from test_i18n_web import FIELD, _german

PLUGIN = Path(__file__).resolve().parents[1] / "orca-plugin" / "kobra_spoolman.py"
KEEP = "i18n: keep"


def _module():
    return ast.parse(PLUGIN.read_text(encoding="utf-8"))


def _assigned(tree, name):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found")


def _used(tree):
    found = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr" and node.args
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            found.add(node.args[0].value)
    found.update(_assigned(tree, "PANEL_TEXTS"))
    found.update(re.findall(r"\{\{(.+?)\}\}", _assigned(tree, "CONFIG_UI")))
    found.update(label for _, _, label in _assigned(tree, "FC_STATUS").values())
    return found


def test_plugin_catalog_complete_and_consistent():
    tree = _module()
    de = _assigned(tree, "DE")
    used = _used(tree)
    missing = sorted(k for k in used if k not in de)
    unused = sorted(k for k in de if k not in used)
    bad = {k: (sorted(FIELD.findall(k)), sorted(FIELD.findall(de[k]))) for k in used
           if k in de and sorted(FIELD.findall(k)) != sorted(FIELD.findall(de[k]))}
    assert not missing, f"tr() without German entry in DE: {missing}"
    assert not unused, f"DE entries no tr() uses any more: {unused}"
    assert not bad, f"placeholders differ: {bad}"


def test_panel_texts_match_the_page():
    tree = _module()
    page = _assigned(tree, "PAGE")
    in_page = set(re.findall(r'data-tp?="([^"]+)"', page)) | set(re.findall(r'\bt\("([^"]+)"\)', page))
    assert in_page == set(_assigned(tree, "PANEL_TEXTS"))


def test_no_german_left_in_the_plugin():
    lines = PLUGIN.read_text(encoding="utf-8").splitlines()
    end = next(i for i, line in enumerate(lines) if line.startswith("DE = {"))
    hits = [i for i, line in enumerate(lines[:end], 1) if KEEP not in line and _german(line)]
    assert not hits, f"German left in the plugin (lines): {hits[:20]}"
