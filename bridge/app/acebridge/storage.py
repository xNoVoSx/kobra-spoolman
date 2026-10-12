"""Write files in the data folder safely: first to a temporary file, flush it to disk, then rename.

If power or the container dies in the middle of writing, the old file stays whole - never half or empty.
Every bridge module that keeps state in `DATA_DIR` writes through these functions.
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterable, Optional


def save_json(path: str, data: Any, indent: Optional[int] = None) -> None:
    """Write JSON atomically (UTF-8, non-ASCII characters kept as they are)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=indent)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def save_lines(path: str, lines: Iterable[str]) -> None:
    """Write text lines (with line endings) atomically, e.g. trimmed JSONL logs."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.writelines(lines)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
