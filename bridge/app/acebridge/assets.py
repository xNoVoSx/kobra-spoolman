"""Auslieferung der Weboberflaeche mit Fingerabdruck.

Ohne Cache-Angaben behalten Browser alte JS/CSS-Dateien nach einem Update (Strg+Shift+R noetig, alte
Oberflaeche trifft auf neue API). Deshalb:
- TAG = Fingerabdruck aller Dateien in static/ (beim Start berechnet). Die Startseite verweist auf
  assets/<TAG>/..., ist selbst nie zwischengespeichert und nennt den TAG in <meta name="ui-tag">.
- Unter assets/<TAG>/ ist alles unveraenderlich (ein Jahr Cache). Neue Dateien -> neuer TAG -> neue Adressen.
- /api/app/state meldet den TAG; eine offene Seite mit altem TAG laedt sich selbst neu.
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
    """Nur die 3D-Ansicht der Druckdatei (App, Teilen im Heimnetz)."""
    return web.Response(text=index_html(page="viewer.html"), content_type="text/html", headers={"Cache-Control": NO_CACHE})


async def display(_: web.Request) -> web.Response:
    """Drucker-Display (800x480, Kiosk-Browser auf dem Klipper-Pi)."""
    return web.Response(text=index_html(page="display.html"), content_type="text/html",
                        headers={"Cache-Control": NO_CACHE})


async def asset(request: web.Request) -> web.StreamResponse:
    """assets/<tag>/<pfad>: aktueller TAG -> unveraenderlich; alter TAG (alte, offene Seite) -> ohne Cache."""
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
    # alte Adressen (Lizenzen, Links): weiter erreichbar, aber immer frisch pruefen
    app.router.add_static("/static", STATIC, append_version=False)
