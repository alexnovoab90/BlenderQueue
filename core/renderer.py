"""Comandos, parseo de progreso y previews de video para los renders de Blender."""
from __future__ import annotations

import os
import re
import subprocess

from . import config

FRA_RE = re.compile(r"Fra:(\d+)")
SAMPLE_RE = re.compile(r"Sample (\d+)/(\d+)")
TIME_RE = re.compile(r"Time: *([0-9:.]+)")
REMAIN_RE = re.compile(r"Remaining: *([0-9:.]+)")
SAVED_RE = re.compile(r"Saved: *'([^']+)'")
NOISE_RE = re.compile(r"blendkit|zozo|Registered|Read prefs|Reading prefs", re.I)


def is_noise(line: str) -> bool:
    return bool(NOISE_RE.search(line))


def sanitize(name: str) -> str:
    out = "".join(c if (c.isalnum() or c in "-_ .") else "_" for c in name)
    out = out.strip().strip(".")
    return out or "salida"


def resolve_relative(raw: str, blend_path: str) -> str:
    """Resuelve rutas '//...' de Blender contra la carpeta del .blend."""
    if raw.startswith("//"):
        return os.path.normpath(os.path.join(os.path.dirname(blend_path), raw[2:]))
    return raw


def output_pattern(job: dict, scene_report: dict | None) -> str | None:
    """Patrón -o para Blender.

    Sin override: se respeta tal cual la salida guardada en el .blend.
    Con override: carpeta elegida + '<blend>_<escena>_####'.
    """
    ov = job.get("overrides") or {}
    out_dir = (ov.get("output_dir") or "").strip()
    raw = ((scene_report or {}).get("filepath_raw") or "").strip()
    if not out_dir:
        return raw or None
    out_dir = os.path.abspath(out_dir)
    stem = sanitize(os.path.splitext(os.path.basename(job["file_path"]))[0])
    if (scene_report or {}).get("is_movie"):
        return os.path.join(out_dir, f"{stem}_{sanitize(job['scene'])}")
    return os.path.join(out_dir, f"{stem}_{sanitize(job['scene'])}_####")


def _device_code(device: str) -> str:
    if device == "GPU":
        return "\n".join([
            "try:",
            "    sc.cycles.device = 'GPU'",
            "except Exception:",
            "    pass",
            "try:",
            "    _pr = bpy.context.preferences.addons['cycles'].preferences",
            "    try:",
            "        _pr.compute_device_type = 'OPTIX'",
            "    except Exception:",
            "        _pr.compute_device_type = 'CUDA'",
            "    _pr.get_devices()",
            "    for _d in _pr.devices:",
            "        if _d.type != 'CPU':",
            "            _d.use = True",
            "except Exception:",
            "    pass",
        ])
    if device == "CPU":
        return "try:\n    sc.cycles.device = 'CPU'\nexcept Exception:\n    pass"
    return ""


def override_expr(job: dict) -> str | None:
    ov = job.get("overrides") or {}
    lines = ["import bpy",
             f"sc = bpy.data.scenes.get({job['scene']!r}) or bpy.context.scene"]
    if ov.get("engine"):
        lines.append(f"sc.render.engine = {ov['engine']!r}")
    if ov.get("samples"):
        n = int(ov["samples"])
        lines += [
            "try:",
            f"    if sc.render.engine == 'CYCLES': sc.cycles.samples = {n}",
            f"    else: sc.eevee.taa_render_samples = {n}",
            "except Exception:",
            "    pass",
        ]
    if ov.get("resolution_percentage"):
        lines.append(f"sc.render.resolution_percentage = {int(ov['resolution_percentage'])}")
    if ov.get("device"):
        code = _device_code(ov["device"])
        if code:
            lines.append(code)
    return "\n".join(lines) if len(lines) > 2 else None


def build_cmd(blender: str, job: dict, scene_report: dict | None) -> list:
    args = [blender, "-b", job["file_path"], "-S", job["scene"]]
    expr = override_expr(job)
    if expr:
        args += ["--python-expr", expr]
    pat = output_pattern(job, scene_report)
    if pat:
        args += ["-o", pat]
    fr = job.get("frames") or {}
    if fr.get("start") is not None:
        args += ["-s", str(int(fr["start"]))]
    if fr.get("end") is not None:
        args += ["-e", str(int(fr["end"]))]
    args.append("-a")
    return args


def ensure_output_dir(job: dict, scene_report: dict | None) -> None:
    """Crea la carpeta de salida si no existe (override local o la del .blend)."""
    ov = job.get("overrides") or {}
    out_dir = (ov.get("output_dir") or "").strip()
    if out_dir:
        folder = os.path.abspath(out_dir)
    else:
        raw = ((scene_report or {}).get("filepath_raw") or "").strip()
        if not raw:
            return
        resolved = resolve_relative(raw, job["file_path"])
        folder = resolved if resolved.endswith(("/", "\\")) else os.path.dirname(resolved)
    if folder:
        try:
            os.makedirs(folder, exist_ok=True)
        except Exception:
            pass


class ProgressParser:
    def __init__(self, frame_start: int, frame_end: int):
        self.start = frame_start
        self.end = frame_end
        self.total = max(1, frame_end - frame_start + 1)
        self.frame = None
        self.sample = None
        self.sample_total = None
        self.remaining_text = None
        self.blender_time = None
        self.percent = 0.0

    def feed(self, line: str) -> bool:
        changed = False
        m = FRA_RE.search(line)
        if m:
            f = int(m.group(1))
            if f != self.frame:
                self.frame = f
                self.sample = None
                changed = True
        m = SAMPLE_RE.search(line)
        if m:
            self.sample = int(m.group(1))
            self.sample_total = int(m.group(2))
            changed = True
        m = TIME_RE.search(line)
        if m:
            self.blender_time = m.group(1)
        m = REMAIN_RE.search(line)
        if m:
            self.remaining_text = m.group(1)
            changed = True
        if self.frame is not None:
            done = max(0, min(self.frame - self.start, self.total - 1))
            sub = 0.0
            if self.sample and self.sample_total:
                sub = min(1.0, self.sample / self.sample_total)
            self.percent = max(0.0, min(0.999, (done + sub) / self.total))
        return changed


VIDEO_EXTS = (".mkv", ".mp4", ".mov", ".avi", ".webm")


def remux_preview(src: str, dest: str, log=print) -> str | None:
    """Convierte la película renderizada (mkv/avi/...) en un MP4 reproducible en el navegador."""
    ff = config.ffmpeg_path()
    if not ff or not os.path.exists(src):
        return None
    args = [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", src,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-c:a", "aac", "-b:a", "160k", dest]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=1800,
                              creationflags=config.CREATE_NO_WINDOW)
    except Exception as exc:
        log(f"ffmpeg (película) falló: {exc}")
        return None
    if proc.returncode != 0 or not os.path.exists(dest):
        log("ffmpeg (película) código " + str(proc.returncode) + " " + (proc.stderr or "")[-400:])
        return None
    return dest


def build_preview_video(outputs: list, fps: float, dest: str, log=print) -> str | None:
    """Arma un MP4 de preview a partir de la secuencia renderizada (ffmpeg)."""
    ff = config.ffmpeg_path()
    if not ff:
        log("ffmpeg no disponible: se omite el video de preview")
        return None
    files = [p for p in outputs if isinstance(p, str) and os.path.exists(p)]
    if len(files) < 2:
        return None
    fps_i = max(1, int(round(fps or 24)))

    pattern = None
    start_number = 1
    m0 = re.search(r"(\d+)(\.[A-Za-z0-9]+)$", files[0])
    if m0:
        prefix = files[0][:m0.start(1)]
        num = m0.group(1)
        ext = m0.group(2)
        ok = True
        for i, p in enumerate(files):
            expected = f"{prefix}{int(num) + i:0{len(num)}d}{ext}"
            if os.path.normcase(p) != os.path.normcase(expected):
                ok = False
                break
        if ok:
            pattern = f"{prefix}%0{len(num)}d{ext}"
            start_number = int(num)

    args = [ff, "-y", "-hide_banner", "-loglevel", "error"]
    listfile = None
    if pattern:
        args += ["-framerate", str(fps_i), "-start_number", str(start_number), "-i", pattern]
    else:
        listfile = dest + ".txt"
        dur = 1.0 / fps_i
        with open(listfile, "w", encoding="utf-8") as fh:
            for p in files:
                fh.write("file '" + p.replace("\\", "/") + f"'\nduration {dur:.6f}\n")
            fh.write("file '" + files[-1].replace("\\", "/") + "'\n")
        args += ["-f", "concat", "-safe", "0", "-i", listfile]
    args += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", dest]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=1800,
                              creationflags=config.CREATE_NO_WINDOW)
        if proc.returncode != 0 or not os.path.exists(dest):
            log("ffmpeg código " + str(proc.returncode) + " " + (proc.stderr or "")[-500:])
            return None
        return dest
    except Exception as exc:
        log(f"ffmpeg falló: {exc}")
        return None
    finally:
        if listfile and os.path.exists(listfile):
            try:
                os.remove(listfile)
            except Exception:
                pass
