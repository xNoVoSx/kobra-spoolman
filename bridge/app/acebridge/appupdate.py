"""App-Update ueber die Bridge: der Release-Workflow legt die signierte APK samt app.json ins Docker-Image
(acebridge/appdist/). Die App fragt /api/app/update und laedt bei neuerer Version /api/app/update/apk -
so passen Bridge und App immer zusammen, und die App braucht kein Internet."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

log = logging.getLogger("appupdate")
APPDIST = os.path.join(os.path.dirname(__file__), "appdist")


def load(folder: str = APPDIST) -> Optional[Dict[str, Any]]:
    """app.json lesen und pruefen, dass die APK daneben liegt; sonst None (z.B. Image vom main-Zweig)."""
    try:
        with open(os.path.join(folder, "app.json"), encoding="utf-8") as fh:
            info = json.load(fh)
        path = os.path.join(folder, os.path.basename(info["file"]))
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        return {"version": str(info["version"]), "code": int(info["code"]), "size": os.path.getsize(path),
                "changes": [str(c) for c in info.get("changes") or []], "path": path}
    except FileNotFoundError:
        return None
    except Exception as e:  # noqa: BLE001
        log.warning("App-Update in %s unlesbar: %s", folder, e)
        return None


def public(info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not info:
        return {"available": False}
    return {"available": True, **{k: info[k] for k in ("version", "code", "size", "changes")},
            "url": "/api/app/update/apk"}
