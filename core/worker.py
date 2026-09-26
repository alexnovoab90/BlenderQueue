"""Sequential worker: takes jobs off the queue and renders them with headless Blender."""
from __future__ import annotations

import os
import subprocess
import threading
import time
from collections import deque

from . import config, notifier, renderer, system

# Why a render was stopped before its end (see pause_job and stop_for_shutdown).
STOP_PAUSE = "pause"         # the user paused it: it waits for ▶ Resume, and so does the queue
STOP_SHUTDOWN = "shutdown"   # BlendQueue is closing: it goes back to the queue, to resume next time


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
        self._stops: dict = {}               # job id -> STOP_PAUSE | STOP_SHUTDOWN
        self._current_is_movie = False
        # A video paused in place (suspended): see pause_job().
        self._paused_since = None
        self._paused_total = 0.0
        self._clock = None
        self._thread = threading.Thread(target=self._loop, name="render-worker", daemon=True)

    def start(self) -> None:
        self._kill_orphans()
        self._thread.start()

    def _kill_orphans(self) -> None:
        """Renders a previous BlendQueue left running when it was killed.

        On Windows system.bind_to_app() already takes them down with it. Elsewhere
        they keep rendering orphaned: holding the GPU and writing the very frames
        the resumed job is about to render. PID + birth time, so a PID reused by
        another program is never touched.
        """
        for job in self.store.jobs():
            pid, birth = job.get("pid"), job.get("pid_birth")
            if not pid:
                continue
            if birth and system.process_birth(pid) == birth:
                system.kill_pid_tree(pid)
            self.store.update_job(job["id"], pid=None, pid_birth=None)

    # ---------------- control ----------------
    def pause(self, flag: bool) -> None:
        self.paused = bool(flag)
        self.on_update()

    def cancel(self, job_id: str) -> None:
        job = self.store.get_job(job_id)
        if not job:
            return
        status = job.get("status")
        if status in ("queued", "paused"):
            self.store.update_job(job_id, status="canceled", finished_at=time.time(),
                                  paused_at=None, resume_from=None,
                                  error="Canceled before starting" if status == "queued" else None)
        elif status == "running":
            # Only what is actually running gets flagged: doing it on a finished
            # job left the flag stuck and the next retry ended up "canceled" even
            # though it had rendered fine.
            self._cancel_ids.add(job_id)
            with self._lock:
                if self.current_job_id == job_id and self._proc is not None:
                    self._kill(self._proc)
        self.on_update()

    def pause_job(self, job_id: str) -> str | None:
        """Pauses the render in progress. Returns "stop", "suspend" or None.

        An image sequence is stopped: Blender closes, which frees the GPU and its
        VRAM, and ▶ Resume starts it again right after the last frame saved. The
        queue pauses as well, or the next job would take the GPU at once.

        A video cannot restart mid-file, so Blender is suspended instead: frozen
        where it is, keeping its memory, and resume_job() continues that frame.
        """
        with self._lock:
            if (self.current_job_id != job_id or self._proc is None
                    or self._paused_since is not None or job_id in self._stops):
                return None
            if self._current_is_movie:
                if not system.suspend_process_tree(self._proc):
                    return None
                self._paused_since = time.time()
                mode = "suspend"
            else:
                self.paused = True
                self._stops[job_id] = STOP_PAUSE
                self._kill(self._proc)
                mode = "stop"
        if mode == "suspend":
            self.store.update_job(job_id, paused_at=self._paused_since)
        self.on_update()
        return mode

    def resume_job(self, job_id: str) -> bool:
        job = self.store.get_job(job_id)
        if not job:
            return False
        status = job.get("status")
        if status == "running":
            with self._lock:
                if (self.current_job_id != job_id or self._proc is None
                        or self._paused_since is None):
                    return False
                if not system.resume_process_tree(self._proc):
                    return False
                gap = time.time() - self._paused_since
                self._paused_since = None
                self._paused_total += gap
                if self._clock:
                    self._clock.shift(gap)      # the frame in progress did not take that long
            self.store.update_job(job_id, paused_at=None, paused_s=round(self._paused_total, 1))
        elif status == "paused" or (status == "error" and job.get("interrupted")):
            # Back to the queue, ahead of the rest (see Store.next_queued_job).
            self.store.update_job(job_id, status="queued", paused_at=None, error=None,
                                  finished_at=None)
            self.paused = False
        else:
            return False
        self.on_update()
        return True

    def stop_for_shutdown(self) -> None:
        """BlendQueue is closing: stop the render and leave it queued to resume next time."""
        self.paused = True                      # nothing new may start on the way down
        with self._lock:
            jid = self.current_job_id
            if jid and self._proc is not None:
                self._stops[jid] = STOP_SHUTDOWN
                self._kill(self._proc)

    def retry(self, job_id: str) -> bool:
        job = self.store.get_job(job_id)
        if not job or job.get("status") == "running":
            return False
        self._cancel_ids.discard(job_id)
        self.store.update_job(job_id, status="queued", error=None, note=None, progress={},
                              outputs=[], preview={}, render_info=None, started_at=None,
                              finished_at=None, duration_s=None, paused_at=None, paused_s=None,
                              resume_from=None, resumed_from=None, interrupted=False,
                              render_s=None, timing=None, segment_started_at=None)
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
        return {"paused": self.paused, "current_job_id": self.current_job_id,
                "render_paused": self._paused_since is not None}

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
        """Renders a job, or the rest of it when it stopped midway before."""
        jid = job["id"]
        self.current_job_id = jid
        self.current_tail.clear()
        self._paused_since, self._paused_total, self._clock = None, 0.0, None
        self._current_is_movie = False
        seg_started = time.time()
        resuming = job.get("resume_from") is not None or bool(job.get("interrupted"))
        fields = dict(status="running", error=None, note=None, paused_at=None, paused_s=None,
                      finished_at=None, segment_started_at=seg_started)
        if not resuming:
            fields.update(started_at=seg_started, render_info=None, outputs=[], resumed_from=None,
                          render_s=None, timing=None,
                          progress={"percent": 0.0, "frame": None, "message": "starting Blender…"})
        self.store.update_job(jid, **fields)
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
            step = max(1, int((scene_report or {}).get("frame_step") or 1))
            movie = renderer.effective_is_movie(job, scene_report)
            self._current_is_movie = movie
            log_path = config.LOGS_DIR / f"job_{jid}.log"

            # Where this stretch starts, and what earlier stretches already wrote.
            resume_from = job.get("resume_from")
            prev_outputs = list(job.get("outputs") or []) if resuming else []
            timing = (job.get("timing") or {}) if resuming else {}
            render_prev = float(job.get("render_s") or 0) if resuming else 0.0
            note = None
            if resuming and movie:
                resume_from, prev_outputs, timing, render_prev = None, [], {}, 0.0
                note = "A video cannot continue mid-file: it is rendered again from the start."
            elif job.get("interrupted") and resume_from is None:
                resume_from, prev_outputs = self._resume_point(log_path, step)
            seg_start = resume_from if resume_from is not None else fstart
            if resuming and not movie:
                self._drop_unconfirmed(job, scene_report, seg_start, fend, prev_outputs, log_path)
            self.store.update_job(jid, interrupted=False, resume_from=None, note=note,
                                  resumed_from=seg_start if seg_start != fstart else None)

            renderer.ensure_output_dir(job, scene_report)
            script_path = renderer.write_job_script(job, config.SCRIPTS_DIR / f"job_{jid}.py")
            parser = renderer.ProgressParser(fstart, fend)
            clock = renderer.FrameClock(movie=movie, done=int(timing.get("done") or 0),
                                        total=float(timing.get("total") or 0))
            self._clock = clock
            new_outputs, last_saved, rc = [], None, 0
            seg_offset = 0

            if seg_start <= fend:
                append = resuming and log_path.exists()
                seg_offset = log_path.stat().st_size if append else 0
                cmd = renderer.build_cmd(blender, dict(job, frames={"start": seg_start, "end": fend}),
                                         scene_report, script_path)
                with open(log_path, "a" if append else "w", encoding="utf-8",
                          errors="replace") as logf:
                    if append:
                        logf.write("\n[blendqueue] " + (note or f"resuming at frame {seg_start}")
                                   + "\n")
                    logf.write("CMD: " + subprocess.list2cmdline(cmd) + "\n\n")
                    logf.flush()
                    proc = subprocess.Popen(
                        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding="utf-8", errors="replace", bufsize=1,
                        **system.popen_kwargs(),
                    )
                    system.bind_to_app(proc)
                    with self._lock:
                        self._proc = proc
                    self.store.update_job(jid, pid=proc.pid, pid_birth=system.process_birth(proc.pid))
                    last_push = 0.0
                    for line in proc.stdout:
                        line = line.rstrip("\r\n")
                        if not line:
                            continue
                        logf.write(line + "\n")
                        if not renderer.is_noise(line):
                            self.current_tail.append(line)
                        changed = parser.feed(line)
                        m = renderer.SAVED_RE.search(line)
                        if m:
                            new_outputs.append(m.group(1))
                            last_saved = parser.frame
                            clock.saved(time.time())
                            # The log is how a render killed with the app resumes:
                            # every confirmed frame must be on disk before the next.
                            logf.flush()
                        info = renderer.parse_render_info(line)
                        if info:
                            self.store.update_job(jid, render_info=info)
                            self.on_update()
                        if changed:
                            nowt = time.time()
                            clock.frame(parser.frame, nowt)
                            if nowt - last_push > 0.35:
                                last_push = nowt
                                self._push_progress(jid, parser, seg_started, render_prev,
                                                    fend, total, clock)
                    rc = proc.wait()
                    clock.finish(time.time())
                    with self._lock:
                        self._proc = None

            stop = self._stops.pop(jid, None)
            canceled = jid in self._cancel_ids
            self._cancel_ids.discard(jid)
            render_s = render_prev + (time.time() - seg_started - self._paused_seconds())
            outputs = prev_outputs + new_outputs
            common = dict(pid=None, pid_birth=None, outputs=outputs, render_s=round(render_s, 1),
                          timing={"done": clock.done, "total": round(clock.total, 3)})

            if stop and not canceled:
                # Stopped on purpose: it continues right after the last frame saved.
                nxt = (last_saved + step) if last_saved is not None else seg_start
                paused = stop == STOP_PAUSE
                progress = dict((self.store.get_job(jid) or {}).get("progress") or {})
                if last_saved is not None and not movie:
                    # The last push is throttled: show where it really stands.
                    progress.update(frame=last_saved, percent=round((last_saved - fstart + 1) / total, 4),
                                    elapsed_s=round(render_s, 1), frames_done=clock.done)
                self.store.update_job(
                    jid, status="paused" if paused else "queued",
                    paused_at=time.time() if paused else None, progress=progress,
                    resume_from=None if movie else nxt, interrupted=movie, **common)
                return
            if canceled:
                self.store.update_job(jid, status="canceled", finished_at=time.time(),
                                      duration_s=round(render_s, 1), **common)
                return
            if rc != 0:
                tail = self._error_tail(log_path, seg_offset)
                self.store.update_job(jid, status="error", finished_at=time.time(),
                                      duration_s=round(render_s, 1),
                                      error=f"Blender exited with code {rc}. {tail}", **common)
                self._notify(settings, "Render failed", self._label(job))
                return

            if not new_outputs and movie and seg_start <= fend:
                # Only movies stay silent: image sequences always print
                # "Saved:", so no line means nothing was written. Scanning
                # the folder there would pick up a previous render's files.
                new_outputs = self._scan_outputs(job, scene_report, seg_started)
                outputs = prev_outputs + new_outputs
                common["outputs"] = outputs
            failure = None
            if not outputs:
                failure, note = self._why_nothing(log_path, parser.frame is not None, seg_offset)
            if failure:
                self.store.update_job(jid, status="error", finished_at=time.time(),
                                      duration_s=round(render_s, 1), error=failure, **common)
                self._notify(settings, "Render failed", self._label(job))
                return
            preview = self._build_preview(jid, job, scene_report, outputs, log_path, settings)
            if note:
                preview["note"] = note
            self.store.update_job(jid, status="done", finished_at=time.time(),
                                  duration_s=round(render_s, 1), preview=preview, note=note,
                                  progress={"percent": 1.0, "frame": fend,
                                            "message": "completed",
                                            "frames_done": clock.done,
                                            "last_frame_s": clock.last,
                                            "avg_frame_s": clock.average},
                                  **common)
            self._notify(settings, "Render finished",
                         self._label(job) + f" · {fend - fstart + 1} frame(s)")
        except Exception as exc:
            self.store.update_job(jid, status="error", finished_at=time.time(), error=str(exc),
                                  pid=None, pid_birth=None)
            self._notify(settings, "Render failed", self._label(job) + " · " + str(exc))
        finally:
            # A render cancelled while suspended ends here too: never leave it marked paused.
            with self._lock:
                was_suspended = self._paused_since is not None
                self._paused_since, self._clock = None, None
                self._stops.pop(jid, None)
                self.current_job_id = None
            if was_suspended:
                self.store.update_job(jid, paused_at=None)
            self.on_update()

    # ---------------- helpers ----------------
    def _build_preview(self, jid, job, scene_report, outputs, log_path, settings) -> dict:
        preview = {}
        if not settings.get("preview_video", True):
            return preview
        dest = str(config.PREVIEWS_DIR / f"{jid}.mp4")
        log_fn = lambda msg: self._append_log(log_path, msg)
        blocked = renderer.preview_block_reason(renderer.effective_format(job, scene_report))
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
        return preview

    @staticmethod
    def _resume_point(log_path, step: int) -> tuple:
        """(next frame, outputs) of a render that stopped without saying so (the app died)."""
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None, []
        saved = renderer.saved_frames(text)
        if not saved:
            return None, []
        outputs, seen = [], set()
        for _, path in saved:
            key = os.path.normcase(os.path.abspath(path))
            if key not in seen and os.path.exists(path):
                seen.add(key)
                outputs.append(path)
        return max(frame for frame, _ in saved) + step, outputs

    def _drop_unconfirmed(self, job, scene_report, seg_start, fend, confirmed, log_path) -> None:
        """Deletes the image that was being written when the render stopped.

        Blender writes the file in place, so a render stopped mid-write leaves it
        cut short, and with Overwrite off the resumed render would keep it. Only
        a file this job wrote during its last run without a "Saved:" line
        qualifies, and only the newest one.
        """
        since = job.get("segment_started_at") or job.get("started_at")
        if not since:
            return
        folder, _, _ = renderer.output_target(job, scene_report)
        known = {os.path.normcase(os.path.abspath(p)) for p in confirmed}
        found = []
        for name in renderer.existing_outputs(job, scene_report, {"start": seg_start, "end": fend}):
            path = os.path.join(folder, name)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if mtime >= since - 1 and os.path.normcase(os.path.abspath(path)) not in known:
                found.append((mtime, path))
        if found:
            newest = max(found)[1]
            try:
                os.remove(newest)
                self._append_log(log_path, f"removed {os.path.basename(newest)}: it was being "
                                           "written when the render stopped")
            except OSError:
                pass

    def _label(self, job: dict) -> str:
        return f"{job.get('file_name')} · {job.get('scene')}"

    def _notify(self, settings: dict, title: str, message: str) -> None:
        if settings.get("notifications", True):
            try:
                notifier.notify(title, message)
            except Exception:
                pass

    def _paused_seconds(self) -> float:
        """Time the current render spent suspended, including a pause still going on."""
        with self._lock:
            ongoing = time.time() - self._paused_since if self._paused_since else 0.0
            return self._paused_total + ongoing

    def _push_progress(self, jid: str, parser, seg_started: float, render_prev: float,
                       fend: int, total: int, clock=None) -> None:
        elapsed = render_prev + time.time() - seg_started - self._paused_seconds()
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
    def _read_segment(log_path, offset: int) -> str:
        """The log of this run only: a resumed job's log holds every earlier run too."""
        try:
            with open(log_path, "rb") as fh:
                fh.seek(offset)       # a byte offset, hence the binary read
                return fh.read().decode("utf-8", errors="replace").replace("\r\n", "\n")
        except OSError:
            return ""

    @classmethod
    def _why_nothing(cls, log_path, rendered_a_frame: bool, offset: int = 0) -> tuple:
        """(error, note) for a render that exited with code 0 but wrote no file.

        Skipping frames that are already on disk (Overwrite off) is a legitimate
        outcome and only earns a note. Anything else is a failure: Blender
        reports some errors -- a video encoder that cannot start, for one -- and
        still exits with 0, which used to end as "done" with nothing on disk.
        """
        data = cls._read_segment(log_path, offset)
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

    @classmethod
    def _error_tail(cls, log_path, offset: int = 0, limit: int = 800) -> str:
        data = cls._read_segment(log_path, offset)
        if not data:
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
