"""BlendQueue: servidor local (FastAPI) + punto de entrada.

    python server.py [--port 8777] [--no-browser]
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import threading
import time
import webbrowser
from contextlib import asynccontextmanager

from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, UploadFile, File as FastAPIFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import config, formats, notifier
from core.inspector import InspectorLane
from core.store import Store
from core.worker import RenderWorker

config.ensure_dirs()
config.STATIC_DIR.mkdir(parents=True, exist_ok=True)

store: Store | None = None
inspector: InspectorLane | None = None
worker: RenderWorker | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global store, inspector, worker
    config.ensure_dirs()
    store = Store()
    inspector = InspectorLane(store)
    worker = RenderWorker(store)
    inspector.start()
    worker.start()
    for f in store.files():
        if f.get("status") == "pending":
            inspector.request(f["id"])
    yield


app = FastAPI(title="BlendQueue", lifespan=lifespan)

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
MAX_SCRIPT = 200_000   # tope del código de un script (caracteres)


@app.middleware("http")
async def only_local(request: Request, call_next):
    """BlendQueue abre el disco local (listar carpetas, abrir el Explorador,
    lanzar Blender). El servidor solo escucha en 127.0.0.1, pero eso no impide
    que otra página del navegador le mande peticiones: se exige que el Host y
    el Origin sean locales antes de aceptar algo que cambie estado."""
    host = (request.headers.get("host") or "").rsplit(":", 1)[0]
    if host and host not in LOCAL_HOSTS:
        return JSONResponse({"detail": "Local connections only"}, status_code=403)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin and (urlparse(origin).hostname or "") not in LOCAL_HOSTS:
            return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
    return await call_next(request)


# ---------------------------------------------------------------- estáticos
@app.get("/")
def index():
    return FileResponse(str(config.STATIC_DIR / "index.html"),
                        headers={"Cache-Control": "no-store, must-revalidate"})


app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")


# ---------------------------------------------------------------- estado
@app.get("/api/state")
def api_state():
    snap = store.snapshot()
    settings = snap["settings"]
    binfo = config.blender_info((settings.get("blender_path") or "").strip() or None)
    summary: dict = {}
    for j in snap["jobs"]:
        s = summary.setdefault(j.get("file_id"), {"queued": 0, "running": 0, "done": 0, "error": 0, "canceled": 0})
        st = j.get("status", "queued")
        if st in s:
            s[st] += 1
    for f in snap["files"]:
        f["jobs_summary"] = summary.get(
            f["id"], {"queued": 0, "running": 0, "done": 0, "error": 0, "canceled": 0})
    caps = snap.get("caps") or {}
    return {
        "blender": binfo,
        "settings": settings,
        "worker": worker.status(),
        "inspector": inspector.status(),
        "files": snap["files"],
        "jobs": snap["jobs"],
        "scripts": snap.get("scripts") or [],
        "log_tail": worker.tail(),
        "ffmpeg": bool(config.ffmpeg_path()),
        # La UI descarga el catálogo de formatos aparte y solo lo vuelve a pedir
        # cuando esta clave cambia (otra versión de Blender, otra instalación).
        "formats_key": str(caps.get("blender_version") or "") + ":" + str(len(caps.get("file_format") or [])),
        "now": time.time(),
    }


@app.get("/api/formats")
def api_formats():
    """Formatos de salida que ofrece la UI, según lo que soporta este Blender."""
    return formats.catalog(store.caps())


# ---------------------------------------------------------------- biblioteca de scripts
class ScriptBody(BaseModel):
    name: str | None = None
    code: str | None = None


def _script_fields(body: ScriptBody, partial: bool) -> dict:
    fields = {}
    if body.name is not None or not partial:
        fields["name"] = (body.name or "").strip()[:120] or "Untitled"
    if body.code is not None or not partial:
        code = body.code or ""
        if len(code) > MAX_SCRIPT:
            raise HTTPException(400, f"Script exceeds {MAX_SCRIPT} characters")
        fields["code"] = code
    return fields


@app.get("/api/scripts")
def api_scripts():
    return {"scripts": store.scripts()}


@app.post("/api/scripts")
def api_script_add(body: ScriptBody):
    f = _script_fields(body, partial=False)
    return {"script": store.add_script(f["name"], f["code"])}


@app.patch("/api/scripts/{sid}")
def api_script_update(sid: str, body: ScriptBody):
    if not store.get_script(sid):
        raise HTTPException(404, "Script not found")
    rec = store.update_script(sid, **_script_fields(body, partial=True))
    return {"script": rec}


@app.delete("/api/scripts/{sid}")
def api_script_delete(sid: str):
    """Borra el script de la biblioteca; los trabajos que ya lo llevan conservan su copia."""
    if not store.delete_script(sid):
        raise HTTPException(404, "Script not found")
    return {"ok": True}


# ---------------------------------------------------------------- archivos
class AddFilesBody(BaseModel):
    paths: list[str]


def _add_and_inspect(path: str, origin: str = "path") -> dict:
    rec = store.add_file(path, origin=origin)
    if rec.get("status") == "pending":
        inspector.request(rec["id"])
    return rec


@app.post("/api/files/add")
def api_files_add(body: AddFilesBody):
    added = []
    for raw in body.paths:
        p = (raw or "").strip().strip('"')
        if not p:
            continue
        if not os.path.exists(p):
            raise HTTPException(404, f"Does not exist: {p}")
        if os.path.isdir(p):
            for name in sorted(os.listdir(p)):
                fp = os.path.join(p, name)
                if os.path.isfile(fp) and fp.lower().endswith(".blend"):
                    added.append(_add_and_inspect(fp))
            continue
        if not p.lower().endswith(".blend"):
            raise HTTPException(400, f"Not a .blend file: {p}")
        added.append(_add_and_inspect(p))
    return {"added": added}


@app.post("/api/files/upload")
async def api_files_upload(files: list[UploadFile] = FastAPIFile(...)):
    added = []
    for uf in files:
        name = os.path.basename(uf.filename or "archivo.blend")
        if not name.lower().endswith(".blend"):
            continue
        dest = config.UPLOADS_DIR / name
        if dest.exists():
            stem, ext = os.path.splitext(name)
            dest = config.UPLOADS_DIR / f"{stem}_{int(time.time())}{ext}"
        with open(dest, "wb") as out:
            while True:
                chunk = await uf.read(4 * 1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        added.append(_add_and_inspect(str(dest), origin="upload"))
    return {"added": added}


@app.post("/api/files/{fid}/inspect")
def api_file_inspect(fid: str):
    if not store.get_file(fid):
        raise HTTPException(404, "File not found")
    inspector.request(fid)
    return {"ok": True}


@app.delete("/api/files/{fid}")
def api_file_delete(fid: str):
    for j in store.jobs():
        if j.get("file_id") == fid and j.get("status") in ("queued", "running"):
            raise HTTPException(409, "This file has queued or running jobs.")
    if not store.remove_file(fid):
        raise HTTPException(404, "File not found")
    return {"ok": True}


# ---------------------------------------------------------------- trabajos (cola)
class JobBody(BaseModel):
    file_id: str
    scene: str
    frames: dict | None = None
    overrides: dict | None = None


def _clean_overrides(raw: dict | None) -> dict:
    """Valida los overrides que llegan de la UI y descarta lo que no aplica."""
    ov = dict(raw or {})
    out: dict = {}
    engine = str(ov.get("engine") or "").strip().upper()
    if engine:
        out["engine"] = engine
    device = str(ov.get("device") or "").strip().upper()
    if device in ("GPU", "CPU"):
        out["device"] = device
    for key, lo, hi in (("samples", 1, 1_000_000), ("resolution_percentage", 1, 400)):
        val = ov.get(key)
        if val in (None, ""):
            continue
        try:
            val = int(val)
        except (TypeError, ValueError):
            raise HTTPException(400, f"Invalid value for {key}")
        if lo <= val <= hi:
            out[key] = val
    out_dir = str(ov.get("output_dir") or "").strip().strip('"')
    if out_dir:
        out["output_dir"] = out_dir

    # Script de Python. Al elegirlo de la biblioteca se guarda una COPIA del
    # código en el trabajo: editar la biblioteca después no cambia lo que ya
    # está en cola. Si la petición ya trae el código, se respeta tal cual.
    sid = str(ov.get("script_id") or "").strip()
    code = ov.get("script")
    if code is None and sid:
        rec = store.get_script(sid)
        if not rec:
            raise HTTPException(404, "That script is no longer in the library")
        out["script_id"] = sid
        out["script_name"] = rec.get("name") or "untitled"
        out["script"] = rec.get("code") or ""
    elif code:
        out["script"] = str(code)[:MAX_SCRIPT]
        out["script_name"] = str(ov.get("script_name") or "script")[:120]
        if sid:
            out["script_id"] = sid

    for key in formats.FORMAT_KEYS:
        if ov.get(key) not in (None, ""):
            out[key] = ov[key]
    return formats.normalize(out)


def _clean_frames(raw: dict | None, scene: dict | None) -> dict:
    fr_in = raw or {}
    scene = scene or {}
    try:
        start = int(fr_in["start"]) if fr_in.get("start") not in (None, "") else int(scene.get("frame_start") or 1)
        end = int(fr_in["end"]) if fr_in.get("end") not in (None, "") else int(scene.get("frame_end") or start)
    except (TypeError, ValueError):
        raise HTTPException(400, "Invalid frame range")
    if end < start:
        raise HTTPException(400, f"Invalid frame range: {start}–{end}")
    return {"start": start, "end": end}


def _scene_of(frec: dict, name: str) -> dict:
    for s in (frec.get("report") or {}).get("scenes", []):
        if s.get("name") == name:
            return s
    raise HTTPException(400, "Scene not found in the report. Re-inspect the file.")


@app.post("/api/jobs")
def api_job_add(body: JobBody):
    frec = store.get_file(body.file_id)
    if not frec:
        raise HTTPException(404, "File not found")
    scene = _scene_of(frec, body.scene)
    job = {
        "file_id": body.file_id,
        "file_path": frec["path"],
        "file_name": frec["name"],
        "scene": body.scene,
        "frames": _clean_frames(body.frames, scene),
        "overrides": _clean_overrides(body.overrides),
        # Formato guardado en el .blend: permite mostrar el formato efectivo de
        # cada trabajo en la cola y detectar colas con formatos mezclados.
        "scene_format": scene.get("file_format"),
        "scene_container": scene.get("ffmpeg_container"),
    }
    return {"job": store.add_job(job)}


class JobPatchBody(BaseModel):
    frames: dict | None = None
    overrides: dict | None = None


@app.patch("/api/jobs/{jid}")
def api_job_patch(jid: str, body: JobPatchBody):
    """Edita un trabajo que aún está en cola (formato, salida, frames…)."""
    job = store.get_job(jid)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.get("status") != "queued":
        raise HTTPException(409, "Only queued jobs can be edited")
    fields = {}
    if body.overrides is not None:
        fields["overrides"] = _clean_overrides(body.overrides)
    if body.frames is not None:
        frec = store.get_file(job.get("file_id") or "") or {}
        scene = None
        for s in (frec.get("report") or {}).get("scenes", []):
            if s.get("name") == job.get("scene"):
                scene = s
        fields["frames"] = _clean_frames(body.frames, scene or job.get("frames"))
    if fields:
        store.update_job(jid, **fields)
    return {"job": store.get_job(jid)}


class FormatBody(BaseModel):
    job_ids: list[str] | None = None   # None = todos los trabajos en cola
    format: str | None = None          # "" o None = volver al formato del .blend
    color_depth: str | None = None
    color_mode: str | None = None
    quality: int | None = None
    exr_codec: str | None = None
    ffmpeg_container: str | None = None
    ffmpeg_codec: str | None = None


@app.post("/api/jobs/format")
def api_jobs_format(body: FormatBody):
    """Aplica un formato de salida a varios trabajos en cola de una vez.

    Resuelve el caso típico: se encolan archivos de distintos proyectos y uno
    venía guardado en otro formato. Solo toca las claves de formato; el resto
    de overrides (carpeta, motor, samples…) de cada trabajo se conserva.
    """
    patch = formats.normalize({k: getattr(body, k) for k in formats.FORMAT_KEYS})
    wanted = set(body.job_ids) if body.job_ids else None
    changed = []
    for job in store.jobs():
        if job.get("status") != "queued":
            continue
        if wanted is not None and job.get("id") not in wanted:
            continue
        ov = {k: v for k, v in (job.get("overrides") or {}).items()
              if k not in formats.FORMAT_KEYS}
        ov.update(patch)
        store.update_job(job["id"], overrides=ov)
        changed.append(job["id"])
    return {"changed": changed, "format": patch}


class JobScriptBody(BaseModel):
    job_ids: list[str] | None = None   # None = todos los trabajos en cola
    script_id: str | None = None       # "" o None = quitar el script


@app.post("/api/jobs/script")
def api_jobs_script(body: JobScriptBody):
    """Pone (o quita) un script a varios trabajos en cola de una vez."""
    sid = (body.script_id or "").strip()
    patch = {}
    if sid:
        rec = store.get_script(sid)
        if not rec:
            raise HTTPException(404, "That script is no longer in the library")
        patch = {"script_id": sid, "script_name": rec.get("name") or "untitled",
                 "script": rec.get("code") or ""}
    wanted = set(body.job_ids) if body.job_ids else None
    changed = []
    for job in store.jobs():
        if job.get("status") != "queued":
            continue
        if wanted is not None and job.get("id") not in wanted:
            continue
        ov = {k: v for k, v in (job.get("overrides") or {}).items()
              if k not in ("script", "script_name", "script_id")}
        ov.update(patch)
        store.update_job(job["id"], overrides=ov)
        changed.append(job["id"])
    return {"changed": changed, "script": patch.get("script_name")}


class MoveBody(BaseModel):
    direction: int = 1


@app.post("/api/jobs/{jid}/move")
def api_job_move(jid: str, body: MoveBody):
    if not store.get_job(jid):
        raise HTTPException(404, "Job not found")
    moved = store.move_job(jid, 1 if body.direction >= 0 else -1)
    return {"ok": True, "moved": moved}


@app.post("/api/jobs/{jid}/cancel")
def api_job_cancel(jid: str):
    if not store.get_job(jid):
        raise HTTPException(404, "Job not found")
    worker.cancel(jid)
    return {"ok": True}


@app.post("/api/jobs/{jid}/retry")
def api_job_retry(jid: str):
    if not store.get_job(jid):
        raise HTTPException(404, "Job not found")
    if not worker.retry(jid):
        raise HTTPException(409, "The job is rendering: cancel it before retrying")
    return {"ok": True}


@app.delete("/api/jobs/{jid}")
def api_job_delete(jid: str):
    if not store.get_job(jid):
        raise HTTPException(404, "Job not found")
    worker.remove(jid)
    return {"ok": True}


@app.get("/api/jobs/{jid}/log")
def api_job_log(jid: str, tail: int = 300):
    job = store.get_job(jid)
    if not job:
        raise HTTPException(404, "Job not found")
    log_path = config.LOGS_DIR / f"job_{jid}.log"
    if not log_path.exists():
        return {"log": ""}
    data = log_path.read_text(encoding="utf-8", errors="replace")
    lines = data.splitlines()
    if tail and tail > 0:
        lines = lines[-tail:]
    return {"log": "\n".join(lines)}


def _job_frame_files(job: dict) -> list:
    out = []
    for p in job.get("outputs") or []:
        name = os.path.basename(p)
        m = re.search(r"(\d+)(?=\.[A-Za-z0-9]+$)", name)
        out.append({"path": p, "name": name, "frame": int(m.group(1)) if m else None,
                    "exists": os.path.exists(p)})
    out.sort(key=lambda x: (x["frame"] is None, x["frame"] or 0))
    return out


@app.get("/api/jobs/{jid}/outputs")
def api_job_outputs(jid: str):
    job = store.get_job(jid)
    if not job:
        raise HTTPException(404, "Job not found")
    return {"outputs": _job_frame_files(job), "preview": job.get("preview") or {}}


@app.get("/api/jobs/{jid}/frames/{frame}")
def api_job_frame(jid: str, frame: int):
    job = store.get_job(jid)
    if not job:
        raise HTTPException(404, "Job not found")
    files = [f for f in _job_frame_files(job) if f["exists"]]
    for f in files:
        if f["frame"] == frame:
            return FileResponse(f["path"])
    fstart = int((job.get("frames") or {}).get("start") or 1)
    idx = frame - fstart
    if 0 <= idx < len(files):
        return FileResponse(files[idx]["path"])
    raise HTTPException(404, "Frame not found")


@app.get("/api/jobs/{jid}/video")
def api_job_video(jid: str):
    job = store.get_job(jid)
    if not job:
        raise HTTPException(404, "Job not found")
    video = (job.get("preview") or {}).get("video")
    if not video or not os.path.exists(video):
        raise HTTPException(404, "No preview video")
    return FileResponse(video, media_type="video/mp4")


@app.post("/api/jobs/{jid}/open")
def api_job_open(jid: str):
    """Abre la carpeta de salida del trabajo (seleccionando el primer frame existente)."""
    job = store.get_job(jid)
    if not job:
        raise HTTPException(404, "Job not found")
    files = [f for f in _job_frame_files(job) if f["exists"]]
    target_dir = None
    if files:
        target_dir = os.path.dirname(files[0]["path"])
    if not target_dir:
        ov_dir = (job.get("overrides") or {}).get("output_dir")
        if ov_dir and os.path.isdir(ov_dir):
            target_dir = ov_dir
    if not target_dir or not os.path.isdir(target_dir):
        raise HTTPException(404, "No output folder available")
    try:
        os.startfile(target_dir)
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"ok": True, "path": target_dir}


# ---------------------------------------------------------------- abrir rutas
class OpenBody(BaseModel):
    path: str


@app.post("/api/open")
def api_open(body: OpenBody):
    p = (body.path or "").strip()
    if not os.path.exists(p):
        raise HTTPException(404, "That path does not exist")
    try:
        if os.path.isdir(p):
            os.startfile(p)  # noqa: S606 (app local)
        else:
            os.startfile(os.path.dirname(p) or p)
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"ok": True}


# ---------------------------------------------------------------- explorador de archivos
@app.get("/api/fs/list")
def api_fs_list(path: str = ""):
    path = (path or "").strip().strip('"')
    home = os.path.expanduser("~")
    if not path:
        drives = []
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZAB":
            root = f"{letter}:\\"
            if os.path.exists(root):
                drives.append({"name": root, "path": root, "type": "drive"})
        favs = []
        for label, sub in (("Home", ""), ("Desktop", "Desktop"), ("Downloads", "Downloads"),
                           ("Developer", "Developer"), ("Videos", "Videos")):
            p = os.path.join(home, sub) if sub else home
            if os.path.isdir(p):
                favs.append({"name": label, "path": p, "type": "dir"})
        return {"path": "", "parent": None, "entries": drives + favs}

    path = os.path.abspath(path)
    if not os.path.isdir(path):
        raise HTTPException(404, "Folder not found")
    parent = os.path.dirname(path.rstrip("\\/"))
    if not parent or parent == path:
        parent = None
    dirs, blends = [], []
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.name.startswith((".", "$")) or e.name.lower().endswith((".blend1", ".blend2")):
                        continue
                    if e.is_dir(follow_symlinks=False):
                        dirs.append({"name": e.name, "path": e.path, "type": "dir"})
                    elif e.is_file(follow_symlinks=False) and e.name.lower().endswith(".blend"):
                        st = e.stat()
                        blends.append({"name": e.name, "path": e.path, "type": "blend",
                                       "size": st.st_size, "mtime": st.st_mtime})
                except OSError:
                    continue
    except OSError as exc:
        raise HTTPException(400, str(exc))
    dirs.sort(key=lambda x: x["name"].lower())
    blends.sort(key=lambda x: x["name"].lower())
    return {"path": path, "parent": parent, "entries": dirs + blends}


# ---------------------------------------------------------------- ajustes
class SettingsBody(BaseModel):
    blender_path: str | None = None
    notifications: bool | None = None
    preview_video: bool | None = None


@app.post("/api/settings")
def api_settings(body: SettingsBody):
    patch = {}
    if body.blender_path is not None:
        bp = body.blender_path.strip()
        if bp and not os.path.exists(bp):
            raise HTTPException(400, "That blender.exe path does not exist")
        patch["blender_path"] = bp
    if body.notifications is not None:
        patch["notifications"] = bool(body.notifications)
    if body.preview_video is not None:
        patch["preview_video"] = bool(body.preview_video)
    store.update_settings(patch)
    return {"settings": store.settings()}


@app.get("/api/blender/check")
def api_blender_check(force: bool = False):
    s = store.settings()
    return config.blender_info((s.get("blender_path") or "").strip() or None, force=force)


@app.post("/api/notify/test")
def api_notify_test():
    ok = notifier.notify("BlendQueue", "Test notification — it works ✓")
    return {"ok": ok}


class PauseBody(BaseModel):
    paused: bool | None = None


@app.post("/api/queue/pause")
def api_queue_pause(body: PauseBody):
    if body.paused is None:
        worker.pause(not worker.paused)
    else:
        worker.pause(bool(body.paused))
    return worker.status()


@app.post("/api/shutdown")
def api_shutdown():
    """Detiene la cola (mata el render en curso) y apaga el servidor."""
    try:
        if worker and worker.current_job_id:
            worker.cancel(worker.current_job_id)
    except Exception:
        pass

    def _stop():
        time.sleep(0.8)
        try:
            if _server_handle is not None:
                _server_handle.should_exit = True
        except Exception:
            pass
        time.sleep(3.0)
        os._exit(0)  # último recurso si el apagado limpio no terminó

    threading.Thread(target=_stop, daemon=True).start()
    return {"ok": True, "message": "BlendQueue is shutting down…"}


# ---------------------------------------------------------------- entrada
_server_handle = None


def main():
    global _server_handle
    parser = argparse.ArgumentParser(description="BlendQueue — local render queue for Blender")
    parser.add_argument("--port", type=int, default=config.DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    config.ensure_dirs()
    url = f"http://127.0.0.1:{args.port}/"
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    import uvicorn
    _server_handle = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port,
                                                   log_level="info"))
    _server_handle.run()


if __name__ == "__main__":
    main()
