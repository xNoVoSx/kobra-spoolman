"""KI-Fehldruck-Erkennung: Bilder an kobra-vision schicken, Funde ueber die Zeit bewerten, melden, sammeln.

Ablauf im Druck (nur Status "printing"): alle VISION_INTERVAL_S ein Bild von der Kamera (camera.still() - das
aktuelle Bild, wenn jemand zuschaut, sonst ein Einzelabruf; die Bildpumpe startet dafuer nicht) an den Dienst.
Der liefert Boxen mit Sicherheit; die Summe p eines Bildes allein ist zu unruhig. Bewertet wird wie bei Obico
(obico-server, backend/lib/prediction.py - hier eigenstaendig umgesetzt): gleitender Mittelwert (EWM) gegen
eine Grundlinie ueber viele Drucke, mit einer unteren und oberen Schwelle; die ersten Bilder eines Drucks
zaehlen nicht. Stufen: ok -> warn (melden) -> fail (deutlich; mit VISION_ACTION=pause wird pausiert).

Gemeldet wird als rote Meldung (key ai-warn / ai-fail): die App macht daraus einen Alarm mit Kamerabild und
den Knoepfen "Pausieren" / "Fehlalarm". "Fehlalarm" schaltet die KI fuer den Rest des Drucks stumm und
markiert das Bild als Trainingsbeispiel.

Bildersammlung (fuer Stufe 2/3: Platte pruefen, eigenes Modell): DATA_DIR/vision/jobs/<druck>/ - beim Start,
jede VISION_SAVE_EVERY_S, jedes verdaechtige Bild, beim Ende; frames.jsonl mit Wert, Funden, Schicht. Ueber
VISION_DATASET_GB werden die aeltesten Drucke geloescht.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Callable, Deque, Dict, List, Optional

import aiohttp

from .camera import CameraError

if TYPE_CHECKING:
    from .camera import Camera
    from .config import Config
    from .moonraker import Moonraker

log = logging.getLogger("vision")

# Werte wie Obico (obico-server, backend/config/settings.py), abgestimmt auf ~1 Bild alle 10 s
EWM_SPAN = 12
ROLLING_WIN_SHORT = 310
ROLLING_WIN_LONG = 7200
THRESHOLD_LOW = 0.38
THRESHOLD_HIGH = 0.78
INIT_SAFE_FRAMES = 30            # die ersten ~5 min eines Drucks zaehlen nicht (erste Schicht, Spuelen)
SHORT_MULTIPLE = 3.8
ESCALATING_FACTOR = 1.75         # warn -> fail
SUSPECT_P = THRESHOLD_LOW * 0.2  # ab hier wird das Bild gesammelt
HISTORY = 360                    # Verlauf fuer die Anzeige (~1 h bei 10 s)
EVENTS_KEPT = 50
HEALTH_EVERY_S = 300
DOWN_AFTER_S = 60                # so lange keine Antwort im Druck -> Meldung


@dataclass
class Prediction:
    """Bewertung ueber die Zeit. long/lifetime bleiben ueber Drucke hinweg (Grundlinie dieses Druckers)."""
    p: float = 0.0
    ewm: float = 0.0
    short: float = 0.0
    long: float = 0.0
    frames: int = 0
    lifetime: int = 0

    def new_print(self) -> None:
        self.p, self.ewm, self.short, self.frames = 0.0, 0.0, 0.0, 0

    def update(self, p: float) -> None:
        alpha = 2 / (EWM_SPAN + 1)
        self.p = p
        self.frames += 1
        self.lifetime += 1
        self.ewm = p * alpha + self.ewm * (1 - alpha)
        self.short += (p - self.short) / float(min(ROLLING_WIN_SHORT, self.frames + 1))
        self.long += (p - self.long) / float(min(ROLLING_WIN_LONG, self.lifetime + 1))

    def _failing(self, sensitivity: float, factor: float) -> bool:
        if self.frames < INIT_SAFE_FRAMES:
            return False
        adj = (self.ewm - self.long) * sensitivity / factor
        if adj < THRESHOLD_LOW:
            return False
        if adj > THRESHOLD_HIGH:
            return True
        return adj > (self.short - self.long) * SHORT_MULTIPLE

    def level(self, sensitivity: float = 1.0) -> str:
        if self._failing(sensitivity, ESCALATING_FACTOR):
            return "fail"
        return "warn" if self._failing(sensitivity, 1.0) else "ok"

    def score(self, sensitivity: float = 1.0) -> float:
        """0..1 fuer die Anzeige: bis 1/3 unauffaellig, bis 2/3 Warnung, darueber Fehldruck."""
        warn = min(THRESHOLD_HIGH, max(THRESHOLD_LOW, (self.short - self.long) * SHORT_MULTIPLE))
        fail = warn * ESCALATING_FACTOR
        p = (self.ewm - self.long) * sensitivity

        def scale(v, a, b, lo, hi):
            return min(hi, max(lo, lo + (v - a) * (hi - lo) / (b - a)))
        if p > fail:
            return round(scale(p, fail, fail * 1.5, 2 / 3, 1.0), 3)
        if p > warn:
            return round(scale(p, warn, fail, 1 / 3, 2 / 3), 3)
        return round(scale(p, 0, warn, 0.0, 1 / 3), 3)


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:60].strip("_") or "druck"


class Vision:
    def __init__(self, cfg: "Config", moon: "Moonraker", camera: "Camera", session: aiohttp.ClientSession,
                 clock: Callable[[], float] = time.time):
        self.cfg = cfg
        self.moon = moon
        self.camera = camera
        self.session = session
        self.clock = clock
        self.enabled = bool(cfg.vision_url)
        self.dir = os.path.join(cfg.data_dir, "vision")
        self.pred = Prediction()
        self.level = "ok"
        self.detections: List[List[Any]] = []
        self.size: Optional[List[int]] = None
        self.history: Deque[List[float]] = deque(maxlen=HISTORY)
        self.events: List[Dict[str, Any]] = []
        self.event: Optional[Dict[str, Any]] = None      # offenes Ereignis des laufenden Drucks
        self.muted = False                                # "Fehlalarm" -> Rest des Drucks still
        self.paused_by_ai = False
        self.health: Dict[str, Any] = {}
        self.last_ok: Optional[float] = None
        self.last_try: Optional[float] = None
        self.error: Optional[str] = None
        self.ms: Optional[float] = None
        self.job: Optional[str] = None
        self._state = ""
        self._last_check = 0.0
        self._last_save = 0.0
        self._last_health = 0.0
        self._load()

    # ------------------------------------------------------------ Speichern
    def _path(self, *parts: str) -> str:
        return os.path.join(self.dir, *parts)

    def _load(self) -> None:
        try:
            with open(self._path("state.json"), encoding="utf-8") as f:
                data = json.load(f)
            self.pred.long = float(data.get("long", 0.0))
            self.pred.lifetime = int(data.get("lifetime", 0))
            self.events = list(data.get("events", []))[-EVENTS_KEPT:]
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            log.warning("vision/state.json unlesbar, fange neu an: %s", e)

    def _save(self) -> None:
        os.makedirs(self.dir, exist_ok=True)
        tmp = self._path("state.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"long": self.pred.long, "lifetime": self.pred.lifetime, "events": self.events[-EVENTS_KEPT:]}, f)
        os.replace(tmp, self._path("state.json"))

    def _save_frame(self, img: bytes, kind: str, extra: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Bild in den Ordner des Drucks, Zeile in frames.jsonl. Rueckgabe: Pfad relativ zu vision/."""
        if not self.job or self.cfg.vision_dataset_gb <= 0:
            return None
        try:
            d = self._path("jobs", self.job)
            os.makedirs(d, exist_ok=True)
            now = self.clock()
            name = f"{time.strftime('%H%M%S', time.localtime(now))}_{kind}_{self.pred.p:.2f}.jpg"
            with open(os.path.join(d, name), "wb") as f:
                f.write(img)
            ps = self.moon.status.get("print_stats") or {}
            info = ps.get("info") or {}
            line = {"t": round(now, 1), "frame": name, "kind": kind, "p": round(self.pred.p, 4),
                    "ewm": round(self.pred.ewm, 4), "level": self.level, "detections": self.detections,
                    "file": ps.get("filename"), "layer": info.get("current_layer"),
                    "progress": (self.moon.status.get("virtual_sdcard") or {}).get("progress"), **(extra or {})}
            with open(os.path.join(d, "frames.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(line) + "\n")
            return os.path.join("jobs", self.job, name)
        except OSError as e:
            log.warning("Bild nicht gespeichert: %s", e)
            return None

    def prune(self) -> int:
        """Aelteste Drucke loeschen, bis die Sammlung unter VISION_DATASET_GB liegt. Rueckgabe: geloeschte Drucke."""
        root = self._path("jobs")
        if not os.path.isdir(root):
            return 0
        limit = self.cfg.vision_dataset_gb * 1024 ** 3
        jobs = []
        for name in sorted(os.listdir(root)):
            p = os.path.join(root, name)
            if os.path.isdir(p):
                size = sum(os.path.getsize(os.path.join(p, f)) for f in os.listdir(p))
                jobs.append((name, size))
        total = sum(s for _, s in jobs)
        removed = 0
        for name, size in jobs:
            if total <= limit or name == self.job:
                continue
            shutil.rmtree(os.path.join(root, name), ignore_errors=True)
            total -= size
            removed += 1
        if removed:
            log.info("Bildersammlung: %d alte Drucke gelöscht (Grenze %.1f GB)", removed, self.cfg.vision_dataset_gb)
        return removed

    def dataset(self) -> Dict[str, Any]:
        root = self._path("jobs")
        jobs, frames, size = 0, 0, 0
        if os.path.isdir(root):
            for name in os.listdir(root):
                p = os.path.join(root, name)
                if os.path.isdir(p):
                    jobs += 1
                    for f in os.listdir(p):
                        size += os.path.getsize(os.path.join(p, f))
                        frames += f.endswith(".jpg")
        return {"jobs": jobs, "frames": frames, "mb": round(size / 1024 ** 2, 1), "limit_gb": self.cfg.vision_dataset_gb}

    # ------------------------------------------------------------ Dienst
    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.cfg.vision_token}"} if self.cfg.vision_token else {}

    async def check_health(self) -> None:
        self._last_health = self.clock()
        try:
            async with self.session.get(f"{self.cfg.vision_url}/v1/health", timeout=aiohttp.ClientTimeout(total=5)) as r:
                self.health = await r.json()
            self.error = None if self.health.get("ok") else "Modell fehlt im Dienst"
        except Exception as e:  # noqa: BLE001
            self.health = {}
            self.error = f"KI-Dienst nicht erreichbar: {e.__class__.__name__}"

    async def analyze(self, img: bytes) -> Dict[str, Any]:
        async with self.session.post(f"{self.cfg.vision_url}/v1/detect", data=img,
                                     headers={"Content-Type": "image/jpeg", **self._headers()},
                                     timeout=aiohttp.ClientTimeout(total=30)) as r:
            body = await r.json(content_type=None)
            if r.status != 200:
                raise RuntimeError(body.get("error") or f"HTTP {r.status}")
            return body

    # ------------------------------------------------------------ Ablauf
    def _print_state(self) -> str:
        return (self.moon.status.get("print_stats") or {}).get("state") or ""

    async def on_state(self, old: str, new: str) -> None:
        """Druckbeginn: neue Bewertung, Startbild. Druckende: Endbild, Ereignis schliessen."""
        if new == "printing" and old not in ("printing", "paused"):
            fname = (self.moon.status.get("print_stats") or {}).get("filename") or "druck"
            self.job = time.strftime("%Y%m%d-%H%M%S", time.localtime(self.clock())) + "_" + \
                _safe(os.path.splitext(os.path.basename(fname))[0])
            self.pred.new_print()
            self.level, self.detections, self.event, self.muted, self.paused_by_ai = "ok", [], None, False, False
            self.history.clear()
            self._last_check = 0.0
            self._last_save = self.clock()
            await self._grab("start")
        elif old in ("printing", "paused") and new not in ("printing", "paused"):
            await self._grab("end", {"result": new})
            self.event = None
            self.level = "ok"
            self.prune()

    async def _grab(self, kind: str, extra: Optional[Dict[str, Any]] = None) -> None:
        """Bild nur sammeln (Start/Ende), ohne Bewertung."""
        try:
            img, _ = await self.camera.still()
        except CameraError:
            return
        self._save_frame(img, kind, extra)

    async def tick(self) -> None:
        """Wird jede Sekunde aufgerufen."""
        if not self.enabled:
            return
        st = self._print_state()
        if st != self._state:
            old, self._state = self._state, st
            await self.on_state(old, st)
        now = self.clock()
        if now - self._last_health >= HEALTH_EVERY_S:
            await self.check_health()
        if st == "printing" and now - self._last_check >= self.cfg.vision_interval_s:
            self._last_check = now
            await self.check()

    async def check(self) -> None:
        self.last_try = self.clock()
        try:
            img, _ = await self.camera.still()
            res = await self.analyze(img)
        except CameraError as e:
            self.error = f"Kein Kamerabild: {e}"
            return
        except Exception as e:  # noqa: BLE001
            self.error = f"KI-Dienst nicht erreichbar: {e}" if not isinstance(e, RuntimeError) else f"KI-Dienst: {e}"
            return
        self.error, self.last_ok = None, self.clock()
        self.detections = [d for d in res.get("detections", []) if isinstance(d, list) and len(d) == 3]
        self.size = [res.get("width"), res.get("height")]
        self.ms = res.get("ms")
        model = self.health.setdefault("model", {})
        model["loaded"] = True                       # hat gerade ein Bild ausgewertet
        if res.get("provider"):
            model["provider"] = res["provider"]
        self.pred.update(sum(float(d[1]) for d in self.detections))
        self.history.append([round(self.last_ok), round(self.pred.p, 3), self.pred.score(self.cfg.vision_sensitivity)])
        old, self.level = self.level, self.pred.level(self.cfg.vision_sensitivity)

        now = self.clock()
        if self.level != "ok" and not self.muted and (self.event is None or self._rank(self.level) > self._rank(old)):
            await self._raise(img)
        elif self.pred.p > SUSPECT_P:
            self._save_frame(img, "suspect")
        elif now - self._last_save >= self.cfg.vision_save_every_s:
            self._last_save = now
            self._save_frame(img, "periodic")
        if self.pred.lifetime % 30 == 0:
            self._save()

    @staticmethod
    def _rank(level: str) -> int:
        return {"ok": 0, "warn": 1, "fail": 2}.get(level, 0)

    async def _raise(self, img: bytes) -> None:
        frame = self._save_frame(img, "event")
        ev = {"id": uuid.uuid4().hex[:12], "at": round(self.clock(), 1), "job": self.job, "level": self.level,
              "p": round(self.pred.p, 3), "score": self.pred.score(self.cfg.vision_sensitivity), "frame": frame,
              "detections": self.detections, "size": self.size, "verdict": None,
              "file": (self.moon.status.get("print_stats") or {}).get("filename")}
        self.event = ev
        self.events.append(ev)
        self.events = self.events[-EVENTS_KEPT:]
        self._save()
        log.warning("KI: %s (Wert %.2f, %d Funde) – %s", "Fehldruck wahrscheinlich" if self.level == "fail"
                    else "verdächtig", self.pred.p, len(self.detections), ev["file"])
        if self.level == "fail" and self.cfg.vision_action == "pause" and not self.paused_by_ai:
            try:
                await self.moon.action("printer.print.pause", "PAUSE (KI)", source="KI")
                self.paused_by_ai = True
                ev["paused"] = True
            except Exception as e:  # noqa: BLE001
                log.error("KI: Pause fehlgeschlagen: %s", e)

    def feedback(self, event_id: str, verdict: str) -> Dict[str, Any]:
        """verdict: false_alarm (Fehlalarm: Rest des Drucks still) oder confirmed (stimmt)."""
        if verdict not in ("false_alarm", "confirmed"):
            raise ValueError("verdict muss false_alarm oder confirmed sein")
        ev = next((e for e in self.events if e.get("id") == event_id), None)
        if ev is None:
            raise KeyError(event_id)
        ev["verdict"] = verdict
        ev["verdict_at"] = round(self.clock(), 1)
        if self.event and self.event.get("id") == event_id:
            if verdict == "false_alarm":
                self.muted = True
                self.event = None
        # Kennzeichnung fuer die Trainingsdaten neben dem Bild
        if ev.get("frame"):
            d = self._path(os.path.dirname(ev["frame"]))
            if os.path.isdir(d):
                with open(os.path.join(d, "labels.jsonl"), "a", encoding="utf-8") as f:
                    f.write(json.dumps({"frame": os.path.basename(ev["frame"]), "verdict": verdict,
                                        "detections": ev.get("detections")}) + "\n")
        self._save()
        log.info("KI: Rückmeldung %s für %s", "Fehlalarm" if verdict == "false_alarm" else "stimmt", event_id)
        return ev

    def frame_path(self, event_id: str) -> Optional[str]:
        ev = next((e for e in self.events if e.get("id") == event_id), None)
        if not ev or not ev.get("frame"):
            return None
        p = os.path.normpath(self._path(ev["frame"]))
        return p if p.startswith(os.path.normpath(self.dir) + os.sep) and os.path.exists(p) else None

    # ------------------------------------------------------------ Anzeige
    def messages(self) -> List[Dict[str, str]]:
        if not self.enabled:
            return []
        out = []
        ev = self.event
        if ev and not self.muted:
            if ev["level"] == "fail":
                text = "KI: wahrscheinlich Fehldruck (Spaghetti)" + (" – Druck pausiert" if ev.get("paused") else
                                                                     " – Kamera prüfen")
            else:
                text = "KI: Druck sieht verdächtig aus – Kamera prüfen"
            out.append({"level": "error", "text": text, "key": f"ai-{ev['level']}"})
        st = self._print_state()
        if st == "printing" and self.error and self.last_try and \
                (self.last_ok is None or self.clock() - self.last_ok >= DOWN_AFTER_S):
            out.append({"level": "warn", "text": self.error, "key": "ai-down"})
        return out

    def status_line(self) -> Dict[str, Any]:
        base = {"key": "ai", "label": "KI"}
        if not self.enabled:
            return {**base, "state": "off", "detail": "aus (VISION_URL nicht gesetzt)"}
        if self.error:
            return {**base, "state": "warn", "detail": self.error}
        prov = ((self.health.get("model") or {}).get("provider") or "").replace("ExecutionProvider", "")
        where = {"CPU": "CPU", "CUDA": "Grafikkarte"}.get(prov, prov or "bereit")
        if self._print_state() == "printing":
            if self.muted:
                return {**base, "state": "ok", "detail": "für diesen Druck stumm (Fehlalarm)"}
            s = self.pred.score(self.cfg.vision_sensitivity)
            word = {"ok": "unauffällig", "warn": "verdächtig", "fail": "Fehldruck?"}[self.level]
            if self.pred.frames < INIT_SAFE_FRAMES:
                word = f"lernt den Druck ({self.pred.frames}/{INIT_SAFE_FRAMES})"
            return {**base, "state": {"ok": "ok", "warn": "warn", "fail": "bad"}[self.level],
                    "detail": f"{word} · Wert {s:.2f} · {where}"}
        return {**base, "state": "ok", "detail": f"bereit · {where}" + (" · Modell entladen" if not
                                                                           (self.health.get("model") or {}).get("loaded") else "")}

    def summary(self) -> Dict[str, Any]:
        """Kurzform fuer /api/app/state und die Weboberflaeche."""
        ev = self.event
        return {"enabled": self.enabled, "level": self.level, "muted": self.muted,
                "score": self.pred.score(self.cfg.vision_sensitivity) if self.enabled else None,
                "detections": self.detections if self.enabled and self._print_state() == "printing" else [],
                "size": self.size,
                "event": {k: ev[k] for k in ("id", "at", "level", "p", "score")} if ev and not self.muted else None}

    def state(self) -> Dict[str, Any]:
        return {**self.summary(), "url_set": self.enabled, "action": self.cfg.vision_action,
                "interval_s": self.cfg.vision_interval_s, "sensitivity": self.cfg.vision_sensitivity,
                "error": self.error, "ms": self.ms, "health": self.health, "prediction": asdict(self.pred),
                "history": list(self.history), "events": self.events[-20:][::-1], "dataset": self.dataset(),
                "job": self.job}

    async def run(self) -> None:
        if not self.enabled:
            return
        log.info("KI: %s, alle %.0f s im Druck, %s, Sammlung bis %.1f GB", self.cfg.vision_url,
                 self.cfg.vision_interval_s, "pausiert bei Fehldruck" if self.cfg.vision_action == "pause"
                 else "meldet nur", self.cfg.vision_dataset_gb)
        await self.check_health()
        while True:
            await asyncio.sleep(1)
            try:
                await self.tick()
            except Exception:  # noqa: BLE001
                log.exception("KI-Fehler")
