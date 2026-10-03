"""KI-Fehldruck-Erkennung: Bilder an kobra-vision schicken, Funde ueber die Zeit bewerten, melden, sammeln.

Ablauf im Druck (nur Status "printing"): alle interval_s ein Bild von der Kamera (camera.still() - das
aktuelle Bild, wenn jemand zuschaut, sonst ein Einzelabruf; die Bildpumpe startet dafuer nicht) an den Dienst.
Der liefert Boxen mit Sicherheit. Boxen, deren Mitte in einem ignorierten Bereich liegt (Spuelrutsche,
Buerste, Spiegelung), zaehlen nicht. Die Summe p eines Bildes allein ist zu unruhig; bewertet wird wie bei
Obico (obico-server, backend/lib/prediction.py - hier eigenstaendig umgesetzt): gleitender Mittelwert (EWM)
gegen eine Grundlinie ueber viele Drucke, mit unterer und oberer Schwelle; die ersten safe_s eines Drucks
zaehlen nicht. Stufen: ok -> warn (verdaechtig) -> fail (wahrscheinlich Fehldruck; mit action=pause wird
pausiert, optional danach die Duese aus).

Gemeldet wird als Meldung ai-warn / ai-fail (rot = Alarm am Handy; ai-warn nur gelb, wenn notify=fail oder
Ruhezeit mit "nur Fehldruck"). Rueckmeldung "Fehlalarm" schaltet die KI fuer den Rest des Drucks still und
kennzeichnet das Bild. Einstellungen: vision_settings.py, Bildersammlung: vision_data.py.
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
from .vision_data import Dataset

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
INIT_SAFE_FRAMES = 30            # Obicos Standard; bei uns aus safe_s / interval_s berechnet
SHORT_MULTIPLE = 3.8
ESCALATING_FACTOR = 1.75         # warn -> fail
SUSPECT_P = THRESHOLD_LOW * 0.2  # ab hier wird das Bild gesammelt ...
SUSPECT_EVERY_S = 30             # ... aber hoechstens so oft (ein Fehldruck ueber Stunden fuellt sonst die Platte)
HISTORY = 720                    # Verlauf fuer die Kurve (~2 h bei 10 s)
EVENTS_KEPT = 100
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

    def update(self, p: float, learn: bool = True) -> None:
        """learn=False: Grundlinie nicht nachziehen (offener Alarm) - sonst gewoehnt sich die KI an einen
        Fehldruck, der lange unbemerkt weiterlaeuft (anders als Obico, im Demo-Test beobachtet)."""
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
        self.configured = bool(cfg.vision_url)          # Dienst eingetragen?
        self.dir = os.path.join(cfg.data_dir, "vision")
        self.data = Dataset(os.path.join(self.dir, "jobs"))
        self.settings = vs.load(self._path("settings.json"), vs.VisionSettings.defaults(cfg))
        self.pred = Prediction()
        self.level = "ok"
        self.detections: List[List[Any]] = []          # gezaehlte Funde des letzten Bildes
        self.ignored: List[List[Any]] = []             # Funde in ignorierten Bereichen
        self.size: Optional[List[int]] = None
        self.history: Deque[List[float]] = deque(maxlen=HISTORY)
        self.events: List[Dict[str, Any]] = []
        self.event: Optional[Dict[str, Any]] = None      # offenes Ereignis des laufenden Drucks
        self.muted: Optional[str] = None                  # None | "false_alarm" | "manual" (nur dieser Druck)
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
        """Bild in den Ordner des Drucks. Rueckgabe: "<druck>/<bild>" oder None."""
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
            log.warning("Bild nicht gespeichert: %s", e)
            return None

    def prune(self) -> int:
        return self.data.prune(self.settings.dataset_gb, keep=self.job)

    # ------------------------------------------------------------ Einstellungen
    def update_settings(self, changes: Dict[str, Any]) -> vs.VisionSettings:
        new = vs.apply(self.settings, changes)
        vs.save(self._path("settings.json"), new)
        old, self.settings = self.settings, new
        if new.dataset_gb < old.dataset_gb:
            self.prune()
        log.info("KI-Einstellungen geändert: %s", ", ".join(sorted(changes)))
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
        """Ab welcher Stufe ist die Meldung rot (= Alarm am Handy)?"""
        if self.quiet_now() and self.settings.quiet.get("mode") == "fail_only":
            return "fail"
        return self.settings.notify

    def mute(self, on: bool) -> None:
        """'Diesen Druck nicht ueberwachen' (gilt bis zum naechsten Druck)."""
        self.muted = "manual" if on else None
        if on:
            self.event = None

    def reset_baseline(self) -> None:
        """Grundlinie vergessen (z. B. nach Kamera-Umbau)."""
        self.pred.long, self.pred.lifetime = 0.0, 0
        self._save()
        log.info("KI: Grundlinie zurückgesetzt")

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

    def _split(self, dets: List[Any]) -> tuple:
        """Funde in gezaehlte und ignorierte (Mitte in einem ignorierten Bereich) teilen."""
        counted, ignored = [], []
        for d in dets:
            if not (isinstance(d, list) and len(d) == 3):
                continue
            box = d[2]
            (ignored if vs.in_zone(self.settings.zones, box[0], box[1]) is not None else counted).append(d)
        return counted, ignored

    async def test(self, img: Optional[bytes] = None) -> Dict[str, Any]:
        """'Jetzt pruefen': ein Bild (aktuelles Kamerabild oder hochgeladen) auswerten, ohne die Bewertung
        zu veraendern. Wird als Art "test" gesammelt, wenn gerade gedruckt wird."""
        if not self.configured:
            raise RuntimeError("KI ist nicht eingerichtet (VISION_URL fehlt)")
        own = img is None
        if own:
            img, _ = await self.camera.still()
        res = await self.analyze(img)
        counted, ignored = self._split(res.get("detections", []))
        p = round(sum(float(d[1]) for d in counted), 3)
        verdict = "auffällig" if p >= THRESHOLD_HIGH else "leicht auffällig" if p >= THRESHOLD_LOW else "unauffällig"
        return {"detections": counted, "ignored": ignored, "p": p, "verdict": verdict, "ms": res.get("ms"),
                "size": [res.get("width"), res.get("height")], "source": "camera" if own else "upload"}

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
        """Bild nur sammeln (Start/Ende), ohne Bewertung."""
        try:
            img, _ = await self.camera.still()
        except CameraError:
            return
        self._save_frame(img, kind, extra)

    async def tick(self) -> None:
        """Wird jede Sekunde aufgerufen."""
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
            self.error = f"Kein Kamerabild: {e}"
            return
        except Exception as e:  # noqa: BLE001
            self.error = f"KI-Dienst nicht erreichbar: {e}" if not isinstance(e, RuntimeError) else f"KI-Dienst: {e}"
            return
        self.error, self.last_ok = None, self.clock()
        self.detections, self.ignored = self._split(res.get("detections", []))
        self.size = [res.get("width"), res.get("height")]
        self.ms = res.get("ms")
        model = self.health.setdefault("model", {})
        model["loaded"] = True                       # hat gerade ein Bild ausgewertet
        if res.get("provider"):
            model["provider"] = res["provider"]
        sens = self.settings.sensitivity
        # offener Alarm (nicht als Fehlalarm bestaetigt): Grundlinie bleibt stehen
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
        log.warning("KI: %s (Wert %.2f, %d Funde) – %s", "Fehldruck wahrscheinlich" if self.level == "fail"
                    else "verdächtig", self.pred.p, len(self.detections), ev["file"])
        if self.level == "fail" and self.effective_action() == "pause" and not self.paused_by_ai:
            try:
                await self.moon.action("printer.print.pause", "PAUSE (KI)", source="KI")
                self.paused_by_ai = True
                ev["paused"] = True
                if self.settings.heater_off:
                    await self.moon.gcode("M104 S0", source="KI")
                    ev["heater_off"] = True
            except Exception as e:  # noqa: BLE001
                log.error("KI: Pause fehlgeschlagen: %s", e)

    @staticmethod
    def _frame_ref(ev: Dict[str, Any]) -> Optional[tuple]:
        """(druck, bild) eines Ereignisses; 2.17.0 speicherte noch "jobs/<druck>/<bild>"."""
        ref = (ev.get("frame") or "").removeprefix("jobs/")
        return tuple(ref.split("/", 1)) if "/" in ref else None

    def _find(self, event_id: str) -> Dict[str, Any]:
        ev = next((e for e in self.events if e.get("id") == event_id), None)
        if ev is None:
            raise KeyError(event_id)
        return ev

    def feedback(self, event_id: str, verdict: str) -> Dict[str, Any]:
        """verdict: false_alarm (Fehlalarm: Rest des Drucks still), confirmed (stimmt) oder None (zuruecknehmen)."""
        if verdict not in ("false_alarm", "confirmed", None):
            raise ValueError("verdict muss false_alarm oder confirmed sein")
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
                pass                                  # Bild schon geloescht
        self._save()
        log.info("KI: Rückmeldung %s für %s", verdict or "zurückgenommen", event_id)
        return ev

    def frame_path(self, event_id: str) -> Optional[str]:
        try:
            ev = self._find(event_id)
        except KeyError:
            return None
        ref = self._frame_ref(ev)
        return self.data.frame_path(*ref) if ref else None

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
            red = ev["level"] == "fail" or self.phone_from() == "warn"
            out.append({"level": "error" if red else "warn", "text": text, "key": f"ai-{ev['level']}"})
        st = self._print_state()
        if st == "printing" and self.error and self.last_try and \
                (self.last_ok is None or self.clock() - self.last_ok >= DOWN_AFTER_S):
            out.append({"level": "warn", "text": self.error, "key": "ai-down"})
        return out

    def status_line(self) -> Dict[str, Any]:
        base = {"key": "ai", "label": "KI"}
        if not self.configured:
            return {**base, "state": "off", "detail": "aus (VISION_URL nicht gesetzt)"}
        if not self.settings.enabled:
            return {**base, "state": "off", "detail": "ausgeschaltet (KI-Tab)"}
        if self.error:
            return {**base, "state": "warn", "detail": self.error}
        prov = ((self.health.get("model") or {}).get("provider") or "").replace("ExecutionProvider", "")
        where = {"CPU": "CPU", "CUDA": "Grafikkarte"}.get(prov, prov or "bereit")
        if self._print_state() == "printing":
            if self.muted:
                why = "Fehlalarm" if self.muted == "false_alarm" else "von Hand"
                return {**base, "state": "ok", "detail": f"für diesen Druck stumm ({why})"}
            s = self.pred.score(self.settings.sensitivity)
            word = {"ok": "unauffällig", "warn": "verdächtig", "fail": "Fehldruck?"}[self.level]
            if self.pred.frames < self.safe_frames():
                word = f"lernt den Druck ({self.pred.frames}/{self.safe_frames()})"
            return {**base, "state": {"ok": "ok", "warn": "warn", "fail": "bad"}[self.level],
                    "detail": f"{word} · Wert {s:.2f} · {where}"}
        return {**base, "state": "ok", "detail": f"bereit · {where}" + (" · Modell entladen" if not
                                                                           (self.health.get("model") or {}).get("loaded") else "")}

    def summary(self) -> Dict[str, Any]:
        """Kurzform fuer /api/app/state und die Weboberflaeche."""
        ev = self.event
        printing = self._print_state() == "printing"
        # muted bleibt ja/nein (App 1.5.0 liest es so), der Grund steht in muted_reason
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
        log.info("KI: %s, alle %.0f s im Druck, %s, Sammlung bis %.1f GB", self.cfg.vision_url,
                 self.settings.interval_s, "pausiert bei Fehldruck" if self.settings.action == "pause"
                 else "meldet nur", self.settings.dataset_gb)
        await self.check_health()
        while True:
            await asyncio.sleep(1)
            try:
                await self.tick()
            except Exception:  # noqa: BLE001
                log.exception("KI-Fehler")
