"""Carrera de inspección: corre Blender headless para leer metadatos de cada .blend."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time

from . import config


class InspectorLane:
    def __init__(self, store, on_update=None):
        self.store = store
        self.on_update = on_update or (lambda: None)
        self.q: "queue.Queue[str]" = queue.Queue()
        self.current_file_id = None
        self._thread = threading.Thread(target=self._loop, name="inspector-lane", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def request(self, file_id: str) -> None:
        if not self.store.get_file(file_id):
            return
        self.store.update_file(file_id, status="pending", inspect_error=None)
        self.q.put(file_id)
        self.on_update()

    def _loop(self) -> None:
        while True:
            fid = self.q.get()
            try:
                self._run(fid)
            except Exception as exc:
                self.store.update_file(fid, status="error", inspect_error=str(exc))
            finally:
                self.current_file_id = None
                self.on_update()

    def status(self) -> dict:
        return {"current_file_id": self.current_file_id}

    def _blender(self) -> str | None:
        settings = self.store.settings()
        info = config.blender_info((settings.get("blender_path") or "").strip() or None)
        return info.get("path") if info.get("ok") else None

    def _run(self, fid: str) -> None:
        rec = self.store.get_file(fid)
        if not rec:
            return
        self.current_file_id = fid
        self.store.update_file(fid, status="inspecting", inspect_error=None)
        self.on_update()

        if not os.path.exists(rec["path"]):
            raise RuntimeError("El archivo ya no existe en disco.")

        blender = self._blender()
        if not blender:
            raise RuntimeError("No se encontró blender.exe. Configura la ruta en Ajustes.")

        script = config.BLENDER_SIDE_DIR / "inspect_blend.py"
        out_json = config.INSPECT_DIR / f"{fid}.json"
        log_path = config.LOGS_DIR / f"inspect_{fid}.log"
        if out_json.exists():
            out_json.unlink()

        cmd = [blender, "-b", rec["path"], "--python", str(script), "--", str(out_json)]
        started = time.time()
        with open(log_path, "w", encoding="utf-8", errors="replace") as logf:
            logf.write("CMD: " + subprocess.list2cmdline(cmd) + "\n\n")
            logf.flush()
            proc = subprocess.run(cmd, stdout=logf, stderr=subprocess.STDOUT, timeout=1800,
                                  creationflags=config.CREATE_NO_WINDOW)
        dur = time.time() - started

        if not out_json.exists():
            raise RuntimeError(
                f"Blender no generó el reporte (código {proc.returncode}). "
                f"Revisa data/logs/{log_path.name}")
        with open(out_json, "r", encoding="utf-8") as fh:
            report = json.load(fh)
        if not report.get("ok", False):
            raise RuntimeError("Inspección falló: " + str(report.get("error")))
        report["inspect_seconds"] = round(dur, 1)

        fields = {"status": "ready", "report": report, "inspected_at": time.time(),
                  "inspect_error": None}
        try:
            fields["size"] = os.path.getsize(rec["path"])
            fields["mtime"] = os.path.getmtime(rec["path"])
        except OSError:
            pass
        self.store.update_file(fid, **fields)
