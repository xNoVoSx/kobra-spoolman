"""Fehldruck-Erkennung mit Obicos "failure"-Modell (ONNX, YOLO mit einer Klasse).

Das Modell kommt aus obico-server (AGPL-3.0) und wird nicht im Repo mitgeliefert, sondern beim Bauen des
Images geladen (Dockerfile, Pruefsumme). Ausgabe wie Obicos ml_api: Liste (Klasse, Sicherheit, Box) ab
DETECT_THRESH - die Bewertung ueber die Zeit macht die Bridge.

Laeuft auf der CPU (Obicos Modell braucht mit 2 Threads ~50 ms pro Bild) oder per CUDA, wenn
onnxruntime-gpu installiert ist. Geladen wird erst beim ersten Bild; nach UNLOAD_AFTER_S ohne Bild wird
das Modell wieder entladen (Speicher/Grafikkarte frei, solange nicht gedruckt wird).
"""

from __future__ import annotations

import io
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

import numpy as np
from PIL import Image

log = logging.getLogger("detector")

DETECT_THRESH = 0.08     # wie Obicos ml_api: ab hier zaehlt eine Box
NMS_THRESH = 0.45

# (Klasse, Sicherheit, (x-Mitte, y-Mitte, Breite, Hoehe) relativ zum Bild 0..1)
Detection = Tuple[str, float, Tuple[float, float, float, float]]


def nms(boxes: np.ndarray, scores: np.ndarray, thresh: float) -> List[int]:
    """Non-Maximum-Suppression: ueberlappende Boxen (IoU > thresh) auf die sicherste reduzieren."""
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]
    keep: List[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        rest = order[1:]
        w = np.maximum(0.0, np.minimum(x2[i], x2[rest]) - np.maximum(x1[i], x1[rest]))
        h = np.maximum(0.0, np.minimum(y2[i], y2[rest]) - np.maximum(y1[i], y1[rest]))
        inter = w * h
        union = areas[i] + areas[rest] - inter
        iou = np.where(union > 0, inter / np.maximum(union, 1e-9), 0.0)
        order = rest[iou <= thresh]
    return keep


def postprocess(boxes: np.ndarray, confs: np.ndarray, names: List[str],
                thresh: float = DETECT_THRESH, nms_thresh: float = NMS_THRESH) -> List[Detection]:
    """Modell-Ausgabe -> Funde. boxes: [1, N, 1, 4] (x1, y1, x2, y2 relativ), confs: [1, N, Klassen]."""
    b = boxes[0, :, 0, :]
    c = confs[0]
    best = c.max(axis=1)
    cls = c.argmax(axis=1)
    out: List[Detection] = []
    for k in range(c.shape[1]):
        sel = (best > thresh) & (cls == k)
        if not sel.any():
            continue
        kb, ks = b[sel], best[sel]
        for i in nms(kb, ks, nms_thresh):
            x1, y1, x2, y2 = (float(v) for v in np.clip(kb[i], 0.0, 1.0))
            out.append((names[k] if k < len(names) else str(k), round(float(ks[i]), 4),
                        (round((x1 + x2) / 2, 4), round((y1 + y2) / 2, 4), round(x2 - x1, 4), round(y2 - y1, 4))))
    out.sort(key=lambda d: d[1], reverse=True)
    return out


@dataclass
class Result:
    detections: List[Detection]
    ms: float
    width: int
    height: int


class Detector:
    """Laedt das Modell bei Bedarf, entlaedt es nach Leerlauf. Thread-sicher (ein Bild nach dem anderen)."""

    def __init__(self, model_path: str, names: List[str], threads: int = 2, use_gpu: bool = False,
                 unload_after_s: float = 600, clock: Callable[[], float] = time.monotonic):
        self.model_path = model_path
        self.names = names
        self.threads = threads
        self.use_gpu = use_gpu
        self.unload_after_s = unload_after_s
        self.clock = clock
        self._session = None
        self._lock = threading.Lock()
        self.last_used: Optional[float] = None
        self.provider: Optional[str] = None
        self.loads = 0

    @property
    def loaded(self) -> bool:
        return self._session is not None

    def _load(self):
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = self.threads
        so.log_severity_level = 3
        wanted = ["CUDAExecutionProvider", "CPUExecutionProvider"] if self.use_gpu else ["CPUExecutionProvider"]
        providers = [p for p in wanted if p in ort.get_available_providers()] or ["CPUExecutionProvider"]
        t = time.monotonic()
        self._session = ort.InferenceSession(self.model_path, so, providers=providers)
        self.provider = self._session.get_providers()[0]
        self.loads += 1
        log.info("Modell geladen (%s, %.1f s)", self.provider, time.monotonic() - t)

    def unload_if_idle(self) -> bool:
        with self._lock:
            if self._session is not None and self.last_used is not None \
                    and self.clock() - self.last_used >= self.unload_after_s:
                self._session = None
                log.info("Modell entladen (%.0f min ohne Bild)", self.unload_after_s / 60)
                return True
        return False

    def detect(self, jpeg: bytes) -> Result:
        img = Image.open(io.BytesIO(jpeg)).convert("RGB")
        with self._lock:
            if self._session is None:
                self._load()
            s = self._session
            inp = s.get_inputs()[0]
            h, w = int(inp.shape[2]), int(inp.shape[3])
            x = np.asarray(img.resize((w, h), Image.BILINEAR), dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
            t = time.monotonic()
            boxes, confs = s.run(None, {inp.name: x})[:2]
            ms = (time.monotonic() - t) * 1000
            self.last_used = self.clock()
        return Result(postprocess(boxes, confs, self.names), round(ms, 1), img.width, img.height)
