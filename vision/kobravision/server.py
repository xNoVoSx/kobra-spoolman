"""HTTP interface of kobra-vision. The bridge sends a JPEG and gets the detections back.

    POST /v1/detect   body: JPEG (Content-Type image/jpeg) -> {"detections": [[class, confidence, [xc, yc, w, h]]],
                      "ms", "width", "height", "provider"}  (box relative to the image, 0..1)
    GET  /v1/health   state: model loaded?, CPU/CUDA, version

With VISION_TOKEN set every request needs "Authorization: Bearer <token>" (except /v1/health).
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import os
from dataclasses import dataclass, field
from typing import List

from aiohttp import web

from . import __version__
from .detector import Detector

log = logging.getLogger("server")


def _bool(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Config:
    model_path: str = "/models/obico-failure.onnx"
    names: List[str] = field(default_factory=lambda: ["failure"])
    host: str = "0.0.0.0"
    port: int = 7917
    threads: int = 2
    use_gpu: bool = False
    unload_after_s: float = 600
    token: str = ""
    max_image_bytes: int = 8 * 1024 * 1024

    @classmethod
    def from_env(cls) -> "Config":
        e = os.environ.get
        return cls(model_path=e("MODEL_PATH", cls.model_path),
                   names=[n.strip() for n in e("MODEL_NAMES", "failure").split(",") if n.strip()],
                   host=e("HTTP_HOST", cls.host), port=int(e("HTTP_PORT", cls.port)),
                   threads=int(e("THREADS", cls.threads)), use_gpu=_bool(e("USE_GPU", "false")),
                   unload_after_s=float(e("UNLOAD_AFTER_S", cls.unload_after_s)), token=e("VISION_TOKEN", ""))


def build_app(cfg: Config, detector: Detector) -> web.Application:
    app = web.Application(client_max_size=cfg.max_image_bytes)

    @web.middleware
    async def auth(request: web.Request, handler):
        if cfg.token and request.path != "/v1/health":
            got = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            if not hmac.compare_digest(got, cfg.token):
                return web.json_response({"error": "Key missing or wrong"}, status=401)
        return await handler(request)

    app.middlewares.append(auth)

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"ok": os.path.exists(cfg.model_path), "version": __version__,
                                  "model": {"name": os.path.basename(cfg.model_path), "loaded": detector.loaded,
                                            "provider": detector.provider, "loads": detector.loads},
                                  "threads": cfg.threads, "gpu": cfg.use_gpu})

    async def detect(request: web.Request) -> web.Response:
        body = await request.read()
        if not body:
            return web.json_response({"error": "No image (JPEG expected as the body)"}, status=400)
        try:
            res = await asyncio.get_running_loop().run_in_executor(None, detector.detect, body)
        except OSError as e:          # Pillow: not a readable image
            return web.json_response({"error": f"Image not readable: {e}"}, status=422)
        return web.json_response({"detections": [[n, c, list(b)] for n, c, b in res.detections], "ms": res.ms,
                                  "width": res.width, "height": res.height, "provider": detector.provider})

    async def unloader(app_: web.Application):
        async def loop():
            while True:
                await asyncio.sleep(30)
                detector.unload_if_idle()
        task = asyncio.create_task(loop())
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    app.router.add_get("/v1/health", health)
    app.router.add_post("/v1/detect", detect)
    app.cleanup_ctx.append(unloader)
    return app


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cfg = Config.from_env()
    if not os.path.exists(cfg.model_path):
        log.error("Model missing: %s", cfg.model_path)
    log.info("kobra-vision %s on %s:%s (model %s, %s threads, GPU %s, unloaded after %.0f min)", __version__,
             cfg.host, cfg.port, os.path.basename(cfg.model_path), cfg.threads, "on" if cfg.use_gpu else "off",
             cfg.unload_after_s / 60)
    det = Detector(cfg.model_path, cfg.names, cfg.threads, cfg.use_gpu, cfg.unload_after_s)
    web.run_app(build_app(cfg, det), host=cfg.host, port=cfg.port, access_log=None, print=None)
