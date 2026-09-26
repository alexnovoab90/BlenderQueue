"""Command building, progress parsing and video previews for Blender renders."""
from __future__ import annotations

import os
import re
import subprocess

from . import config, formats, system

# Blender 4.2+ logs "Fra: 12 | Rendering 5 / 64 samples" and "Rendering frame 12";
# older builds print "Fra:12 Mem:... | Sample 5/64".
FRA_RE = re.compile(r"Fra:\s*(\d+)|Rendering frame (\d+)")
SAMPLE_RE = re.compile(r"Sample (\d+)/(\d+)|Rendering (\d+) / (\d+) samples")
TIME_RE = re.compile(r"Time: *([0-9:.]+)")
REMAIN_RE = re.compile(r"Remaining: *([0-9:.]+)")
SAVED_RE = re.compile(r"Saved: *'([^']+)'")
NOISE_RE = re.compile(r"blendkit|zozo|Registered|Read prefs|Reading prefs", re.I)
# "00:02.781  video.write | ERROR Couldn't initialize..." (4.2+) or "Error: ..." (older).
ERROR_RE = re.compile(r"\|\s*ERROR\s+(.+)$|^(?:Error|ERROR):?\s+(.+)$")
ERROR_NOISE_RE = re.compile(r"Not freed memory|unfreed memory", re.I)
RENDER_INFO_RE = re.compile(
    r"\[blendqueue\] render: engine=(\S+) samples=(\S+) size=(\d+)x(\d+) format=(\S+)")


def is_noise(line: str) -> bool:
    return bool(NOISE_RE.search(line))


def blender_errors(log_text: str) -> list:
    """Error lines Blender printed while rendering, in order, without repeats.

    Only Blender's output counts: the log starts with the command line, whose
    generated Python mentions errors of its own.
    """
    body = log_text.split("\n\n", 1)[1] if log_text.startswith("CMD:") else log_text
    out = []
    for line in body.splitlines():
        m = ERROR_RE.search(line.strip())
        if not m:
            continue
        msg = (m.group(1) or m.group(2) or "").strip()
        if msg and not ERROR_NOISE_RE.search(msg) and msg not in out:
            out.append(msg)
    return out


def parse_render_info(line: str) -> dict | None:
    """What Blender is about to render with, from the line final_expr() prints."""
    m = RENDER_INFO_RE.search(line)
    if not m:
        return None
    return {"engine": m.group(1), "samples": m.group(2), "width": int(m.group(3)),
            "height": int(m.group(4)), "format": m.group(5)}


def sanitize(name: str) -> str:
    out = "".join(c if (c.isalnum() or c in "-_ .") else "_" for c in name)
    out = out.strip().strip(".")
    return out or "output"


def resolve_relative(raw: str, blend_path: str) -> str:
    """Resolves Blender's '//...' paths against the .blend's folder."""
    if raw.startswith("//"):
        return os.path.normpath(os.path.join(os.path.dirname(blend_path), raw[2:]))
    return raw


def effective_format(job: dict, scene_report: dict | None) -> str | None:
    """Format the job will write with: the override if set, else the .blend's own."""
    ov = job.get("overrides") or {}
    return ov.get("format") or (scene_report or {}).get("file_format")


def effective_is_movie(job: dict, scene_report: dict | None) -> bool:
    fmt = effective_format(job, scene_report)
    if fmt:
        return formats.is_movie(fmt)
    return bool((scene_report or {}).get("is_movie"))


def expected_extension(job: dict, scene_report: dict | None) -> str | None:
    """Expected extension of the output files (used to find them afterwards)."""
    ov = job.get("overrides") or {}
    fmt = effective_format(job, scene_report)
    container = ov.get("ffmpeg_container") or (scene_report or {}).get("ffmpeg_container")
    return formats.extension(fmt, container)


def output_stem(job: dict) -> str:
    blend = sanitize(os.path.splitext(os.path.basename(job["file_path"]))[0])
    return f"{blend}_{sanitize(job['scene'])}"


def output_target(job: dict, scene_report: dict | None) -> tuple:
    """(folder, prefix, extension) this job would write into.

    Blender names frames `<filepath><number>.<ext>`, so the filepath's tail is a
    prefix, not a folder, unless it ends with a separator.
    """
    pattern = output_pattern(job, scene_report) or ""
    # A trailing separator means "write into this folder", but normpath in
    # resolve_relative drops it, so remember it before resolving.
    is_folder = pattern.endswith(("/", "\\"))
    if pattern.startswith("//"):
        pattern = resolve_relative(pattern, job["file_path"])
    pattern = pattern.replace("####", "")
    if is_folder or pattern.endswith(("/", "\\")):
        folder, prefix = pattern, ""
    else:
        folder, prefix = os.path.split(pattern)
    ext = (expected_extension(job, scene_report) or "").lower()
    return os.path.abspath(folder) if folder else "", prefix, ext


def existing_outputs(job: dict, scene_report: dict | None, frames: dict | None = None) -> list:
    """Files already on disk that this job is about to write.

    Used before queueing to ask what to do, because Blender either silently
    skips them (Overwrite off) or silently replaces them (Overwrite on).
    """
    folder, prefix, ext = output_target(job, scene_report)
    if not folder or not os.path.isdir(folder):
        return []
    fr = frames or job.get("frames") or {}
    start, end = fr.get("start"), fr.get("end")
    movie = effective_is_movie(job, scene_report)
    hits = []
    try:
        for name in sorted(os.listdir(folder)):
            low = name.lower()
            if prefix and not low.startswith(prefix.lower()):
                continue
            if ext and not low.endswith(ext):
                continue
            if not os.path.isfile(os.path.join(folder, name)):
                continue
            if movie:
                hits.append(name)
                continue
            m = re.search(r"(\d+)(?=\.[A-Za-z0-9]+$)", name)
            if not m:
                continue
            n = int(m.group(1))
            if start is not None and end is not None and not (int(start) <= n <= int(end)):
                continue
            hits.append(name)
    except OSError:
        return []
    return hits


def output_pattern(job: dict, scene_report: dict | None) -> str | None:
    """-o pattern for Blender.

    Without a folder override the output saved in the .blend is used as-is.
    With one: chosen folder + '<blend>_<scene>_####' (no '####' when the output
    is a movie, because Blender writes a single file).
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
    """Wraps an assignment so an unsupported value cannot kill the render."""
    return ["try:",
            "    " + stmt,
            "except Exception as _e:",
            f"    print('[blendqueue] could not apply {what}:', _e)"]


def format_code(ov: dict) -> list:
    """Python lines that apply the output format override inside Blender."""
    fmt = ov.get("format")
    if not fmt:
        return []
    spec = formats.spec(fmt) or {}
    lines = ["_im = sc.render.image_settings"]
    media = spec.get("media")
    if media:
        # Blender 5 filters file_format by media_type; 4.x has no such attribute.
        lines += ["try:",
                  "    if hasattr(_im, 'media_type'):",
                  f"        _im.media_type = {media!r}",
                  "except Exception:",
                  "    pass"]
    lines += _guard(f"_im.file_format = {fmt!r}", f"format {fmt}")
    # With a forced format Blender must add the extension, or the file lies.
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
    """Switches the engine, tolerating the EEVEE rename across Blender versions."""
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


def size_code(ov: dict) -> list:
    """Output size in pixels. The size asked for is the size of the file, so the
    .blend's percentage is reset to 100 unless the job sets its own."""
    rx, ry = ov.get("resolution_x"), ov.get("resolution_y")
    if not rx and not ry:
        return []
    lines = ["try:", "    _r = sc.render"]
    if rx and ry:
        lines.append(f"    _r.resolution_x, _r.resolution_y = {int(rx)}, {int(ry)}")
    elif rx:
        # Only one side given: the other keeps the .blend's aspect ratio
        # (rounded half up, like the size the UI shows).
        lines += [f"    _r.resolution_y = max(4, int(_r.resolution_y * {int(rx)} / _r.resolution_x + 0.5))",
                  f"    _r.resolution_x = {int(rx)}"]
    else:
        lines += [f"    _r.resolution_x = max(4, int(_r.resolution_x * {int(ry)} / _r.resolution_y + 0.5))",
                  f"    _r.resolution_y = {int(ry)}"]
    if not ov.get("resolution_percentage"):
        lines.append("    _r.resolution_percentage = 100")
    lines += ["except Exception as _e:",
              "    print('[blendqueue] could not apply the size:', _e)"]
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
            "except Exception as _e:",
            "    print('[blendqueue] could not apply samples:', _e)",
        ]
    lines += size_code(ov)
    if ov.get("resolution_percentage"):
        lines += _guard(f"sc.render.resolution_percentage = {int(ov['resolution_percentage'])}",
                        "resolution")
    if ov.get("device"):
        code = _device_code(ov["device"])
        if code:
            lines.append(code)
    if ov.get("overwrite") is not None:
        lines += _guard(f"sc.render.use_overwrite = {bool(ov['overwrite'])}", "overwrite")
    lines += format_code(ov)
    return "\n".join(lines) if len(lines) > 2 else None


def final_expr(job: dict) -> str:
    """Runs last, after the overrides and the user's script.

    Video codecs with chroma subsampling (H.264, H.265, MPEG-4...) refuse odd
    sizes, and Blender then exits with code 0 having written nothing: 66% of
    1920x1080 is 1267x712. The size is rounded down to even, one pixel at most.
    It also prints what Blender is about to render with, which is the only
    trustworthy answer to "did my overrides apply?".
    """
    return "\n".join([
        "import bpy",
        f"sc = bpy.data.scenes.get({job['scene']!r}) or bpy.context.scene",
        "_r = sc.render",
        "try:",
        "    _p = _r.resolution_percentage",
        "    _w, _h = _r.resolution_x * _p // 100, _r.resolution_y * _p // 100",
        "    if _r.image_settings.file_format == 'FFMPEG' and (_w % 2 or _h % 2):",
        "        if _r.use_border and _r.use_crop_to_border:",
        "            print('[blendqueue] the cropped video size may be odd:', _w, _h)",
        "        else:",
        "            _r.resolution_x, _r.resolution_y = max(4, _w - _w % 2), max(4, _h - _h % 2)",
        "            _r.resolution_percentage = 100",
        "            print('[blendqueue] video needs an even size: %dx%d rendered as %dx%d'",
        "                  % (_w, _h, _r.resolution_x, _r.resolution_y))",
        "except Exception as _e:",
        "    print('[blendqueue] could not check the video size:', _e)",
        "try:",
        "    _s = (sc.cycles.samples if _r.engine == 'CYCLES' else",
        "          sc.eevee.taa_render_samples if 'EEVEE' in _r.engine else '-')",
        "    print('[blendqueue] render: engine=%s samples=%s size=%dx%d format=%s' % (",
        "        _r.engine, _s, _r.resolution_x * _r.resolution_percentage // 100,",
        "        _r.resolution_y * _r.resolution_percentage // 100, _r.image_settings.file_format))",
        "except Exception as _e:",
        "    print('[blendqueue] could not read the render settings:', _e)",
        # Python's stdout is block-buffered into a pipe: without this, every
        # print above reaches the log after the render, hours late.
        "import sys",
        "sys.stdout.flush()",
    ])


SCRIPT_HEADER = """# Generated by BlendQueue: this is the file Blender runs for this job.
# Your code starts below and gets bpy, sc (this job's scene) and blend_path.
import bpy

sc = bpy.data.scenes.get({scene!r}) or bpy.context.scene
blend_path = bpy.data.filepath
print("[blendqueue] script:", {name!r})

# --- your script ---
"""


def write_job_script(job: dict, dest) -> str | None:
    """Writes the job's script to a .py that Blender runs with --python.

    A separate file instead of --python-expr so the user's code does not depend
    on command line escaping (accents, quotes, newlines) and so tracebacks point
    at real line numbers.
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
        # Without this Blender prints the traceback and renders anyway: the job must fail.
        args += ["--python-exit-code", "1"]
    expr = override_expr(job)
    if expr:
        args += ["--python-expr", expr]
    if script_path:
        # After the overrides: the user script may override any of them.
        args += ["--python", script_path]
    args += ["--python-expr", final_expr(job)]
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
    """Creates the output folder if missing (the override, or the .blend's)."""
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
            f = int(m.group(1) or m.group(2))
            if f != self.frame:
                self.frame = f
                self.sample = None
                changed = True
        m = SAMPLE_RE.search(line)
        if m:
            self.sample = int(m.group(1) or m.group(3))
            self.sample_total = int(m.group(2) or m.group(4))
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


class FrameClock:
    """How long each frame takes to come out, wall-clock.

    An image of a sequence is done at its "Saved:" line. Blender prints
    "Rendering frame N" even for frames it then skips because they exist, so
    the start of the next frame proves nothing there. Movies print no "Saved:"
    per frame: a movie frame ends when the next one starts, the last one when
    Blender exits.
    """

    def __init__(self, movie: bool = False):
        self.movie = movie
        self.current = None       # frame being rendered
        self.started = None       # when it started (None once it is counted)
        self.done = 0             # frames that came out
        self.last = None          # seconds the latest one took
        self.total = 0.0

    def frame(self, number, now: float) -> None:
        if number is None or number == self.current:
            return
        if self.movie and self.started is not None:
            self._close(now)
        self.current, self.started = number, now

    def saved(self, now: float) -> None:
        # A second "Saved:" for the same frame (stereo views) is not another frame.
        if not self.movie and self.started is not None:
            self._close(now)

    def finish(self, now: float) -> None:
        if self.movie and self.started is not None:
            self._close(now)
        self.current = self.started = None

    def shift(self, seconds: float) -> None:
        """A pause is not render time: the frame in progress started that much later."""
        if self.started is not None:
            self.started += seconds

    def _close(self, end: float) -> None:
        took = max(0.0, end - self.started)
        self.last = round(took, 2)
        self.total += took
        self.done += 1
        self.started = None

    @property
    def average(self):
        return round(self.total / self.done, 2) if self.done else None


# Extensions Blender can produce as a movie (FFmpeg containers + AVI).
VIDEO_EXTS = tuple(sorted({c["ext"] for c in formats.FFMPEG_CONTAINERS} | {".avi"}))

# Formats a browser cannot show in an <img>: their preview is built with ffmpeg.
HDR_EXTS = (".exr", ".hdr", ".dpx", ".cin")

# Formats ffmpeg cannot read: say so instead of trying and failing.
NO_PREVIEW = {"OPEN_EXR_MULTILAYER": "ffmpeg cannot read multilayer EXR"}


def preview_block_reason(fmt: str | None) -> str | None:
    return NO_PREVIEW.get(fmt or "")


def remux_preview(src: str, dest: str, log=print) -> str | None:
    """Converts the rendered movie (mkv/avi/...) into a browser-playable MP4."""
    ff = config.ffmpeg_path()
    if not ff or not os.path.exists(src):
        return None
    args = [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", src,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-c:a", "aac", "-b:a", "160k", dest]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=1800,
                              **system.popen_kwargs())
    except Exception as exc:
        log(f"ffmpeg (movie) failed: {exc}")
        return None
    if proc.returncode != 0 or not os.path.exists(dest):
        log("ffmpeg (movie) exit " + str(proc.returncode) + " " + (proc.stderr or "")[-400:])
        return None
    return dest


def build_preview_video(outputs: list, fps: float, dest: str, log=print) -> str | None:
    """Builds a preview MP4 from the rendered sequence (ffmpeg)."""
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

    # EXR stores linear color: without the conversion the preview looks washed
    # out. If the installed ffmpeg rejects the option, retry without it.
    attempts = [[]]
    if os.path.splitext(files[0])[1].lower() == ".exr":
        attempts.insert(0, ["-apply_trc", "iec61966_2_1"])
    try:
        for extra in attempts:
            args = [ff, "-y", "-hide_banner", "-loglevel", "error"] + extra + input_args + out_args
            try:
                proc = subprocess.run(args, capture_output=True, text=True, timeout=1800,
                                      **system.popen_kwargs())
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
