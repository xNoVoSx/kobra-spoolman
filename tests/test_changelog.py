"""Doku-Pflicht: jede Version hat ihre Eintraege (Einstellungen der Weboberflaeche, CHANGELOG.md, App)."""

from __future__ import annotations

import re
from pathlib import Path

from acebridge import CHANGELOG, __version__

ROOT = Path(__file__).resolve().parents[1]
MD = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_web_changelog_has_current_version():
    assert CHANGELOG[0][0] == __version__, "Bridge-Version fehlt in CHANGELOG (acebridge/__init__.py, Einstellungen)"
    assert all(items for _, _, items in CHANGELOG)


def test_changelog_md_has_current_version():
    assert f"## [{__version__}]" in MD, "Bridge-Version fehlt in CHANGELOG.md"


def test_changelog_md_has_current_app_version():
    props = (ROOT / "android/app/version.properties").read_text(encoding="utf-8")
    app = re.search(r"^versionName=(\S+)", props, re.M).group(1)
    assert f"## app {app} " in MD, "App-Version fehlt in CHANGELOG.md (## app x.y.z – Datum, Text der Update-Karte)"


def test_web_and_md_list_the_same_bridge_versions():
    md_versions = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", MD, re.M)
    web = [v for v, _, _ in CHANGELOG]
    newest = md_versions[: len(web)]
    assert web == newest, "Einstellungen und CHANGELOG.md haben verschiedene Versionen"
