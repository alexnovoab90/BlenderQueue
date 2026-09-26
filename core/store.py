"""BlendQueue's persistent state: files, jobs and settings (atomic JSON)."""
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
        self._data = {"settings": dict(DEFAULT_SETTINGS), "files": [], "jobs": [],
                      "scripts": [], "caps": {}, "recent_dirs": []}
        self.load()

    # ---------------- persistence ----------------
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
                    if isinstance(data.get("scripts"), list):
                        self._data["scripts"] = data["scripts"]
                    if isinstance(data.get("caps"), dict):
                        self._data["caps"] = data["caps"]
                    if isinstance(data.get("recent_dirs"), list):
                        self._data["recent_dirs"] = data["recent_dirs"]
            except Exception:
                pass  # corrupt state: start fresh (the logs stay in data/logs)
            self._recover()
            self.save()

    def _recover(self) -> None:
        for job in self._data["jobs"]:
            st = job.get("status")
            if st == "running":
                # BlendQueue died mid-render (window closed, crash, reboot): back to
                # the queue, to continue after the last frame its log says was
                # saved. pid/pid_birth stay so the worker can kill an orphan first.
                job["status"] = "queued"
                job["interrupted"] = True
                job["paused_at"] = None
            elif (st == "error" and not job.get("interrupted")
                  and str(job.get("error") or "").startswith("Interrupted:")):
                job["interrupted"] = True      # from older versions: offer ▶ Resume
            elif st not in ("queued", "paused", "done", "error", "canceled"):
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

    # ---------------- queries ----------------
    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    def settings(self) -> dict:
        with self._lock:
            return dict(self._data["settings"])

    # ---------------- script library ----------------
    def scripts(self) -> list:
        with self._lock:
            return copy.deepcopy(self._data.get("scripts") or [])

    def get_script(self, sid: str):
        with self._lock:
            for s in self._data.get("scripts") or []:
                if s.get("id") == sid:
                    return copy.deepcopy(s)
        return None

    def add_script(self, name: str, code: str) -> dict:
        with self._lock:
            rec = {"id": new_id("s"), "name": name, "code": code,
                   "created_at": now(), "updated_at": now()}
            self._data.setdefault("scripts", []).append(rec)
            self.save()
            return copy.deepcopy(rec)

    def update_script(self, sid: str, **fields):
        with self._lock:
            for s in self._data.get("scripts") or []:
                if s.get("id") == sid:
                    s.update(fields)
                    s["updated_at"] = now()
                    self.save()
                    return copy.deepcopy(s)
        return None

    def delete_script(self, sid: str) -> bool:
        with self._lock:
            scripts = self._data.get("scripts") or []
            rest = [s for s in scripts if s.get("id") != sid]
            if len(rest) != len(scripts):
                self._data["scripts"] = rest
                self.save()
                return True
        return False

    def caps(self) -> dict:
        """Formats/enums the detected Blender supports (last successful inspection)."""
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

    def recent_dirs(self) -> list:
        """Folders the user worked in lately, newest first (to find dropped files)."""
        with self._lock:
            return list(self._data.get("recent_dirs") or [])

    def remember_dir(self, path: str, limit: int = 40) -> None:
        if not path:
            return
        path = os.path.abspath(path)
        key = os.path.normcase(path)
        with self._lock:
            dirs = [d for d in self._data.get("recent_dirs") or []
                    if os.path.normcase(d) != key]
            dirs.insert(0, path)
            if dirs != self._data.get("recent_dirs"):
                self._data["recent_dirs"] = dirs[:limit]
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

    # ---------------- mutations ----------------
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
        """Moves a queued job one position up (-1) or down (+1).

        Skips jobs that are no longer queued (done, errored...), which can sit
        in between: what matters is the relative order of the queued ones, which
        is what the worker consumes.
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
        """The next job to render: one that was already halfway goes first."""
        with self._lock:
            queued = [j for j in self._data["jobs"] if j.get("status") == "queued"]
            for j in queued:
                if j.get("resume_from") is not None or j.get("interrupted"):
                    return copy.deepcopy(j)
            return copy.deepcopy(queued[0]) if queued else None
