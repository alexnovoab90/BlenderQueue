"""Sequential worker: takes jobs off the queue and renders them with headless Blender."""
from __future__ import annotations

import os
import subprocess
import threading
import time
from collections import deque

from . import config, notifier, renderer, system


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
                                  error="Canceled before starting")
        elif status == "running":
            # Only what is actually running gets flagged: doing it on a finished
            # job left the flag stuck and the next retry ended up "canceled" even
            # though it had rendered fine.
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
        self.store.update_job(job_id, status="queued", error=None, note=None, progress={},
                              outputs=[], preview={}, render_info=None, started_at=None,
                              finished_at=None, duration_s=None)
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
        system.kill_process_tree(proc)

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
        self.store.update_job(jid, status="running", started_at=started, error=None, note=None,
                              render_info=None,
                              progress={"percent": 0.0, "frame": None, "message": "starting Blender…"})
        self.on_update()
        settings = self.store.settings()
        try:
            frec = self.store.get_file(job.get("file_id") or "")
            if not frec or not os.path.exists(job["file_path"]):
                raise RuntimeError("The .blend file no longer exists on disk.")
            scene_report = None
            for s in (frec.get("report") or {}).get("scenes", []):
                if s.get("name") == job["scene"]:
                    scene_report = s
                    break
            if scene_report is None and (frec.get("report") or {}).get("scenes"):
                raise RuntimeError("That scene no longer exists in the .blend. Re-inspect the file.")

            blender = (settings.get("blender_path") or "").strip() or None
            blender = blender or config.find_blender()
            if not blender or not os.path.exists(blender):
                raise RuntimeError("Blender not found. Set the path in Settings.")

            fr = job.get("frames") or {}
            fstart = int(fr["start"] if fr.get("start") is not None
                         else (scene_report or {}).get("frame_start") or 1)
            fend = int(fr["end"] if fr.get("end") is not None
                       else (scene_report or {}).get("frame_end") or fstart)
            if fend < fstart:
                raise RuntimeError(f"Invalid frame range: {fstart}-{fend}")
            total = max(1, fend - fstart + 1)

            renderer.ensure_output_dir(job, scene_report)
            script_path = renderer.write_job_script(job, config.SCRIPTS_DIR / f"job_{jid}.py")
            cmd = renderer.build_cmd(blender, job, scene_report, script_path)
            log_path = config.LOGS_DIR / f"job_{jid}.log"
            parser = renderer.ProgressParser(fstart, fend)
            clock = renderer.FrameClock(movie=renderer.effective_is_movie(job, scene_report))
            outputs = []

            with open(log_path, "w", encoding="utf-8", errors="replace") as logf:
                logf.write("CMD: " + subprocess.list2cmdline(cmd) + "\n\n")
                logf.flush()
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                    **system.popen_kwargs(),
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
                        clock.saved(time.time())
                    info = renderer.parse_render_info(line)
                    if info:
                        self.store.update_job(jid, render_info=info)
                        self.on_update()
                    if parser.feed(line):
                        nowt = time.time()
                        clock.frame(parser.frame, nowt)
                        if nowt - last_push > 0.35:
                            last_push = nowt
                            self._push_progress(jid, parser, started, fend, total, clock)
                rc = proc.wait()
                clock.finish(time.time())
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
                                      error=f"Blender exited with code {rc}. {tail}")
                self._notify(settings, "Render failed", self._label(job))
            else:
                if not outputs and renderer.effective_is_movie(job, scene_report):
                    # Only movies stay silent: image sequences always print
                    # "Saved:", so no line means nothing was written. Scanning
                    # the folder there would pick up a previous render's files.
                    outputs = self._scan_outputs(job, scene_report, started)
                failure, note = (None, None)
                if not outputs:
                    failure, note = self._why_nothing(log_path, parser.frame is not None)
                if failure:
                    self.store.update_job(jid, status="error", finished_at=time.time(),
                                          duration_s=duration, error=failure)
                    self._notify(settings, "Render failed", self._label(job))
                    return
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
                        log_fn("preview skipped: " + blocked)
                    elif movie:
                        video = renderer.remux_preview(movie, dest, log=log_fn)
                    elif len(outputs) > 1:
                        fps = float((scene_report or {}).get("fps") or 24)
                        video = renderer.build_preview_video(outputs, fps, dest, log=log_fn)
                    if not blocked or movie:
                        log_fn("preview: movie=%s outputs=%d video=%s"
                               % (movie or "-", len(outputs), video or "not generated"))
                    if video:
                        preview["video"] = video
                nframes = fend - fstart + 1
                if note:
                    preview["note"] = note
                self.store.update_job(jid, status="done", finished_at=time.time(),
                                      duration_s=duration, outputs=outputs, preview=preview,
                                      note=note,
                                      progress={"percent": 1.0, "frame": fend,
                                                "message": "completed",
                                                "frames_done": clock.done,
                                                "last_frame_s": clock.last,
                                                "avg_frame_s": clock.average})
                self._notify(settings, "Render finished",
                             self._label(job) + f" · {nframes} frame(s)")
        except Exception as exc:
            self.store.update_job(jid, status="error", finished_at=time.time(), error=str(exc))
            self._notify(settings, "Render failed", self._label(job) + " · " + str(exc))
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

    def _push_progress(self, jid: str, parser, started: float, fend: int, total: int,
                       clock=None) -> None:
        elapsed = time.time() - started
        pct = parser.percent
        eta = None
        if 0.02 < pct < 1.0:
            eta = elapsed / pct - elapsed
        msg = f"frame {parser.frame} of {fend}" if parser.frame is not None else "preparing…"
        self.store.update_job(jid, progress={
            "percent": round(pct, 4),
            "frame": parser.frame,
            "total_frames": total,
            "elapsed_s": round(elapsed, 1),
            "eta_s": round(eta, 1) if eta else None,
            "remaining_text": parser.remaining_text,
            "message": msg,
            "frames_done": clock.done if clock else None,
            "last_frame_s": clock.last if clock else None,
            "avg_frame_s": clock.average if clock else None,
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
    def _why_nothing(log_path, rendered_a_frame: bool) -> tuple:
        """(error, note) for a render that exited with code 0 but wrote no file.

        Skipping frames that are already on disk (Overwrite off) is a legitimate
        outcome and only earns a note. Anything else is a failure: Blender
        reports some errors -- a video encoder that cannot start, for one -- and
        still exits with 0, which used to end as "done" with nothing on disk.
        """
        try:
            data = log_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            data = ""
        if "skipped to not overwrite" in data or "Skipping existing frame" in data:
            skipped = data.count("Skipping existing frame")
            return None, (f"No files written: Blender skipped {skipped} frame(s) that already "
                          "exist (Overwrite is off). Re-queue with Overwrite to render them again.")
        errors = renderer.blender_errors(data)
        if errors:
            return "Blender rendered nothing: " + " · ".join(errors[:2]), None
        if not rendered_a_frame:
            return "Blender exited without rendering any frame. Check the job log.", None
        return None, "Blender rendered, but no output file was found. Check the job log."

    @staticmethod
    def _error_tail(log_path, limit: int = 800) -> str:
        try:
            data = log_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return "Check the job log."
        lines = [l for l in data.splitlines() if l.strip() and not renderer.is_noise(l)]
        # If a Python script blew up, the useful part is the exception: the end
        # of the log only holds Blender's banner and "Blender quit".
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].startswith("Traceback (most recent call last)"):
                for line in lines[i + 1:]:
                    if line[:1] not in (" ", "\t"):
                        return ("Script error: " + line.strip())[:limit]
                break
        errors = renderer.blender_errors(data)
        if errors:
            return " · ".join(errors[:2])[:limit]
        tail = " | ".join(lines[-3:])[-limit:]
        return tail or "Check the job log."

    @staticmethod
    def _scan_outputs(job: dict, scene_report: dict | None, started: float) -> list:
        """Render outputs when Blender did not announce them with 'Saved:' (video).

        Limited to files written during this job and, when known, to the matching
        extension and filename prefix.
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
