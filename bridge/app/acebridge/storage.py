"""Dateien im Datenordner sicher schreiben: erst in eine temporaere Datei, auf die Platte bringen, dann umbenennen.

Bricht der Strom oder der Container mitten im Schreiben ab, bleibt die alte Datei ganz - nie eine halbe oder leere.
Alle Module der Bridge, die Zustand in `DATA_DIR` halten, schreiben ueber diese Funktionen.
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterable, Optional


def save_json(path: str, data: Any, indent: Optional[int] = None) -> None:
    """JSON atomar schreiben (UTF-8, Umlaute unveraendert)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=indent)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def save_lines(path: str, lines: Iterable[str]) -> None:
    """Textzeilen (mit Zeilenende) atomar schreiben, z. B. gekuerzte JSONL-Protokolle."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.writelines(lines)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
