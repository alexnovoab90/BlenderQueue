"""Configuration, paths and Blender discovery for BlendQueue."""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import threading
import time

from . import system

APP_DIR = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
OUTPUTS_DIR = DATA_DIR / "outputs"
LOGS_DIR = DATA_DIR / "logs"
PREVIEWS_DIR = DATA_DIR / "previews"
INSPECT_DIR = DATA_DIR / "inspect"
SCRIPTS_DIR = DATA_DIR / "scripts"   # copy of the script each job runs
TESTS_DIR = DATA_DIR / "tests"
STATIC_DIR = APP_DIR / "static"
BLENDER_SIDE_DIR = APP_DIR / "blender_side"
STATE_FILE = DATA_DIR / "state.json"

DEFAULT_PORT = 8777


def ensure_dirs() -> None:
    for d in (DATA_DIR, UPLOADS_DIR, OUTPUTS_DIR, LOGS_DIR, PREVIEWS_DIR, INSPECT_DIR,
              SCRIPTS_DIR, TESTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def find_blender() -> str | None:
    """First runnable Blender among the candidates for this platform."""
    for p in system.blender_candidates():
        if system.is_runnable(p):
            return p
    return None


_BI = {"configured": None, "path": None, "version": None, "checked": 0.0, "error": None}
_bi_lock = threading.Lock()


def _bi_result() -> dict:
    return {"ok": bool(_BI["version"]), "path": _BI["path"],
            "version": _BI["version"], "error": _BI["error"]}


def blender_info(path: str | None = None, force: bool = False) -> dict:
    """Returns {'ok', 'path', 'version', 'error'}, cached for ~60 s.

    ``path`` is the path set in Settings (None = autodetect). 'blender --version'
    only runs again if that path changed, if the cache expired or if ``force``
    is given: the UI polls the state every second and spawning a process per
    poll was very expensive.
    """
    with _bi_lock:
        configured = (path or "").strip() or None
        if configured != _BI["configured"]:
            _BI["configured"] = configured
            force = True
        if not force and _BI["checked"] and time.time() - _BI["checked"] < 60:
            return _bi_result()

        p = configured or find_blender()
        _BI["path"] = p
        _BI["checked"] = time.time()
        if not p:
            _BI["version"] = None
            _BI["error"] = "Blender not found"
            return _bi_result()
        try:
            out = subprocess.run([p, "--version"], capture_output=True, text=True, timeout=60,
                                 **system.popen_kwargs())
            lines = (out.stdout or "").strip().splitlines()
            ver = lines[0].strip() if lines else ""
            _BI["version"] = ver or None
            _BI["error"] = None if ver else "Empty output from 'blender --version'"
        except Exception as exc:
            _BI["version"] = None
            _BI["error"] = str(exc)
        return _bi_result()


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")
