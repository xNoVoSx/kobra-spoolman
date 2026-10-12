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

from aiohttp import web

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


def index_html(tag: str = TAG, page: str = "index.html") -> str:
    with open(os.path.join(STATIC, page), encoding="utf-8") as fh:
        html = fh.read()
    html = html.replace('"static/', f'"assets/{tag}/')
    return html.replace("<head>", f'<head>\n<meta name="ui-tag" content="{tag}">', 1)


async def index(_: web.Request) -> web.Response:
    return web.Response(text=index_html(), content_type="text/html", headers={"Cache-Control": NO_CACHE})


async def viewer(_: web.Request) -> web.Response:
    """Only the 3D view of the print file (app, sharing in the home network)."""
    return web.Response(text=index_html(page="viewer.html"), content_type="text/html", headers={"Cache-Control": NO_CACHE})


async def display(_: web.Request) -> web.Response:
    """Printer display (800x480, kiosk browser on the Klipper Pi)."""
    return web.Response(text=index_html(page="display.html"), content_type="text/html",
                        headers={"Cache-Control": NO_CACHE})


async def asset(request: web.Request) -> web.StreamResponse:
    """assets/<tag>/<path>: current TAG -> immutable; old TAG (an old, open page) -> not cached."""
    rel = request.match_info["path"]
    path = os.path.realpath(os.path.join(STATIC, rel))
    if not path.startswith(os.path.realpath(STATIC) + os.sep) or not os.path.isfile(path):
        raise web.HTTPNotFound()
    cache = IMMUTABLE if request.match_info["tag"] == TAG else NO_CACHE
    return web.FileResponse(path, headers={"Cache-Control": cache})


def add_routes(app: web.Application) -> None:
    app.router.add_get("/", index)
    app.router.add_get("/viewer", viewer)
    app.router.add_get("/display", display)
    app.router.add_get("/assets/{tag}/{path:.+}", asset)
    # old URLs (licenses, links): still reachable, but always revalidated
    app.router.add_static("/static", STATIC, append_version=False)
