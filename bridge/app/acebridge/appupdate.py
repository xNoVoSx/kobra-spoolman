"""App update through the bridge: the release workflow puts the signed APK and app.json into the Docker image
(acebridge/appdist/). The app asks /api/app/update and, for a newer version, downloads /api/app/update/apk -
so bridge and app always match, and the app needs no internet."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

log = logging.getLogger("appupdate")
APPDIST = os.path.join(os.path.dirname(__file__), "appdist")


def load(folder: str = APPDIST) -> Optional[Dict[str, Any]]:
    """Read app.json and check that the APK is next to it; else None (e.g. an image built from main)."""
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
        log.warning("App update in %s unreadable: %s", folder, e)
        return None


def public(info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not info:
        return {"available": False}
    return {"available": True, **{k: info[k] for k in ("version", "code", "size", "changes")},
            "url": "/api/app/update/apk"}
