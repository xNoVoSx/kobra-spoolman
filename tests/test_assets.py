"""Weboberflaeche mit Fingerabdruck: nach einem Update nie alte JS/CSS-Dateien aus dem Browser-Cache."""

from __future__ import annotations

import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from acebridge import assets


def client_call(fn):
    async def go():
        app = web.Application()
        assets.add_routes(app)
        async with TestClient(TestServer(app)) as c:
            return await fn(c)
    return asyncio.run(go())


def test_index_points_to_fingerprinted_assets():
    async def fn(c):
        r = await c.get("/")
        return r.headers["Cache-Control"], await r.text()
    cache, html = client_call(fn)
    assert cache == "no-cache"
    assert f'<meta name="ui-tag" content="{assets.TAG}">' in html
    assert f'src="assets/{assets.TAG}/js/main.js"' in html and '"static/' not in html


def test_current_assets_are_immutable_old_ones_not():
    async def fn(c):
        cur = await c.get(f"/assets/{assets.TAG}/js/main.js")
        old = await c.get("/assets/altertag/js/main.js")
        bad = await c.get(f"/assets/{assets.TAG}/../__init__.py")
        missing = await c.get(f"/assets/{assets.TAG}/js/gibtsnicht.js")
        return cur.status, cur.headers["Cache-Control"], old.status, old.headers["Cache-Control"], bad.status, missing.status
    cur, cur_cache, old, old_cache, bad, missing = client_call(fn)
    assert (cur, old) == (200, 200)
    assert "immutable" in cur_cache and old_cache == "no-cache"
    assert bad == 404 and missing == 404


def test_fingerprint_changes_with_content(tmp_path):
    (tmp_path / "a.js").write_text("eins")
    first = assets.fingerprint(str(tmp_path))
    (tmp_path / "a.js").write_text("zwei")
    assert assets.fingerprint(str(tmp_path)) != first


def test_viewer_page_for_the_app():
    async def fn(c):
        r = await c.get("/viewer?q=lines")
        return r.status, r.headers["Cache-Control"], await r.text()
    status, cache, html = client_call(fn)
    assert status == 200 and cache == "no-cache"
    assert f'src="assets/{assets.TAG}/js/viewer-page.js"' in html and '"static/' not in html
