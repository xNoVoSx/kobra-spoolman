"""Home Assistant ingress: the web UI inside the HA sidebar (e.g. as a HA add-on).

The Supervisor proxies `/api/hassio_ingress/<token>/...` to the bridge's `/...` and adds the header `X-Ingress-Path`.
Every request through ingress comes from the Supervisor's proxy at 172.30.32.2; Home Assistant has already logged the
user in (developers.home-assistant.io/docs/add-ons/presentation#ingress).

- The web UI uses relative paths only, so it works under any base path without changes.
- The start page tells the browser it runs under ingress (`<meta name="ingress">`): the camera then fetches single
  images instead of the MJPEG stream (CAMERA_INGRESS_SNAPSHOTS), copyable links (camera, app pairing) point at the
  bridge's direct address (BRIDGE_PUBLIC_URL, else the HA host on HTTP_PORT) - an ingress link needs a HA login.
- HA_INGRESS_TRUST (default off): a request that really comes from the ingress proxy counts as a paired device
  ("Home Assistant"), so nobody has to pair the HA sidebar. The header alone is never trusted - anyone in the network
  could send it to the direct port.
- IngressPath: the add-on's own ingress path for the app's way from outside through Home Assistant (app setting
  "Remote access", GET /api/app/remote).
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, Optional

import aiohttp

from .storage import save_json

log = logging.getLogger("ingress")

PROXY = "172.30.32.2"
SUPERVISOR = "http://supervisor"
VALID = re.compile(r"^/api/hassio_ingress/[A-Za-z0-9_-]+$")
HEADER = "X-Ingress-Path"
DEVICE: Dict[str, Any] = {"id": "ha_ingress", "name": "Home Assistant (ingress)", "kind": "browser",
                          "created": None, "last_seen": None}


def path(request: Any) -> str:
    """The ingress base path (`/api/hassio_ingress/<token>`), "" outside ingress."""
    return str((getattr(request, "headers", None) or {}).get(HEADER) or "").strip()


def via_ingress(request: Any) -> bool:
    """Came through the Supervisor's ingress proxy (header and source address)."""
    return bool(path(request)) and getattr(request, "remote", None) == PROXY


def meta(request: Any, cfg: Any) -> Optional[Dict[str, str]]:
    """What the start page tells the browser under ingress, None outside."""
    if not via_ingress(request):
        return None
    return {"ingress": "snapshots" if getattr(cfg, "camera_ingress_snapshots", True) else "stream",
            "bridge-url": str(getattr(cfg, "bridge_public_url", "") or "").rstrip("/"),
            "bridge-port": str(getattr(cfg, "http_port", 7913))}


class IngressPath:
    """The add-on's ingress path (`/api/hassio_ingress/<token>`): the app reaches the bridge through Home Assistant
    with it when it is away from home. Learned from the first request through the ingress proxy, or asked from the
    Supervisor at start when the bridge runs as an add-on (SUPERVISOR_TOKEN; every add-on may read /addons/self/info).
    Kept in ingress.json - an add-on keeps its token across restarts and updates."""

    def __init__(self, data_dir: str):
        self.file = os.path.join(data_dir, "ingress.json")
        self.path = ""
        try:
            with open(self.file, encoding="utf-8") as fh:
                self.path = str(json.load(fh).get("path") or "")
        except FileNotFoundError:
            pass
        except Exception as e:  # noqa: BLE001
            log.warning("ingress.json unreadable (%s) - learning the ingress path again", e)

    def _set(self, p: str, source: str) -> None:
        p = p.strip().rstrip("/")
        if not VALID.match(p) or p == self.path:
            return
        self.path = p
        save_json(self.file, {"path": p})
        log.info("Home Assistant ingress path %s (%s)", p, source)

    def seen(self, request: Any) -> None:
        """Remember the path of a request through the ingress proxy (cheap: only on a change it writes)."""
        if via_ingress(request):
            self._set(path(request), "request")

    async def discover(self, session: Any, token: Optional[str] = None, base: str = SUPERVISOR) -> None:
        """As an add-on: ask the Supervisor for the own ingress entry. Outside an add-on (no token) nothing happens."""
        token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN", "")
        if not token:
            return
        try:
            async with session.get(base + "/addons/self/info", headers={"Authorization": f"Bearer {token}"},
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = (await resp.json(content_type=None)).get("data") or {}
        except Exception as e:  # noqa: BLE001
            log.info("Supervisor did not tell the ingress path (%s) - it is learned from the first ingress request", e)
            return
        self._set(str(data.get("ingress_entry") or ""), "Supervisor")

    def view(self) -> Dict[str, Any]:
        return {"ha_ingress": self.path or None, "addon": bool(os.environ.get("SUPERVISOR_TOKEN"))}
