"""The "start here" pages (docs/start.md, docs/de/start.md) list every feature of the bridge's register (features.py),
and every relative link in them points at an existing file and heading."""

from __future__ import annotations

import json
import pathlib
import re

from acebridge import features

ROOT = pathlib.Path(__file__).resolve().parents[1]
DE = json.loads((ROOT / "bridge/app/acebridge/locale/de.json").read_text(encoding="utf-8"))


def _anchors(path: pathlib.Path) -> set:
    return {features._slug(h) for h in re.findall(r"^#+ (.+)$", path.read_text(encoding="utf-8"), re.M)}


def test_every_feature_is_on_the_start_pages():
    en = (ROOT / "docs/start.md").read_text(encoding="utf-8")
    de = (ROOT / "docs/de/start.md").read_text(encoding="utf-8")
    for f in features.FEATURES:
        if f.key in ("spools", "web"):          # the core itself is goal 1
            continue
        title = str(f.title)
        assert f"| {title} |" in en, f"{f.key}: '{title}' missing in docs/start.md"
        german = DE.get(title, title)
        assert f"| {german} |" in de, f"{f.key}: '{german}' missing in docs/de/start.md"


def test_links_on_the_start_pages_resolve():
    for page in ("docs/start.md", "docs/de/start.md"):
        path = ROOT / page
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            if target.startswith("http"):
                continue
            file, _, anchor = target.partition("#")
            dest = (path.parent / file).resolve() if file else path
            assert dest.exists(), f"{page}: {target} – file missing"
            if anchor:
                assert anchor in _anchors(dest), f"{page}: {target} – heading missing"
