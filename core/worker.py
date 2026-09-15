"""Worker secuencial: toma trabajos de la cola y los renderiza con Blender headless."""
from __future__ import annotations

import os
import subprocess
import threading
import time
from collections import deque

from . import config, notifier, renderer


class RenderWorker:
    def __init__(self, store, on_update=None):
        self.store = store
        self.on_update = on_update or (lambda: None)
        self.paused = False
        self.current_job_id = None
        self.current_tail: deque = deque(maxlen=30)
        self._lock = threading.RLock()
        self._proc = None
        self._cancel_ids: set = set()
        self._thread = threading.Thread(target=self._loop, name="render-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()

    # ---------------- control ----------------
    def pause(self, flag: bool) -> None:
        self.paused = bool(flag)
        self.on_update()

    def cancel(self, job_id: str) -> None:
        job = self.store.get_job(job_id)
        if not job:
            return
        status = job.get("status")
        if status == "queued":
            self.store.update_job(job_id, status="canceled", finished_at=time.time(),
                                  error="Cancelado antes de iniciar")
        elif status == "running":
            # Solo se marca para cancelar lo que está corriendo: hacerlo con un
            # trabajo ya terminado dejaba la marca pegada y el siguiente
            # reintento terminaba como "cancelado" aunque hubiera renderizado.
            self._cancel_ids.add(job_id)
            with self._lock:
                if self.current_job_id == job_id and self._proc is not None:
                    self._kill(self._proc)
        self.on_update()

    def retry(self, job_id: str) -> bool:
        job = self.store.get_job(job_id)
        if not job or job.get("status") == "running":
            return False
        self._cancel_ids.discard(job_id)
        self.store.update_job(job_id, status="queued", error=None, progress={}, outputs=[],
                              preview={}, started_at=None, finished_at=None, duration_s=None)
        self.on_update()
        return True

    def remove(self, job_id: str) -> None:
        job = self.store.get_job(job_id)
        if job and job.get("status") == "running":
            self._cancel_ids.add(job_id)
            with self._lock:
                if self._proc is not None:
                    self._kill(self._proc)
        self.store.delete_job(job_id)
        self.on_update()

    @staticmethod
    def _kill(proc) -> None:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=30,
                           creationflags=config.CREATE_NO_WINDOW)
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass

    def status(self) -> dict:
        return {"paused": self.paused, "current_job_id": self.current_job_id}

    def tail(self) -> list:
        return list(self.current_tail)

    # ---------------- loop ----------------
    def _loop(self) -> None:
        while True:
            try:
                if self.paused:
                    time.sleep(0.4)
                    continue
                job = self.store.next_queued_job()
                if not job:
                    time.sleep(0.5)
                    continue
                self._run_job(job)
            except Exception:
                time.sleep(1)

    def _run_job(self, job: dict) -> None:
        jid = job["id"]
        self.current_job_id = jid
        self.current_tail.clear()
        started = time.time()
        self.store.update_job(jid, status="running", started_at=started, error=None,
                              progress={"percent": 0.0, "frame": None, "message": "iniciando Blender…"})
        self.on_update()
        settings = self.store.settings()
        try:
            frec = self.store.get_file(job.get("file_id") or "")
            if not frec or not os.path.exists(job["file_path"]):
                raise RuntimeError("El archivo .blend ya no existe en disco.")
            scene_report = None
            for s in (frec.get("report") or {}).get("scenes", []):
                if s.get("name") == job["scene"]:
                    scene_report = s
                    break
            if scene_report is None and (frec.get("report") or {}).get("scenes"):
                raise RuntimeError("La escena ya no existe en el .blend. Re-inspecciona el archivo.")

            blender = (settings.get("blender_path") or "").strip() or None
            blender = blender or config.find_blender()
            if not blender or not os.path.exists(blender):
                raise RuntimeError("No se encontró blender.exe. Configura la ruta en Ajustes.")

            fr = job.get("frames") or {}
            fstart = int(fr["start"] if fr.get("start") is not None
                         else (scene_report or {}).get("frame_start") or 1)
            fend = int(fr["end"] if fr.get("end") is not None
                       else (scene_report or {}).get("frame_end") or fstart)
            if fend < fstart:
                raise RuntimeError(f"Rango de frames inválido: {fstart}-{fend}")
            total = max(1, fend - fstart + 1)

            renderer.ensure_output_dir(job, scene_report)
            script_path = renderer.write_job_script(job, config.SCRIPTS_DIR / f"job_{jid}.py")
            cmd = renderer.build_cmd(blender, job, scene_report, script_path)
            log_path = config.LOGS_DIR / f"job_{jid}.log"
            parser = renderer.ProgressParser(fstart, fend)
            outputs = []

            with open(log_path, "w", encoding="utf-8", errors="replace") as logf:
                logf.write("CMD: " + subprocess.list2cmdline(cmd) + "\n\n")
                logf.flush()
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                    creationflags=config.CREATE_NO_WINDOW,
                )
                with self._lock:
                    self._proc = proc
                last_push = 0.0
                for line in proc.stdout:
                    line = line.rstrip("\r\n")
                    if not line:
                        continue
                    logf.write(line + "\n")
                    if not renderer.is_noise(line):
                        self.current_tail.append(line)
                    m = renderer.SAVED_RE.search(line)
                    if m:
                        outputs.append(m.group(1))
                    if parser.feed(line):
                        nowt = time.time()
                        if nowt - last_push > 0.35:
                            last_push = nowt
                            self._push_progress(jid, parser, started, fend, total)
                rc = proc.wait()
                with self._lock:
                    self._proc = None

            canceled = jid in self._cancel_ids
            self._cancel_ids.discard(jid)
            duration = round(time.time() - started, 1)

            if canceled:
                self.store.update_job(jid, status="canceled", finished_at=time.time(),
                                      duration_s=duration)
            elif rc != 0:
                tail = self._error_tail(log_path)
                self.store.update_job(jid, status="error", finished_at=time.time(),
                                      duration_s=duration,
                                      error=f"Blender terminó con código {rc}. {tail}")
                self._notify(settings, "Render con error", self._label(job))
            else:
                if not outputs:
                    outputs = self._scan_outputs(job, scene_report, started)
                preview = {}
                if settings.get("preview_video", True):
                    dest = str(config.PREVIEWS_DIR / f"{jid}.mp4")
                    log_fn = lambda msg: self._append_log(log_path, msg)
                    blocked = renderer.preview_block_reason(
                        renderer.effective_format(job, scene_report))
                    video = None
                    movie = next((p for p in outputs if os.path.splitext(p)[1].lower()
                                  in renderer.VIDEO_EXTS and os.path.exists(p)), None)
                    if blocked and not movie:
                        preview["note"] = blocked
                        log_fn("preview omitido: " + blocked)
                    elif movie:
                        video = renderer.remux_preview(movie, dest, log=log_fn)
                    elif len(outputs) > 1:
                        fps = float((scene_report or {}).get("fps") or 24)
                        video = renderer.build_preview_video(outputs, fps, dest, log=log_fn)
                    if not blocked or movie:
                        log_fn("preview: movie=%s outputs=%d video=%s"
                               % (movie or "-", len(outputs), video or "no generado"))
                    if video:
                        preview["video"] = video
                nframes = fend - fstart + 1
                self.store.update_job(jid, status="done", finished_at=time.time(),
                                      duration_s=duration, outputs=outputs, preview=preview,
                                      progress={"percent": 1.0, "frame": fend,
                                                "message": "completado"})
                self._notify(settings, "Render terminado",
                             self._label(job) + f" · {nframes} frame(s)")
        except Exception as exc:
            self.store.update_job(jid, status="error", finished_at=time.time(), error=str(exc))
            self._notify(settings, "Render con error", self._label(job) + " · " + str(exc))
        finally:
            self.current_job_id = None
            self.on_update()

    # ---------------- helpers ----------------
    def _label(self, job: dict) -> str:
        return f"{job.get('file_name')} · {job.get('scene')}"

    def _notify(self, settings: dict, title: str, message: str) -> None:
        if settings.get("notifications", True):
            try:
                notifier.notify(title, message)
            except Exception:
                pass

    def _push_progress(self, jid: str, parser, started: float, fend: int, total: int) -> None:
        elapsed = time.time() - started
        pct = parser.percent
        eta = None
        if 0.02 < pct < 1.0:
            eta = elapsed / pct - elapsed
        msg = f"frame {parser.frame} de {fend}" if parser.frame is not None else "preparando…"
        self.store.update_job(jid, progress={
            "percent": round(pct, 4),
            "frame": parser.frame,
            "total_frames": total,
            "elapsed_s": round(elapsed, 1),
            "eta_s": round(eta, 1) if eta else None,
            "remaining_text": parser.remaining_text,
            "message": msg,
        })
        self.on_update()

    @staticmethod
    def _append_log(log_path, msg: str) -> None:
        try:
            with open(log_path, "a", encoding="utf-8", errors="replace") as fh:
                fh.write(f"[blendqueue] {msg}\n")
        except Exception:
            pass

    @staticmethod
    def _error_tail(log_path, limit: int = 800) -> str:
        try:
            data = log_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return "Revisa el log del trabajo."
        lines = [l for l in data.splitlines() if l.strip() and not renderer.is_noise(l)]
        # Si reventó un script de Python, lo útil es la excepción: el final del
        # log solo trae el banner de Blender y "Blender quit".
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].startswith("Traceback (most recent call last)"):
                for line in lines[i + 1:]:
                    if line[:1] not in (" ", "\t"):
                        return ("Error en el script: " + line.strip())[:limit]
                break
        tail = " | ".join(lines[-3:])[-limit:]
        return tail or "Revisa el log del trabajo."

    @staticmethod
    def _scan_outputs(job: dict, scene_report: dict | None, started: float) -> list:
        """Salidas del render cuando Blender no las anunció con 'Saved:' (video).

        Se limita a archivos escritos durante este trabajo y, cuando se conoce,
        a la extensión y al prefijo que le corresponden.
        """
        ov = job.get("overrides") or {}
        out_dir = (ov.get("output_dir") or "").strip()
        stem = renderer.output_stem(job).lower() if out_dir else None
        if not out_dir:
            raw = ((scene_report or {}).get("filepath_raw") or "").strip()
            if not raw:
                return []
            resolved = renderer.resolve_relative(raw, job["file_path"])
            out_dir = resolved if resolved.endswith(("\\", "/")) else os.path.dirname(resolved)
        out_dir = os.path.abspath(out_dir)
        ext = (renderer.expected_extension(job, scene_report) or "").lower()
        results = []
        try:
            for name in os.listdir(out_dir):
                low = name.lower()
                if ext and not low.endswith(ext):
                    continue
                if stem and not low.startswith(stem):
                    continue
                p = os.path.join(out_dir, name)
                try:
                    if os.path.isfile(p) and os.path.getmtime(p) >= started - 5:
                        results.append(p)
                except OSError:
                    pass
        except OSError:
            pass
        results.sort(key=lambda p: os.path.getmtime(p))
        return results
