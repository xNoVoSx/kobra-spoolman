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
"""

from __future__ import annotations

from typing import Any, Dict, Optional

PROXY = "172.30.32.2"
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
