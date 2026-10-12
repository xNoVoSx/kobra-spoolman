"""Slot hints are recognised by their English template (slots.hint_level) - the constants must match the tr() texts."""

from __future__ import annotations

import json
from pathlib import Path

from acebridge import slots
from acebridge.i18n import tr

CATALOG = json.loads((Path(slots.__file__).parent / "locale" / "de.json").read_text(encoding="utf-8"))


def test_templates_exist_as_texts():
    for t in (*slots.HINT_ERROR, *slots.HINT_WARN, slots.UNKNOWN_TAG):
        assert t in CATALOG, t                     # catalog = exactly the tr() templates of the code


def test_levels_independent_of_language():
    err = tr("The ACE knows no material for this slot – assign a spool")
    warn = tr("ACE reports {ace}, assigned is {spool}", ace="PLA", spool="PETG")
    assert slots.hint_level(err) == "error" and slots.hint_level(warn) == "warn"
    assert slots.hint_level(tr("will be moved to the shelf after the print")) == "info"
    assert slots.is_unknown_tag_event(tr(slots.UNKNOWN_TAG, slot=1, nr=1234))
    assert not slots.is_unknown_tag_event("Slot 1: something else")
