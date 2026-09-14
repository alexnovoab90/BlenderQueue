"""Estado persistente de BlendQueue: archivos, trabajos y ajustes (JSON atómico)."""
from __future__ import annotations

import copy
import json
import os
import threading
import time
import uuid

from . import config


def now() -> float:
    return time.time()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


DEFAULT_SETTINGS = {
    "blender_path": "",
    "notifications": True,
    "preview_video": True,
}


class Store:
    def __init__(self, path: str | None = None):
        self._path = str(path or config.STATE_FILE)
        self._lock = threading.RLock()
        self._data = {"settings": dict(DEFAULT_SETTINGS), "files": [], "jobs": [], "caps": {}}
        self.load()

    # ---------------- persistencia ----------------
    def load(self) -> None:
        with self._lock:
            try:
                if os.path.exists(self._path):
                    with open(self._path, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    if isinstance(data.get("settings"), dict):
                        self._data["settings"].update(data["settings"])
                    if isinstance(data.get("files"), list):
                        self._data["files"] = data["files"]
                    if isinstance(data.get("jobs"), list):
                        self._data["jobs"] = data["jobs"]
                    if isinstance(data.get("caps"), dict):
                        self._data["caps"] = data["caps"]
            except Exception:
                pass  # estado corrupto: se parte de cero (los logs quedan en data/logs)
            self._recover()
            self.save()

    def _recover(self) -> None:
        for job in self._data["jobs"]:
            st = job.get("status")
            if st == "running":
                job["status"] = "error"
                job["error"] = "Interrumpido: la aplicación se cerró durante el render."
                job["finished_at"] = now()
            elif st not in ("queued", "done", "error", "canceled"):
                job["status"] = "queued"
        for f in self._data["files"]:
            if f.get("status") in ("inspecting", "pending"):
                f["status"] = "pending"

    def save(self) -> None:
        with self._lock:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=1, ensure_ascii=False)
            os.replace(tmp, self._path)

    # ---------------- consultas ----------------
    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    def settings(self) -> dict:
        with self._lock:
            return dict(self._data["settings"])

    def caps(self) -> dict:
        """Formatos/enums que soporta el Blender detectado (última inspección OK)."""
        with self._lock:
            return copy.deepcopy(self._data.get("caps") or {})

    def set_caps(self, caps: dict | None) -> None:
        if not isinstance(caps, dict) or not caps.get("file_format"):
            return
        with self._lock:
            if self._data.get("caps") == caps:
                return
            self._data["caps"] = caps
            self.save()

    def files(self) -> list:
        with self._lock:
            return copy.deepcopy(self._data["files"])

    def get_file(self, fid: str):
        with self._lock:
            for f in self._data["files"]:
                if f.get("id") == fid:
                    return copy.deepcopy(f)
        return None

    def jobs(self) -> list:
        with self._lock:
            return copy.deepcopy(self._data["jobs"])

    def get_job(self, jid: str):
        with self._lock:
            for j in self._data["jobs"]:
                if j.get("id") == jid:
                    return copy.deepcopy(j)
        return None

    # ---------------- mutaciones ----------------
    def update_settings(self, patch: dict) -> dict:
        with self._lock:
            self._data["settings"].update(patch)
            self.save()
            return dict(self._data["settings"])

    def add_file(self, path: str, origin: str = "path") -> dict:
        path = os.path.abspath(path)
        with self._lock:
            for f in self._data["files"]:
                if os.path.normcase(os.path.abspath(f.get("path") or "")) == os.path.normcase(path):
                    return copy.deepcopy(f)
            rec = {
                "id": new_id("f"),
                "path": path,
                "name": os.path.basename(path),
                "size": os.path.getsize(path) if os.path.exists(path) else None,
                "mtime": os.path.getmtime(path) if os.path.exists(path) else None,
                "origin": origin,
                "status": "pending",
                "report": None,
                "inspect_error": None,
                "inspected_at": None,
                "added_at": now(),
            }
            self._data["files"].append(rec)
            self.save()
            return copy.deepcopy(rec)

    def update_file(self, fid: str, **fields) -> None:
        with self._lock:
            for f in self._data["files"]:
                if f.get("id") == fid:
                    f.update(fields)
                    self.save()
                    return

    def remove_file(self, fid: str) -> bool:
        with self._lock:
            before = len(self._data["files"])
            self._data["files"] = [f for f in self._data["files"] if f.get("id") != fid]
            if len(self._data["files"]) != before:
                self.save()
                return True
        return False

    def add_job(self, job: dict) -> dict:
        with self._lock:
            job = dict(job)
            job.setdefault("id", new_id("j"))
            job.setdefault("created_at", now())
            job.setdefault("status", "queued")
            job.setdefault("progress", {})
            job.setdefault("outputs", [])
            job.setdefault("preview", {})
            job.setdefault("error", None)
            self._data["jobs"].append(job)
            self.save()
            return copy.deepcopy(job)

    def update_job(self, jid: str, **fields) -> None:
        with self._lock:
            for j in self._data["jobs"]:
                if j.get("id") == jid:
                    j.update(fields)
                    self.save()
                    return

    def delete_job(self, jid: str) -> bool:
        with self._lock:
            before = len(self._data["jobs"])
            self._data["jobs"] = [j for j in self._data["jobs"] if j.get("id") != jid]
            if len(self._data["jobs"]) != before:
                self.save()
                return True
        return False

    def move_job(self, jid: str, direction: int) -> bool:
        """Mueve un trabajo encolado una posición arriba (-1) o abajo (+1).

        Salta los trabajos que ya no están en cola (listos, con error…), que
        pueden quedar intercalados: lo que importa es el orden relativo entre
        los encolados, que es el que consume el worker.
        """
        with self._lock:
            jobs = self._data["jobs"]
            idx = next((i for i, j in enumerate(jobs) if j.get("id") == jid), None)
            if idx is None or jobs[idx].get("status") != "queued":
                return False
            step = 1 if direction > 0 else -1
            k = idx + step
            while 0 <= k < len(jobs) and jobs[k].get("status") != "queued":
                k += step
            if not (0 <= k < len(jobs)):
                return False
            jobs[idx], jobs[k] = jobs[k], jobs[idx]
            self.save()
            return True

    def next_queued_job(self):
        with self._lock:
            for j in self._data["jobs"]:
                if j.get("status") == "queued":
                    return copy.deepcopy(j)
        return None
