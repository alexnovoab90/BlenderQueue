"""Configuración, rutas y localización de Blender para BlendQueue."""
from __future__ import annotations

import glob
import os
import pathlib
import re
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

# Carpetas donde suele quedar Blender (instalador, Steam, portable en otra unidad).
INSTALL_DIRS = (
    r"{drive}:\Program Files\Blender Foundation",
    r"{drive}:\Program Files (x86)\Blender Foundation",
    r"{drive}:\Blender Foundation",
)
STEAM_PATHS = (
    r"{drive}:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe",
    r"{drive}:\SteamLibrary\steamapps\common\Blender\blender.exe",
    r"{drive}:\Steam\steamapps\common\Blender\blender.exe",
)
DRIVES = ("C", "D", "E", "F", "G")

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def ensure_dirs() -> None:
    for d in (DATA_DIR, UPLOADS_DIR, OUTPUTS_DIR, LOGS_DIR, PREVIEWS_DIR, INSPECT_DIR, TESTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _version_key(path: str) -> tuple:
    """Ordena 'Blender 5.2' por encima de 'Blender 4.5' (y de 'Blender 4.10')."""
    folder = os.path.basename(os.path.dirname(path))
    nums = tuple(int(n) for n in re.findall(r"\d+", folder))
    return nums or (0,)


def find_blender() -> str | None:
    """Busca blender.exe: variable de entorno, instalaciones, PATH y Steam."""
    env = os.environ.get("BLENDQUEUE_BLENDER", "").strip().strip('"')
    if env and pathlib.Path(env).is_file():
        return env

    installs = []
    for drive in DRIVES:
        for tpl in INSTALL_DIRS:
            base = tpl.format(drive=drive)
            if os.path.isdir(base):
                installs += glob.glob(os.path.join(base, "*", "blender.exe"))
    for p in sorted(installs, key=_version_key, reverse=True):
        if pathlib.Path(p).is_file():
            return p

    w = shutil.which("blender")
    if w:
        return w

    for drive in DRIVES:
        for tpl in STEAM_PATHS:
            p = tpl.format(drive=drive)
            if pathlib.Path(p).is_file():
                return p
    return None


_BI = {"configured": None, "path": None, "version": None, "checked": 0.0, "error": None}
_bi_lock = threading.Lock()


def _bi_result() -> dict:
    return {"ok": bool(_BI["version"]), "path": _BI["path"],
            "version": _BI["version"], "error": _BI["error"]}


def blender_info(path: str | None = None, force: bool = False) -> dict:
    """Devuelve {'ok', 'path', 'version', 'error'} con caché de ~60 s.

    ``path`` es la ruta configurada en Ajustes (None = autodetectar). Solo se
    vuelve a ejecutar 'blender --version' si cambió esa ruta, si venció la
    caché o si se pide ``force``: la UI consulta el estado cada segundo y
    lanzar un proceso por consulta era carísimo.
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
            _BI["error"] = "No se encontró blender.exe"
            return _bi_result()
        try:
            out = subprocess.run([p, "--version"], capture_output=True, text=True, timeout=60,
                                 creationflags=CREATE_NO_WINDOW)
            lines = (out.stdout or "").strip().splitlines()
            ver = lines[0].strip() if lines else ""
            _BI["version"] = ver or None
            _BI["error"] = None if ver else "Salida vacía de 'blender --version'"
        except Exception as exc:
            _BI["version"] = None
            _BI["error"] = str(exc)
        return _bi_result()


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")
