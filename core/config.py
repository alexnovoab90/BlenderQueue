"""Configuración, rutas y localización de Blender para BlendQueue."""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import threading
import time

APP_DIR = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
OUTPUTS_DIR = DATA_DIR / "outputs"
LOGS_DIR = DATA_DIR / "logs"
PREVIEWS_DIR = DATA_DIR / "previews"
INSPECT_DIR = DATA_DIR / "inspect"
TESTS_DIR = DATA_DIR / "tests"
STATIC_DIR = APP_DIR / "static"
BLENDER_SIDE_DIR = APP_DIR / "blender_side"
STATE_FILE = DATA_DIR / "state.json"

DEFAULT_PORT = 8777
DEFAULT_BLENDER = r"D:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe"

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def ensure_dirs() -> None:
    for d in (DATA_DIR, UPLOADS_DIR, OUTPUTS_DIR, LOGS_DIR, PREVIEWS_DIR, INSPECT_DIR, TESTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def find_blender() -> str | None:
    candidates = [
        os.environ.get("BLENDQUEUE_BLENDER", ""),
        DEFAULT_BLENDER,
        r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
        r"D:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
    ]
    for c in candidates:
        if c and pathlib.Path(c).is_file():
            return c
    w = shutil.which("blender")
    if w:
        return w
    for drive in ("C:", "D:", "E:", "F:"):
        for sub in (r"\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe",
                    r"\SteamLibrary\steamapps\common\Blender\blender.exe"):
            p = pathlib.Path(drive + sub)
            if p.is_file():
                return str(p)
    return None


_BI = {"path": None, "version": None, "checked": 0.0}
_bi_lock = threading.Lock()


def blender_info(path: str | None = None, force: bool = False) -> dict:
    """Devuelve {'ok', 'path', 'version', 'error'} con caché de ~60 s."""
    with _bi_lock:
        now = time.time()
        if path:
            _BI["path"] = path
            force = True
        if not force and _BI["checked"] and now - _BI["checked"] < 60:
            return {"ok": bool(_BI["version"]), "path": _BI["path"], "version": _BI["version"], "error": None}
        p = _BI["path"] or find_blender()
        _BI["path"] = p
        _BI["checked"] = now
        if not p:
            _BI["version"] = None
            return {"ok": False, "path": None, "version": None, "error": "No se encontró blender.exe"}
        try:
            out = subprocess.run([p, "--version"], capture_output=True, text=True, timeout=60,
                                 creationflags=CREATE_NO_WINDOW)
            lines = (out.stdout or "").strip().splitlines()
            ver = lines[0].strip() if lines else ""
            _BI["version"] = ver or None
            if not ver:
                return {"ok": False, "path": p, "version": None, "error": "Salida vacía de 'blender --version'"}
            return {"ok": True, "path": p, "version": ver, "error": None}
        except Exception as exc:
            _BI["version"] = None
            return {"ok": False, "path": p, "version": None, "error": str(exc)}


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")
