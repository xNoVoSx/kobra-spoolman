"""Serving the web UI with a fingerprint.

Without cache headers browsers keep old JS/CSS files after an update (Ctrl+Shift+R needed, old UI meets new API).
Therefore:
- TAG = fingerprint of all files in static/ (computed at start). The start page points to assets/<TAG>/..., is never
  cached itself and names the TAG in <meta name="ui-tag">.
- Everything under assets/<TAG>/ is immutable (cached for a year). New files -> new TAG -> new URLs.
- /api/app/state reports the TAG; an open page with an old TAG reloads itself.
"""

from __future__ import annotations

import hashlib
import os
import re
from html import escape
from typing import Any, Dict, Optional

from aiohttp import web

from . import i18n, ingress

STATIC = os.path.join(os.path.dirname(__file__), "static")
IMMUTABLE = "public, max-age=31536000, immutable"
NO_CACHE = "no-cache"


def fingerprint(root: str = STATIC) -> str:
    h = hashlib.sha256()
    for base, dirs, files in sorted(os.walk(root)):
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(base, name)
            h.update(os.path.relpath(path, root).encode())
            with open(path, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()[:12]


TAG = fingerprint()


def index_html(tag: str = TAG, page: str = "index.html", extra: Optional[Dict[str, str]] = None) -> str:
    """The page with its assets under assets/<tag>/. extra: further <meta> tags (name -> content), e.g. ingress."""
    with open(os.path.join(STATIC, page), encoding="utf-8") as fh:
        html = fh.read()
    html = html.replace('"static/', f'"assets/{tag}/')
    # the bridge default language; a device's own choice (localStorage) wins in static/js/i18n.js
    html = re.sub(r'<html lang="[a-z]+">', f'<html lang="{i18n.default_lang()}">', html, count=1)
    metas = [f'<meta name="ui-tag" content="{tag}">'] + [
        f'<meta name="{name}" content="{escape(value, quote=True)}">' for name, value in (extra or {}).items()]
    return html.replace("<head>", "<head>\n" + "\n".join(metas), 1)


def _page(page: str, cfg: Any = None):
    async def handler(request: web.Request) -> web.Response:
        return web.Response(text=index_html(page=page, extra=ingress.meta(request, cfg)), content_type="text/html",
                            headers={"Cache-Control": NO_CACHE})
    return handler


async def asset(request: web.Request) -> web.StreamResponse:
    """assets/<tag>/<path>: current TAG -> immutable; old TAG (an old, open page) -> not cached."""
    rel = request.match_info["path"]
    path = os.path.realpath(os.path.join(STATIC, rel))
    if not path.startswith(os.path.realpath(STATIC) + os.sep) or not os.path.isfile(path):
        raise web.HTTPNotFound()
    cache = IMMUTABLE if request.match_info["tag"] == TAG else NO_CACHE
    return web.FileResponse(path, headers={"Cache-Control": cache})


def add_routes(app: web.Application, cfg: Any = None) -> None:
    app.router.add_get("/", _page("index.html", cfg))
    app.router.add_get("/viewer", _page("viewer.html", cfg))      # only the 3D view of the print file
    app.router.add_get("/display", _page("display.html", cfg))    # printer display (800x480, kiosk on the Klipper Pi)
    app.router.add_get("/assets/{tag}/{path:.+}", asset)
    # old URLs (licenses, links): still reachable, but always revalidated
    app.router.add_static("/static", STATIC, append_version=False)
