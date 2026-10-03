"""Bildersammlung der KI: DATA_DIR/vision/jobs/<start>_<datei>/ mit Bildern, frames.jsonl und labels.jsonl.

Jedes Bild hat eine Zeile in frames.jsonl (Zeit, Art, Wert, Funde, Schicht ...). Kennzeichnungen stehen in
labels.jsonl (die letzte Zeile je Bild gilt) - daraus entstehen spaeter die Trainingsdaten fuer Stufe 2/3.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import zipfile
from typing import Any, Callable, Dict, Iterator, List, Optional

log = logging.getLogger("vision")

# Kennzeichnungen fuer die Trainingsdaten (Schluessel -> Anzeige)
LABELS = {
    "ok": "In Ordnung",
    "spaghetti": "Spaghetti",
    "detached": "Teil gelöst",
    "tower": "Turm umgefallen",
    "plate_not_empty": "Platte nicht leer",
    "plate_empty": "Platte leer",
}
KINDS = ("start", "periodic", "suspect", "event", "end", "test")
_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


class Dataset:
    def __init__(self, root: str):
        self.root = root                       # .../vision/jobs

    # ------------------------------------------------------------ Pfade
    def _job_dir(self, job: str) -> str:
        if not _NAME.match(job or ""):
            raise KeyError(job)
        return os.path.join(self.root, job)

    def frame_path(self, job: str, frame: str) -> Optional[str]:
        """Pfad eines Bildes - nur Namen ohne Verzeichnisanteile, nur .jpg, nur wenn es existiert."""
        if not _NAME.match(frame or "") or not frame.endswith(".jpg"):
            return None
        try:
            p = os.path.join(self._job_dir(job), frame)
        except KeyError:
            return None
        return p if os.path.isfile(p) else None

    # ------------------------------------------------------------ Schreiben
    def add(self, job: str, name: str, img: bytes, meta: Dict[str, Any]) -> str:
        d = self._job_dir(job)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "wb") as f:
            f.write(img)
        with open(os.path.join(d, "frames.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"frame": name, **meta}) + "\n")
        return name

    def label(self, job: str, frame: str, label: Optional[str], extra: Optional[Dict[str, Any]] = None) -> None:
        """label None = Kennzeichnung entfernen."""
        if label is not None and label not in LABELS:
            raise ValueError("Unbekannte Kennzeichnung: " + str(label))
        if not self.frame_path(job, frame):
            raise KeyError(frame)
        with open(os.path.join(self._job_dir(job), "labels.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"frame": frame, "label": label, **(extra or {})}) + "\n")

    def delete_job(self, job: str) -> None:
        d = self._job_dir(job)
        if not os.path.isdir(d):
            raise KeyError(job)
        shutil.rmtree(d, ignore_errors=True)

    def delete_frame(self, job: str, frame: str) -> None:
        p = self.frame_path(job, frame)
        if not p:
            raise KeyError(frame)
        os.remove(p)
        # Zeilen bleiben; frames() zeigt nur vorhandene Bilder

    # ------------------------------------------------------------ Lesen
    def _labels(self, d: str) -> Dict[str, Optional[str]]:
        out: Dict[str, Optional[str]] = {}
        try:
            with open(os.path.join(d, "labels.jsonl"), encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                        lab = r.get("label")
                        if lab is None and "verdict" in r:          # Rueckmeldungen aus 2.17.0
                            lab = {"false_alarm": "ok", "confirmed": "spaghetti"}.get(r["verdict"])
                        out[r["frame"]] = lab
                    except (ValueError, KeyError):
                        continue
        except FileNotFoundError:
            pass
        return out

    def frames(self, job: str) -> List[Dict[str, Any]]:
        d = self._job_dir(job)
        if not os.path.isdir(d):
            raise KeyError(job)
        labels = self._labels(d)
        out = []
        try:
            with open(os.path.join(d, "frames.jsonl"), encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if os.path.isfile(os.path.join(d, r.get("frame", ""))):
                        r["label"] = labels.get(r["frame"])
                        out.append(r)
        except FileNotFoundError:
            pass
        return out

    def page(self, job: str, flt: str = "all", offset: int = 0, limit: int = 120) -> Dict[str, Any]:
        """Bilder eines Drucks gefiltert und seitenweise (ein langer Druck hat tausende Bilder)."""
        tests = {"all": lambda f: True, "event": lambda f: f.get("kind") == "event",
                 "suspect": lambda f: f.get("kind") == "suspect",
                 "startend": lambda f: f.get("kind") in ("start", "end"),
                 "labelled": lambda f: bool(f.get("label")), "open": lambda f: not f.get("label")}
        if flt not in tests:
            raise ValueError("Filter: " + ", ".join(tests))
        sel = [f for f in self.frames(job) if tests[flt](f)]
        offset, limit = max(0, offset), min(max(1, limit), 500)
        return {"job": job, "total": len(sel), "offset": offset, "frames": sel[offset:offset + limit]}

    def jobs(self) -> List[Dict[str, Any]]:
        """Alle Drucke, neueste zuerst, mit Anzahl Bilder/Alarme/Kennzeichnungen und Groesse."""
        if not os.path.isdir(self.root):
            return []
        out = []
        for name in sorted(os.listdir(self.root), reverse=True):
            d = os.path.join(self.root, name)
            if not os.path.isdir(d):
                continue
            files = os.listdir(d)
            jpgs = [f for f in files if f.endswith(".jpg")]
            labels = self._labels(d)
            out.append({"job": name, "frames": len(jpgs),
                        "events": sum(1 for f in jpgs if "_event_" in f),
                        "suspect": sum(1 for f in jpgs if "_suspect_" in f),
                        "labelled": sum(1 for f in jpgs if labels.get(f)),
                        "mb": round(sum(os.path.getsize(os.path.join(d, f)) for f in files) / 1024 ** 2, 2),
                        "cover": next((f for f in sorted(jpgs) if "_event_" in f), sorted(jpgs)[0] if jpgs else None)})
        return out

    def stats(self, limit_gb: float) -> Dict[str, Any]:
        jobs = self.jobs()
        return {"jobs": len(jobs), "frames": sum(j["frames"] for j in jobs),
                "labelled": sum(j["labelled"] for j in jobs), "events": sum(j["events"] for j in jobs),
                "mb": round(sum(j["mb"] for j in jobs), 1), "limit_gb": limit_gb,
                "labels": {k: v for k, v in LABELS.items()}}

    def prune(self, limit_gb: float, keep: Optional[str] = None) -> int:
        """Aelteste Drucke loeschen, bis die Sammlung unter limit_gb liegt (keep bleibt immer)."""
        if not os.path.isdir(self.root):
            return 0
        limit = limit_gb * 1024 ** 3
        jobs = []
        for name in sorted(os.listdir(self.root)):
            p = os.path.join(self.root, name)
            if os.path.isdir(p):
                jobs.append((name, sum(os.path.getsize(os.path.join(p, f)) for f in os.listdir(p))))
        total = sum(s for _, s in jobs)
        removed = 0
        for name, size in jobs:
            if total <= limit:
                break
            if name == keep:
                continue
            shutil.rmtree(os.path.join(self.root, name), ignore_errors=True)
            total -= size
            removed += 1
        if removed:
            log.info("Bildersammlung: %d alte Drucke gelöscht (Grenze %.1f GB)", removed, limit_gb)
        return removed

    # ------------------------------------------------------------ Export
    def iter_files(self, job: Optional[str] = None) -> Iterator[str]:
        """Alle Dateien (relativ zu root) - fuer den ZIP-Export."""
        names = [job] if job else (sorted(os.listdir(self.root)) if os.path.isdir(self.root) else [])
        for name in names:
            d = self._job_dir(name)
            if os.path.isdir(d):
                for f in sorted(os.listdir(d)):
                    yield os.path.join(name, f)

    def write_zip(self, out, job: Optional[str] = None, cancelled: Callable[[], bool] = lambda: False) -> int:
        """ZIP (Bilder unkomprimiert) in einen nicht-seekbaren Strom schreiben. Rueckgabe: Anzahl Dateien."""
        n = 0
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as z:
            z.writestr("README.txt", "kobra-spoolman KI-Bildersammlung\n"
                       "Pro Druck: Bilder, frames.jsonl (Zeit, Art, Wert p, Funde, Schicht), labels.jsonl (Kennzeichnung,\n"
                       "die letzte Zeile je Bild gilt). Kennzeichnungen: " + ", ".join(LABELS) + "\n")
            for rel in self.iter_files(job):
                if cancelled():
                    break
                z.write(os.path.join(self.root, rel), rel)
                n += 1
        return n
