import asyncio
import io
import os

import numpy as np
import pytest
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from kobravision.detector import Detector, nms, postprocess
from kobravision.server import Config, build_app

MODEL = os.environ.get("MODEL_PATH", "")


def test_nms_keeps_the_best_of_overlapping_boxes():
    boxes = np.array([[0.1, 0.1, 0.4, 0.4], [0.12, 0.12, 0.42, 0.42], [0.6, 0.6, 0.9, 0.9]], dtype=np.float32)
    scores = np.array([0.5, 0.9, 0.3], dtype=np.float32)
    assert nms(boxes, scores, 0.45) == [1, 2]


def test_postprocess_threshold_and_relative_boxes():
    boxes = np.zeros((1, 3, 1, 4), dtype=np.float32)
    boxes[0, :, 0] = [[0.1, 0.2, 0.3, 0.6], [0.5, 0.5, 0.7, 0.9], [0.0, 0.0, 1.0, 1.0]]
    confs = np.array([[[0.6], [0.2], [0.05]]], dtype=np.float32)       # die dritte liegt unter 0.08
    out = postprocess(boxes, confs, ["failure"])
    assert [round(d[1], 2) for d in out] == [0.6, 0.2]
    name, conf, (xc, yc, w, h) = out[0]
    assert name == "failure" and (xc, yc, w, h) == pytest.approx((0.2, 0.4, 0.2, 0.4), abs=1e-4)


class FakeSession:
    """Statt des 200-MB-Modells: liefert immer eine Box."""
    def get_inputs(self):
        class Inp:
            name, shape = "input", [1, 3, 32, 32]
        return [Inp()]

    def get_providers(self):
        return ["CPUExecutionProvider"]

    def run(self, _, feeds):
        assert feeds["input"].shape == (1, 3, 32, 32)
        boxes = np.array([[[[0.2, 0.2, 0.4, 0.6]]]], dtype=np.float32)
        return [boxes, np.array([[[0.7]]], dtype=np.float32)]


def jpeg(color=(40, 40, 40)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(b, "JPEG")
    return b.getvalue()


def test_lazy_load_and_unload_after_idle(monkeypatch):
    t = [0.0]
    d = Detector("x.onnx", ["failure"], unload_after_s=600, clock=lambda: t[0])
    loads = []
    monkeypatch.setattr(d, "_load", lambda: (loads.append(1), setattr(d, "_session", FakeSession()),
                                             setattr(d, "provider", "CPUExecutionProvider")))
    assert not d.loaded
    r = d.detect(jpeg())
    assert d.loaded and loads == [1] and r.width == 64 and r.detections[0][1] == pytest.approx(0.7)
    t[0] = 599
    assert not d.unload_if_idle()
    t[0] = 601
    assert d.unload_if_idle() and not d.loaded
    d.detect(jpeg())
    assert loads == [1, 1]                                            # beim naechsten Bild wieder geladen


def test_http_api_with_token(monkeypatch):
    d = Detector("x.onnx", ["failure"])
    monkeypatch.setattr(d, "_load", lambda: setattr(d, "_session", FakeSession()))
    cfg = Config(model_path="x.onnx", token="geheim")

    async def go():
        async with TestClient(TestServer(build_app(cfg, d))) as c:
            assert (await c.get("/v1/health")).status == 200
            assert (await c.post("/v1/detect", data=jpeg())).status == 401
            h = {"Authorization": "Bearer geheim"}
            assert (await c.post("/v1/detect", data=b"kein bild", headers=h)).status == 422
            r = await c.post("/v1/detect", data=jpeg(), headers=h)
            body = await r.json()
            assert r.status == 200 and body["detections"][0][0] == "failure" and body["width"] == 64
    asyncio.run(go())


@pytest.mark.skipif(not MODEL or not os.path.exists(MODEL), reason="MODEL_PATH mit Obicos ONNX-Modell setzen")
def test_real_model_sees_spaghetti_but_not_a_clean_print():
    imgs = os.environ.get("TEST_IMAGES", "")
    d = Detector(MODEL, ["failure"])
    score = {f: sum(c for _, c, _ in d.detect(open(os.path.join(imgs, f), "rb").read()).detections)
             for f in ("kobra_clean.jpg", "spaghetti_monster.jpg")}
    assert score["kobra_clean.jpg"] < 0.1 and score["spaghetti_monster.jpg"] > 0.78
