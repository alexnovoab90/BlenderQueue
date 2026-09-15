"""Comandos, parseo de progreso y previews de video para los renders de Blender."""
from __future__ import annotations

import os
import re
import subprocess

from . import config, formats

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
    return out or "output"


def resolve_relative(raw: str, blend_path: str) -> str:
    """Resuelve rutas '//...' de Blender contra la carpeta del .blend."""
    if raw.startswith("//"):
        return os.path.normpath(os.path.join(os.path.dirname(blend_path), raw[2:]))
    return raw


def effective_format(job: dict, scene_report: dict | None) -> str | None:
    """Formato con el que se va a escribir: el override si existe, si no el del .blend."""
    ov = job.get("overrides") or {}
    return ov.get("format") or (scene_report or {}).get("file_format")


def effective_is_movie(job: dict, scene_report: dict | None) -> bool:
    fmt = effective_format(job, scene_report)
    if fmt:
        return formats.is_movie(fmt)
    return bool((scene_report or {}).get("is_movie"))


def expected_extension(job: dict, scene_report: dict | None) -> str | None:
    """Extensión esperada de los archivos de salida (para localizarlos después)."""
    ov = job.get("overrides") or {}
    fmt = effective_format(job, scene_report)
    container = ov.get("ffmpeg_container") or (scene_report or {}).get("ffmpeg_container")
    return formats.extension(fmt, container)


def output_stem(job: dict) -> str:
    blend = sanitize(os.path.splitext(os.path.basename(job["file_path"]))[0])
    return f"{blend}_{sanitize(job['scene'])}"


def output_pattern(job: dict, scene_report: dict | None) -> str | None:
    """Patrón -o para Blender.

    Sin override de carpeta: se respeta tal cual la salida guardada en el .blend.
    Con override: carpeta elegida + '<blend>_<escena>_####' (sin '####' si la
    salida es una película, porque Blender escribe un único archivo).
    """
    ov = job.get("overrides") or {}
    out_dir = (ov.get("output_dir") or "").strip()
    raw = ((scene_report or {}).get("filepath_raw") or "").strip()
    if not out_dir:
        return raw or None
    out_dir = os.path.abspath(out_dir)
    stem = output_stem(job)
    if effective_is_movie(job, scene_report):
        return os.path.join(out_dir, stem)
    return os.path.join(out_dir, f"{stem}_####")


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


def _guard(stmt: str, what: str) -> list:
    """Envuelve una asignación para que un valor no soportado no tumbe el render."""
    return ["try:",
            "    " + stmt,
            "except Exception as _e:",
            f"    print('[blendqueue] could not apply {what}:', _e)"]


def format_code(ov: dict) -> list:
    """Líneas Python que aplican el override de formato de salida en Blender."""
    fmt = ov.get("format")
    if not fmt:
        return []
    spec = formats.spec(fmt) or {}
    lines = ["_im = sc.render.image_settings"]
    media = spec.get("media")
    if media:
        # Blender 5 filtra file_format según media_type; en 4.x este atributo no existe.
        lines += ["try:",
                  "    if hasattr(_im, 'media_type'):",
                  f"        _im.media_type = {media!r}",
                  "except Exception:",
                  "    pass"]
    lines += _guard(f"_im.file_format = {fmt!r}", f"format {fmt}")
    # Con formato forzado la extensión la pone Blender, si no el archivo miente.
    lines += _guard("sc.render.use_file_extension = True", "use_file_extension")
    if ov.get("color_mode"):
        lines += _guard(f"_im.color_mode = {ov['color_mode']!r}", "color mode")
    if ov.get("color_depth"):
        lines += _guard(f"_im.color_depth = {str(ov['color_depth'])!r}", "color depth")
    if ov.get("exr_codec"):
        lines += _guard(f"_im.exr_codec = {ov['exr_codec']!r}", "EXR codec")
    if ov.get("quality") is not None:
        attr = "compression" if spec.get("quality_kind") == "compression" else "quality"
        lines += _guard(f"_im.{attr} = {int(ov['quality'])}", "quality/compression")
    if spec.get("ffmpeg"):
        if ov.get("ffmpeg_container"):
            lines += _guard(f"sc.render.ffmpeg.format = {ov['ffmpeg_container']!r}", "container")
        if ov.get("ffmpeg_codec"):
            lines += _guard(f"sc.render.ffmpeg.codec = {ov['ffmpeg_codec']!r}", "video codec")
    lines.append("print('[blendqueue] output format:', _im.file_format, _im.color_mode, "
                 "getattr(_im, 'color_depth', ''))")
    return lines


def engine_code(engine: str) -> list:
    """Cambia el motor tolerando el rename de EEVEE entre versiones de Blender."""
    alt = {"BLENDER_EEVEE": "BLENDER_EEVEE_NEXT",
           "BLENDER_EEVEE_NEXT": "BLENDER_EEVEE"}.get(engine)
    lines = ["try:", f"    sc.render.engine = {engine!r}", "except Exception as _e:"]
    if alt:
        lines += ["    try:",
                  f"        sc.render.engine = {alt!r}",
                  "    except Exception as _e2:",
                  "        print('[blendqueue] engine not available:', _e2)"]
    else:
        lines.append("    print('[blendqueue] engine not available:', _e)")
    return lines


def override_expr(job: dict) -> str | None:
    ov = job.get("overrides") or {}
    lines = ["import bpy",
             f"sc = bpy.data.scenes.get({job['scene']!r}) or bpy.context.scene"]
    if ov.get("engine"):
        lines += engine_code(str(ov["engine"]))
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
        lines += _guard(f"sc.render.resolution_percentage = {int(ov['resolution_percentage'])}",
                        "resolution")
    if ov.get("device"):
        code = _device_code(ov["device"])
        if code:
            lines.append(code)
    lines += format_code(ov)
    return "\n".join(lines) if len(lines) > 2 else None


SCRIPT_HEADER = """# Generated by BlendQueue: this is the file Blender runs for this job.
# Your code starts below and gets bpy, sc (this job's scene) and blend_path.
import bpy

sc = bpy.data.scenes.get({scene!r}) or bpy.context.scene
blend_path = bpy.data.filepath
print("[blendqueue] script:", {name!r})

# --- your script ---
"""


def write_job_script(job: dict, dest) -> str | None:
    """Escribe el script del trabajo a un .py que Blender ejecuta con --python.

    Va en un archivo aparte y no dentro de --python-expr para que el codigo del
    usuario no dependa de como se escapa la linea de comandos (acentos, comillas,
    saltos) y para que el traceback apunte a lineas reales.
    """
    code = (job.get("overrides") or {}).get("script") or ""
    if not code.strip():
        return None
    header = SCRIPT_HEADER.format(scene=job.get("scene") or "",
                                  name=(job.get("overrides") or {}).get("script_name") or "untitled")
    dest = str(dest)
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(header + code.rstrip() + "\nprint('[blendqueue] script ok')\n")
    return dest


def build_cmd(blender: str, job: dict, scene_report: dict | None,
              script_path: str | None = None) -> list:
    args = [blender, "-b", job["file_path"], "-S", job["scene"]]
    if script_path:
        # Sin esto Blender imprime el traceback y renderiza igual: el trabajo debe fallar.
        args += ["--python-exit-code", "1"]
    expr = override_expr(job)
    if expr:
        args += ["--python-expr", expr]
    if script_path:
        # Despues de los overrides: el script del usuario puede pisar cualquiera.
        args += ["--python", script_path]
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


# Extensiones que Blender puede producir como película (contenedores FFmpeg + AVI).
VIDEO_EXTS = tuple(sorted({c["ext"] for c in formats.FFMPEG_CONTAINERS} | {".avi"}))

# Formatos que el navegador no sabe mostrar en un <img>: el preview se arma con ffmpeg.
HDR_EXTS = (".exr", ".hdr", ".dpx", ".cin")

# Formatos que ffmpeg no puede leer: se avisa en vez de intentarlo y fallar.
NO_PREVIEW = {"OPEN_EXR_MULTILAYER": "ffmpeg cannot read multilayer EXR"}


def preview_block_reason(fmt: str | None) -> str | None:
    return NO_PREVIEW.get(fmt or "")


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
        log(f"ffmpeg (movie) failed: {exc}")
        return None
    if proc.returncode != 0 or not os.path.exists(dest):
        log("ffmpeg (movie) exit " + str(proc.returncode) + " " + (proc.stderr or "")[-400:])
        return None
    return dest


def build_preview_video(outputs: list, fps: float, dest: str, log=print) -> str | None:
    """Arma un MP4 de preview a partir de la secuencia renderizada (ffmpeg)."""
    ff = config.ffmpeg_path()
    if not ff:
        log("ffmpeg not available: skipping the preview video")
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

    listfile = None
    if pattern:
        input_args = ["-framerate", str(fps_i), "-start_number", str(start_number), "-i", pattern]
    else:
        listfile = dest + ".txt"
        dur = 1.0 / fps_i
        with open(listfile, "w", encoding="utf-8") as fh:
            for p in files:
                fh.write("file '" + p.replace("\\", "/") + f"'\nduration {dur:.6f}\n")
            fh.write("file '" + files[-1].replace("\\", "/") + "'\n")
        input_args = ["-f", "concat", "-safe", "0", "-i", listfile]
    out_args = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", dest]

    # EXR guarda color lineal: sin la conversión el preview sale lavado. Si el
    # ffmpeg instalado no acepta la opción, se reintenta sin ella.
    attempts = [[]]
    if os.path.splitext(files[0])[1].lower() == ".exr":
        attempts.insert(0, ["-apply_trc", "iec61966_2_1"])
    try:
        for extra in attempts:
            args = [ff, "-y", "-hide_banner", "-loglevel", "error"] + extra + input_args + out_args
            try:
                proc = subprocess.run(args, capture_output=True, text=True, timeout=1800,
                                      creationflags=config.CREATE_NO_WINDOW)
            except Exception as exc:
                log(f"ffmpeg failed: {exc}")
                return None
            if proc.returncode == 0 and os.path.exists(dest):
                return dest
            log("ffmpeg exit " + str(proc.returncode) + " " + (proc.stderr or "")[-500:])
        return None
    finally:
        if listfile and os.path.exists(listfile):
            try:
                os.remove(listfile)
            except Exception:
                pass
