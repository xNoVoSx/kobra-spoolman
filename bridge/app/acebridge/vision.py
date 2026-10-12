"""AI print failure detection: send images to kobra-vision, judge detections over time, report, collect.

Flow while printing (state "printing" only): every interval_s an image from the camera (camera.still() - the current
image when someone watches, else a single request; the image pump does not start for it) to the service. It returns
boxes with confidence. Boxes whose centre lies in an ignored area (purge chute, brush, reflection) do not count. The sum
p of one image alone is too noisy; judging works like Obico (obico-server, backend/lib/prediction.py - implemented
independently here): moving average (EWM) against a baseline over many prints, with a lower and an upper threshold;
the first safe_s of a print do not count. Levels: ok -> warn (suspicious) -> fail (probably a failed print; with
action=pause the print is paused, optionally the nozzle switched off afterwards).

Reported as message ai-warn / ai-fail (red = alarm on the phone; ai-warn only yellow with notify=fail or quiet hours
with "failure only"). Feedback "false alarm" mutes the AI for the rest of the print and labels the image.
Settings: vision_settings.py, image collection: vision_data.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Callable, Deque, Dict, List, Optional

import aiohttp

from . import vision_settings as vs
from .camera import CameraError
from .i18n import tr
from .vision_data import Dataset
from .storage import save_json

if TYPE_CHECKING:
    from .camera import Camera
    from .config import Config
    from .moonraker import Moonraker

log = logging.getLogger("vision")

# values like Obico (obico-server, backend/config/settings.py), tuned to ~1 image every 10 s
EWM_SPAN = 12
ROLLING_WIN_SHORT = 310
ROLLING_WIN_LONG = 7200
THRESHOLD_LOW = 0.38
THRESHOLD_HIGH = 0.78
INIT_SAFE_FRAMES = 30            # Obico's default; here computed from safe_s / interval_s
SHORT_MULTIPLE = 3.8
ESCALATING_FACTOR = 1.75         # warn -> fail
SUSPECT_P = THRESHOLD_LOW * 0.2  # from here the image is collected ...
SUSPECT_EVERY_S = 30             # ... but at most this often (a failed print over hours would fill the disk)
HISTORY = 720                    # history for the curve (~2 h at 10 s)
EVENTS_KEPT = 100
HEALTH_EVERY_S = 300
DOWN_AFTER_S = 60                # no answer for this long while printing -> message


@dataclass
class Prediction:
    """Judging over time. long/lifetime stay across prints (baseline of this printer)."""
    p: float = 0.0
    ewm: float = 0.0
    short: float = 0.0
    long: float = 0.0
    frames: int = 0
    lifetime: int = 0

    def new_print(self) -> None:
        self.p, self.ewm, self.short, self.frames = 0.0, 0.0, 0.0, 0

    def update(self, p: float, learn: bool = True) -> None:
        """learn=False: do not move the baseline (open alarm) - otherwise the AI gets used to a failed print that keeps
        running unnoticed for a long time (unlike Obico, seen in the demo test)."""
        alpha = 2 / (EWM_SPAN + 1)
        self.p = p
        self.frames += 1
        self.ewm = p * alpha + self.ewm * (1 - alpha)
        self.short += (p - self.short) / float(min(ROLLING_WIN_SHORT, self.frames + 1))
        if learn:
            self.lifetime += 1
            self.long += (p - self.long) / float(min(ROLLING_WIN_LONG, self.lifetime + 1))

    def _failing(self, sensitivity: float, factor: float, safe_frames: int) -> bool:
        if self.frames < safe_frames:
            return False
        adj = (self.ewm - self.long) * sensitivity / factor
        if adj < THRESHOLD_LOW:
            return False
        if adj > THRESHOLD_HIGH:
            return True
        return adj > (self.short - self.long) * SHORT_MULTIPLE

    def level(self, sensitivity: float = 1.0, safe_frames: int = INIT_SAFE_FRAMES) -> str:
        if self._failing(sensitivity, ESCALATING_FACTOR, safe_frames):
            return "fail"
        return "warn" if self._failing(sensitivity, 1.0, safe_frames) else "ok"

    def score(self, sensitivity: float = 1.0) -> float:
        """0..1 for display: up to 1/3 unremarkable, up to 2/3 warning, above failed print."""
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
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:60].strip("_") or "print"


class Vision:
    def __init__(self, cfg: "Config", moon: "Moonraker", camera: "Camera", session: aiohttp.ClientSession,
                 clock: Callable[[], float] = time.time):
        self.cfg = cfg
        self.moon = moon
        self.camera = camera
        self.session = session
        self.clock = clock
        self.configured = bool(cfg.vision_url)          # service configured?
        self.dir = os.path.join(cfg.data_dir, "vision")
        self.data = Dataset(os.path.join(self.dir, "jobs"))
        self.settings = vs.load(self._path("settings.json"), vs.VisionSettings.defaults(cfg))
        self.pred = Prediction()
        self.level = "ok"
        self.detections: List[List[Any]] = []          # counted detections of the last image
        self.ignored: List[List[Any]] = []             # detections in ignored areas
        self.size: Optional[List[int]] = None
        self.history: Deque[List[float]] = deque(maxlen=HISTORY)
        self.events: List[Dict[str, Any]] = []
        self.event: Optional[Dict[str, Any]] = None      # open event of the running print
        self.muted: Optional[str] = None                  # None | "false_alarm" | "manual" (this print only)
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
        self._last_suspect = 0.0
        self._last_health = 0.0
        self._load()

    @property
    def enabled(self) -> bool:
        return self.configured and self.settings.enabled

    # ------------------------------------------------------------ storing
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
            log.warning("vision/state.json unreadable, starting over: %s", e)

    def _save(self) -> None:
        os.makedirs(self.dir, exist_ok=True)
        save_json(self._path("state.json"),
                  {"long": self.pred.long, "lifetime": self.pred.lifetime, "events": self.events[-EVENTS_KEPT:]})

    def _save_frame(self, img: bytes, kind: str, extra: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Image into the print's folder. Returns: "<print>/<image>" or None."""
        if not self.job or self.settings.dataset_gb <= 0:
            return None
        try:
            now = self.clock()
            name = f"{time.strftime('%H%M%S', time.localtime(now))}_{kind}_{self.pred.p:.2f}.jpg"
            ps = self.moon.status.get("print_stats") or {}
            meta = {"t": round(now, 1), "kind": kind, "p": round(self.pred.p, 4), "ewm": round(self.pred.ewm, 4),
                    "level": self.level, "detections": self.detections, "ignored": self.ignored, "size": self.size,
                    "file": ps.get("filename"), "layer": (ps.get("info") or {}).get("current_layer"),
                    "progress": (self.moon.status.get("virtual_sdcard") or {}).get("progress"), **(extra or {})}
            self.data.add(self.job, name, img, meta)
            return f"{self.job}/{name}"
        except OSError as e:
            log.warning("Image not saved: %s", e)
            return None

    def prune(self) -> int:
        return self.data.prune(self.settings.dataset_gb, keep=self.job)

    # ------------------------------------------------------------ settings
    def update_settings(self, changes: Dict[str, Any]) -> vs.VisionSettings:
        new = vs.apply(self.settings, changes)
        vs.save(self._path("settings.json"), new)
        old, self.settings = self.settings, new
        if new.dataset_gb < old.dataset_gb:
            self.prune()
        log.info("AI settings changed: %s", ", ".join(sorted(changes)))
        return new

    def safe_frames(self) -> int:
        return int(round(self.settings.safe_s / max(1.0, self.settings.interval_s)))

    def quiet_now(self) -> bool:
        t = time.localtime(self.clock())
        return vs.in_quiet(self.settings, t.tm_hour * 60 + t.tm_min)

    def effective_action(self) -> str:
        if self.quiet_now() and self.settings.quiet.get("mode") == "pause":
            return "pause"
        return self.settings.action

    def phone_from(self) -> str:
        """From which level is the message red (= alarm on the phone)?"""
        if self.quiet_now() and self.settings.quiet.get("mode") == "fail_only":
            return "fail"
        return self.settings.notify

    def mute(self, on: bool) -> None:
        """'Do not watch this print' (until the next print)."""
        self.muted = "manual" if on else None
        if on:
            self.event = None

    def reset_baseline(self) -> None:
        """Forget the baseline (e.g. after moving the camera)."""
        self.pred.long, self.pred.lifetime = 0.0, 0
        self._save()
        log.info("AI: baseline reset")

    # ------------------------------------------------------------ service
    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.cfg.vision_token}"} if self.cfg.vision_token else {}

    async def check_health(self) -> None:
        self._last_health = self.clock()
        try:
            async with self.session.get(f"{self.cfg.vision_url}/v1/health", timeout=aiohttp.ClientTimeout(total=5)) as r:
                self.health = await r.json()
            self.error = None if self.health.get("ok") else tr("Model missing in the service")
        except Exception as e:  # noqa: BLE001
            self.health = {}
            self.error = tr("AI service not reachable: {error}", error=e.__class__.__name__)

    async def analyze(self, img: bytes) -> Dict[str, Any]:
        async with self.session.post(f"{self.cfg.vision_url}/v1/detect", data=img,
                                     headers={"Content-Type": "image/jpeg", **self._headers()},
                                     timeout=aiohttp.ClientTimeout(total=30)) as r:
            body = await r.json(content_type=None)
            if r.status != 200:
                raise RuntimeError(body.get("error") or f"HTTP {r.status}")
            return body

    def _split(self, dets: List[Any]) -> tuple:
        """Split detections into counted and ignored ones (centre in an ignored area)."""
        counted, ignored = [], []
        for d in dets:
            if not (isinstance(d, list) and len(d) == 3):
                continue
            box = d[2]
            (ignored if vs.in_zone(self.settings.zones, box[0], box[1]) is not None else counted).append(d)
        return counted, ignored

    async def test(self, img: Optional[bytes] = None) -> Dict[str, Any]:
        """'Check now': evaluate one image (current camera image or uploaded) without changing the judging. Collected
        as kind "test" while printing."""
        if not self.configured:
            raise RuntimeError(tr("AI is not set up (VISION_URL missing)"))
        own = img is None
        if own:
            img, _ = await self.camera.still()
        res = await self.analyze(img)
        counted, ignored = self._split(res.get("detections", []))
        p = round(sum(float(d[1]) for d in counted), 3)
        verdict = (tr("conspicuous") if p >= THRESHOLD_HIGH else tr("slightly conspicuous") if p >= THRESHOLD_LOW
                   else tr("unremarkable"))
        return {"detections": counted, "ignored": ignored, "p": p, "verdict": verdict, "ms": res.get("ms"),
                "size": [res.get("width"), res.get("height")], "source": "camera" if own else "upload"}

    # ------------------------------------------------------------ flow
    def _print_state(self) -> str:
        return (self.moon.status.get("print_stats") or {}).get("state") or ""

    async def on_state(self, old: str, new: str) -> None:
        """Print start: new judging, start image. Print end: end image, close the event."""
        if new == "printing" and old not in ("printing", "paused"):
            fname = (self.moon.status.get("print_stats") or {}).get("filename") or "print"
            self.job = time.strftime("%Y%m%d-%H%M%S", time.localtime(self.clock())) + "_" + \
                _safe(os.path.splitext(os.path.basename(fname))[0])
            self.pred.new_print()
            self.level, self.detections, self.ignored, self.event = "ok", [], [], None
            self.muted, self.paused_by_ai = None, False
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
        """Only collect the image (start/end), without judging."""
        try:
            img, _ = await self.camera.still()
        except CameraError:
            return
        self._save_frame(img, kind, extra)

    async def tick(self) -> None:
        """Called every second."""
        if not self.configured:
            return
        st = self._print_state()
        if st != self._state:
            old, self._state = self._state, st
            if self.settings.enabled:
                await self.on_state(old, st)
        now = self.clock()
        if now - self._last_health >= HEALTH_EVERY_S:
            await self.check_health()
        if self.enabled and st == "printing" and now - self._last_check >= self.settings.interval_s:
            self._last_check = now
            await self.check()

    async def check(self) -> None:
        self.last_try = self.clock()
        try:
            img, _ = await self.camera.still()
            res = await self.analyze(img)
        except CameraError as e:
            self.error = tr("No camera image: {error}", error=str(e))
            return
        except Exception as e:  # noqa: BLE001
            self.error = (tr("AI service not reachable: {error}", error=str(e)) if not isinstance(e, RuntimeError)
                          else tr("AI service: {error}", error=str(e)))
            return
        self.error, self.last_ok = None, self.clock()
        self.detections, self.ignored = self._split(res.get("detections", []))
        self.size = [res.get("width"), res.get("height")]
        self.ms = res.get("ms")
        model = self.health.setdefault("model", {})
        model["loaded"] = True                       # has just evaluated an image
        if res.get("provider"):
            model["provider"] = res["provider"]
        sens = self.settings.sensitivity
        # open alarm (not confirmed as a false alarm): the baseline stays
        self.pred.update(sum(float(d[1]) for d in self.detections), learn=self.event is None)
        self.history.append([round(self.last_ok), round(self.pred.p, 3), self.pred.score(sens)])
        old, self.level = self.level, self.pred.level(sens, self.safe_frames())

        now = self.clock()
        if self.level != "ok" and not self.muted and (self.event is None or self._rank(self.level) > self._rank(old)):
            await self._raise(img)
        elif self.pred.p > SUSPECT_P and now - self._last_suspect >= SUSPECT_EVERY_S:
            self._last_suspect = now
            self._save_frame(img, "suspect")
        elif now - self._last_save >= self.settings.save_every_s:
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
              "p": round(self.pred.p, 3), "score": self.pred.score(self.settings.sensitivity), "frame": frame,
              "detections": self.detections, "size": self.size, "verdict": None,
              "file": (self.moon.status.get("print_stats") or {}).get("filename")}
        self.event = ev
        self.events.append(ev)
        self.events = self.events[-EVENTS_KEPT:]
        self._save()
        log.warning("AI: %s (score %.2f, %d detections) – %s", "probably a failed print" if self.level == "fail"
                    else "suspicious", self.pred.p, len(self.detections), ev["file"])
        if self.level == "fail" and self.effective_action() == "pause" and not self.paused_by_ai:
            try:
                await self.moon.action("printer.print.pause", tr("PAUSE (AI)"), source=tr("AI"))
                self.paused_by_ai = True
                ev["paused"] = True
                if self.settings.heater_off:
                    await self.moon.gcode("M104 S0", source=tr("AI"))
                    ev["heater_off"] = True
            except Exception as e:  # noqa: BLE001
                log.error("AI: pause failed: %s", e)

    @staticmethod
    def _frame_ref(ev: Dict[str, Any]) -> Optional[tuple]:
        """(print, image) of an event; 2.17.0 still stored "jobs/<print>/<image>"."""
        ref = (ev.get("frame") or "").removeprefix("jobs/")
        return tuple(ref.split("/", 1)) if "/" in ref else None

    def _find(self, event_id: str) -> Dict[str, Any]:
        ev = next((e for e in self.events if e.get("id") == event_id), None)
        if ev is None:
            raise KeyError(event_id)
        return ev

    def feedback(self, event_id: str, verdict: str) -> Dict[str, Any]:
        """verdict: false_alarm (false alarm: rest of the print muted), confirmed (correct) or None (take back)."""
        if verdict not in ("false_alarm", "confirmed", None):
            raise ValueError(tr("verdict must be false_alarm or confirmed"))
        ev = self._find(event_id)
        ev["verdict"] = verdict
        ev["verdict_at"] = round(self.clock(), 1)
        if verdict == "false_alarm" and self.event and self.event.get("id") == event_id:
            self.muted = "false_alarm"
            self.event = None
        ref = self._frame_ref(ev)
        if ref:
            job, frame = ref
            label = {"false_alarm": "ok", "confirmed": "spaghetti"}.get(verdict) if verdict else None
            try:
                self.data.label(job, frame, label, {"verdict": verdict, "detections": ev.get("detections")})
            except KeyError:
                pass                                  # image already deleted
        self._save()
        log.info("AI: feedback %s for %s", verdict or "taken back", event_id)
        return ev

    def frame_path(self, event_id: str) -> Optional[str]:
        try:
            ev = self._find(event_id)
        except KeyError:
            return None
        ref = self._frame_ref(ev)
        return self.data.frame_path(*ref) if ref else None

    # ------------------------------------------------------------ display
    def messages(self) -> List[Dict[str, str]]:
        if not self.enabled:
            return []
        out = []
        ev = self.event
        if ev and not self.muted:
            if ev["level"] == "fail":
                text = (tr("AI: probably a failed print (spaghetti) – print paused") if ev.get("paused")
                        else tr("AI: probably a failed print (spaghetti) – check the camera"))
            else:
                text = tr("AI: the print looks suspicious – check the camera")
            red = ev["level"] == "fail" or self.phone_from() == "warn"
            out.append({"level": "error" if red else "warn", "text": text, "key": f"ai-{ev['level']}"})
        st = self._print_state()
        if st == "printing" and self.error and self.last_try and \
                (self.last_ok is None or self.clock() - self.last_ok >= DOWN_AFTER_S):
            out.append({"level": "warn", "text": self.error, "key": "ai-down"})
        return out

    def status_line(self) -> Dict[str, Any]:
        base = {"key": "ai", "label": tr("AI")}
        if not self.configured:
            return {**base, "state": "off", "detail": tr("off (VISION_URL not set)")}
        if not self.settings.enabled:
            return {**base, "state": "off", "detail": tr("switched off (AI tab)")}
        if self.error:
            return {**base, "state": "warn", "detail": self.error}
        prov = ((self.health.get("model") or {}).get("provider") or "").replace("ExecutionProvider", "")
        where = {"CPU": "CPU", "CUDA": tr("graphics card")}.get(prov, prov or tr("ready"))
        if self._print_state() == "printing":
            if self.muted:
                return {**base, "state": "ok", "detail": tr("muted for this print (false alarm)")
                        if self.muted == "false_alarm" else tr("muted for this print (by hand)")}
            s = self.pred.score(self.settings.sensitivity)
            word = {"ok": tr("unremarkable"), "warn": tr("suspicious"), "fail": tr("failed print?")}[self.level]
            if self.pred.frames < self.safe_frames():
                word = tr("learning the print ({n}/{total})", n=self.pred.frames, total=self.safe_frames())
            return {**base, "state": {"ok": "ok", "warn": "warn", "fail": "bad"}[self.level],
                    "detail": tr("{word} · score {s:.2f} · {where}", word=word, s=float(s), where=where)}
        if (self.health.get("model") or {}).get("loaded"):
            return {**base, "state": "ok", "detail": tr("ready · {where}", where=where)}
        return {**base, "state": "ok", "detail": tr("ready · {where} · model unloaded", where=where)}

    def summary(self) -> Dict[str, Any]:
        """Short form for /api/app/state and the web UI."""
        ev = self.event
        printing = self._print_state() == "printing"
        # muted stays yes/no (app 1.5.0 reads it like that), the reason is in muted_reason
        return {"enabled": self.enabled, "configured": self.configured, "level": self.level,
                "muted": bool(self.muted), "muted_reason": self.muted,
                "score": self.pred.score(self.settings.sensitivity) if self.enabled else None,
                "detections": self.detections if self.enabled and printing else [],
                "ignored": self.ignored if self.enabled and printing else [],
                "zones": self.settings.zones, "size": self.size,
                "event": {k: ev[k] for k in ("id", "at", "level", "p", "score")} if ev and not self.muted else None}

    def state(self) -> Dict[str, Any]:
        return {**self.summary(), "settings": self.settings.to_dict(), "quiet_now": self.quiet_now(),
                "action_now": self.effective_action(), "safe_frames": self.safe_frames(),
                "thresholds": {"low": THRESHOLD_LOW, "high": THRESHOLD_HIGH, "escalate": ESCALATING_FACTOR},
                "error": self.error, "ms": self.ms, "health": self.health, "prediction": asdict(self.pred),
                "history": list(self.history), "events": self.events[::-1], "dataset": self.data.stats(
                    self.settings.dataset_gb), "job": self.job, "printing": self._print_state() == "printing"}

    async def run(self) -> None:
        if not self.configured:
            return
        log.info("AI: %s, every %.0f s while printing, %s, collection up to %.1f GB", self.cfg.vision_url,
                 self.settings.interval_s, "pauses on a failed print" if self.settings.action == "pause"
                 else "reports only", self.settings.dataset_gb)
        await self.check_health()
        while True:
            await asyncio.sleep(1)
            try:
                await self.tick()
            except Exception:  # noqa: BLE001
                log.exception("AI error")
