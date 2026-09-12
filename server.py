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

from fastapi import FastAPI, HTTPException, UploadFile, File as FastAPIFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import config, notifier
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


# ---------------------------------------------------------------- estáticos
@app.get("/")
def index():
    return FileResponse(str(config.STATIC_DIR / "index.html"))


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
    return {
        "blender": binfo,
        "settings": settings,
        "worker": worker.status(),
        "inspector": inspector.status(),
        "files": snap["files"],
        "jobs": snap["jobs"],
        "log_tail": worker.tail(),
        "ffmpeg": bool(config.ffmpeg_path()),
        "now": time.time(),
    }


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
            raise HTTPException(404, f"No existe: {p}")
        if os.path.isdir(p):
            for name in sorted(os.listdir(p)):
                fp = os.path.join(p, name)
                if os.path.isfile(fp) and fp.lower().endswith(".blend"):
                    added.append(_add_and_inspect(fp))
            continue
        if not p.lower().endswith(".blend"):
            raise HTTPException(400, f"No es un archivo .blend: {p}")
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
        raise HTTPException(404, "Archivo no encontrado")
    inspector.request(fid)
    return {"ok": True}


@app.delete("/api/files/{fid}")
def api_file_delete(fid: str):
    for j in store.jobs():
        if j.get("file_id") == fid and j.get("status") in ("queued", "running"):
            raise HTTPException(409, "El archivo tiene trabajos en cola o renderizando.")
    if not store.remove_file(fid):
        raise HTTPException(404, "Archivo no encontrado")
    return {"ok": True}


# ---------------------------------------------------------------- trabajos (cola)
class JobBody(BaseModel):
    file_id: str
    scene: str
    frames: dict | None = None
    overrides: dict | None = None


@app.post("/api/jobs")
def api_job_add(body: JobBody):
    frec = store.get_file(body.file_id)
    if not frec:
        raise HTTPException(404, "Archivo no encontrado")
    scene = None
    for s in (frec.get("report") or {}).get("scenes", []):
        if s.get("name") == body.scene:
            scene = s
            break
    if scene is None:
        raise HTTPException(400, "Escena no encontrada en el reporte. Re-inspecciona el archivo.")

    ov = dict(body.overrides or {})
    for k in list(ov.keys()):
        v = ov[k]
        if v in (None, "", 0):
            ov.pop(k)
            continue
        if k in ("samples", "resolution_percentage"):
            try:
                ov[k] = int(v)
            except (TypeError, ValueError):
                ov.pop(k)
    fr_in = body.frames or {}
    try:
        fstart = int(fr_in["start"]) if fr_in.get("start") is not None else int(scene.get("frame_start") or 1)
        fend = int(fr_in["end"]) if fr_in.get("end") is not None else int(scene.get("frame_end") or fstart)
    except (TypeError, ValueError):
        raise HTTPException(400, "Rango de frames inválido")

    job = {
        "file_id": body.file_id,
        "file_path": frec["path"],
        "file_name": frec["name"],
        "scene": body.scene,
        "frames": {"start": fstart, "end": fend},
        "overrides": ov,
    }
    return {"job": store.add_job(job)}


class MoveBody(BaseModel):
    direction: int = 1


@app.post("/api/jobs/{jid}/move")
def api_job_move(jid: str, body: MoveBody):
    store.move_job(jid, 1 if body.direction >= 0 else -1)
    return {"ok": True}


@app.post("/api/jobs/{jid}/cancel")
def api_job_cancel(jid: str):
    if not store.get_job(jid):
        raise HTTPException(404, "Trabajo no encontrado")
    worker.cancel(jid)
    return {"ok": True}


@app.post("/api/jobs/{jid}/retry")
def api_job_retry(jid: str):
    if not store.get_job(jid):
        raise HTTPException(404, "Trabajo no encontrado")
    worker.retry(jid)
    return {"ok": True}


@app.delete("/api/jobs/{jid}")
def api_job_delete(jid: str):
    if not store.get_job(jid):
        raise HTTPException(404, "Trabajo no encontrado")
    worker.remove(jid)
    return {"ok": True}


@app.get("/api/jobs/{jid}/log")
def api_job_log(jid: str, tail: int = 300):
    job = store.get_job(jid)
    if not job:
        raise HTTPException(404, "Trabajo no encontrado")
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
        raise HTTPException(404, "Trabajo no encontrado")
    return {"outputs": _job_frame_files(job), "preview": job.get("preview") or {}}


@app.get("/api/jobs/{jid}/frames/{frame}")
def api_job_frame(jid: str, frame: int):
    job = store.get_job(jid)
    if not job:
        raise HTTPException(404, "Trabajo no encontrado")
    files = [f for f in _job_frame_files(job) if f["exists"]]
    for f in files:
        if f["frame"] == frame:
            return FileResponse(f["path"])
    fstart = int((job.get("frames") or {}).get("start") or 1)
    idx = frame - fstart
    if 0 <= idx < len(files):
        return FileResponse(files[idx]["path"])
    raise HTTPException(404, "Frame no encontrado")


@app.get("/api/jobs/{jid}/video")
def api_job_video(jid: str):
    job = store.get_job(jid)
    if not job:
        raise HTTPException(404, "Trabajo no encontrado")
    video = (job.get("preview") or {}).get("video")
    if not video or not os.path.exists(video):
        raise HTTPException(404, "Sin video de preview")
    return FileResponse(video, media_type="video/mp4")


@app.post("/api/jobs/{jid}/open")
def api_job_open(jid: str):
    """Abre la carpeta de salida del trabajo (seleccionando el primer frame existente)."""
    job = store.get_job(jid)
    if not job:
        raise HTTPException(404, "Trabajo no encontrado")
    files = [f for f in _job_frame_files(job) if f["exists"]]
    if files:
        p = files[0]["path"]
        try:
            subprocess.Popen(f'explorer /select,"{p}"', shell=True,
                             creationflags=config.CREATE_NO_WINDOW)
            return {"ok": True, "path": p}
        except Exception as exc:
            raise HTTPException(500, str(exc))
    ov_dir = (job.get("overrides") or {}).get("output_dir")
    if ov_dir and os.path.isdir(ov_dir):
        os.startfile(ov_dir)
        return {"ok": True, "path": ov_dir}
    raise HTTPException(404, "Sin carpeta de salida disponible")


# ---------------------------------------------------------------- abrir rutas
class OpenBody(BaseModel):
    path: str


@app.post("/api/open")
def api_open(body: OpenBody):
    p = (body.path or "").strip()
    if not os.path.exists(p):
        raise HTTPException(404, "La ruta no existe")
    try:
        if os.path.isdir(p):
            os.startfile(p)  # noqa: S606 (app local)
        else:
            subprocess.Popen(f'explorer /select,"{p}"', shell=True,
                             creationflags=config.CREATE_NO_WINDOW)
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
        for label, sub in (("Inicio", ""), ("Escritorio", "Desktop"), ("Descargas", "Downloads"),
                           ("Developer", "Developer"), ("Videos", "Videos")):
            p = os.path.join(home, sub) if sub else home
            if os.path.isdir(p):
                favs.append({"name": label, "path": p, "type": "dir"})
        return {"path": "", "parent": None, "entries": drives + favs}

    path = os.path.abspath(path)
    if not os.path.isdir(path):
        raise HTTPException(404, "Carpeta no encontrada")
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
            raise HTTPException(400, "La ruta de blender.exe no existe")
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
    ok = notifier.notify("BlendQueue", "Notificación de prueba — funciona ✓")
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


# ---------------------------------------------------------------- entrada
def main():
    parser = argparse.ArgumentParser(description="BlendQueue — cola local de renders Blender")
    parser.add_argument("--port", type=int, default=config.DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    config.ensure_dirs()
    url = f"http://127.0.0.1:{args.port}/"
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
