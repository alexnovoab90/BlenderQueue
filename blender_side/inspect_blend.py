"""Fase Blender: extrae metadatos de un .blend (escenas, frames, salidas, dependencias).

Este script corre DENTRO de Blender, no en el servidor:

    blender.exe -b "archivo.blend" --python inspect_blend.py -- "salida.json"

Escribe un JSON con la información de cada escena (rango de frames, resolución,
motor, samples, cámara y salida) más el chequeo de dependencias externas
(texturas, bibliotecas) que puedan faltar.
"""
import json
import os
import re
import sys

import bpy

MOVIE_FORMATS = {"FFMPEG", "AVI_JPEG", "AVI_RAW"}

# Referencias que NO son dependencias reales de render (ruido típico):
#  - copybuffer.blend: buffer interno de copiar/pegar de Blender
#  - datafiles/assets: librerías de assets incluidas en la instalación de Blender
#  - blends temporales en carpetas Temp
NOISE_RE = re.compile(
    r"copybuffer\.blend$"
    r"|datafiles[\\/]+assets[\\/]"
    r"|[\\/]Temp[\\/][^\\/]+\.blend$",
    re.IGNORECASE,
)


def _abs(p):
    try:
        return bpy.path.abspath(p)
    except Exception:
        return p


def _exists(p):
    try:
        return bool(p) and os.path.exists(p)
    except Exception:
        return False


def _scene_info(sc):
    r = sc.render
    fps = 0.0
    try:
        base = r.fps_base or 1.0
        fps = round(r.fps / base, 4)
    except Exception:
        pass
    step = int(getattr(sc, "frame_step", 1) or 1)
    count = max(0, (int(sc.frame_end) - int(sc.frame_start))) // max(step, 1) + 1
    info = {
        "name": sc.name,
        "frame_start": int(sc.frame_start),
        "frame_end": int(sc.frame_end),
        "frame_step": step,
        "frame_count": count,
        "fps": fps,
        "resolution_native": [int(r.resolution_x), int(r.resolution_y)],
        "resolution_percentage": int(r.resolution_percentage),
        "resolution_x": int(r.resolution_x * r.resolution_percentage / 100),
        "resolution_y": int(r.resolution_y * r.resolution_percentage / 100),
        "engine": r.engine,
        "camera": sc.camera.name if sc.camera else None,
        "file_format": r.image_settings.file_format,
        "is_movie": r.image_settings.file_format in MOVIE_FORMATS,
        "filepath_raw": r.filepath,
        "filepath_abs": _abs(r.filepath) if r.filepath else None,
    }
    if r.engine == "CYCLES":
        try:
            cy = sc.cycles
            info["samples"] = int(cy.samples)
            info["device"] = cy.device
            info["denoise"] = bool(cy.use_denoising)
        except Exception:
            pass
    elif "EEVEE" in r.engine:
        try:
            info["samples"] = int(sc.eevee.taa_render_samples)
        except Exception:
            pass
    return info


def build_report():
    data = {
        "ok": True,
        "blend_filepath": bpy.data.filepath,
        "saved_with": ".".join(str(v) for v in getattr(bpy.data, "version", ())),
        "blender_version": bpy.app.version_string,
        "scenes": [],
        "counts": {
            "scenes": len(bpy.data.scenes),
            "objects": len(bpy.data.objects),
            "collections": len(bpy.data.collections),
            "cameras": len(bpy.data.cameras),
            "meshes": len(bpy.data.meshes),
            "actions": len(bpy.data.actions),
            "images": len(bpy.data.images),
        },
    }

    for sc in bpy.data.scenes:
        try:
            data["scenes"].append(_scene_info(sc))
        except Exception as exc:
            data["scenes"].append({"name": getattr(sc, "name", "?"), "error": repr(exc)})

    libs = []
    for lib in bpy.data.libraries:
        ap = _abs(lib.filepath)
        libs.append({"path": lib.filepath, "abs": ap, "missing": not _exists(ap)})
    data["libraries"] = libs

    ext = []
    try:
        seen = set()
        for p in bpy.utils.blend_paths(absolute=False):
            ap = _abs(p)
            key = (ap or p or "").lower()
            if not key or key in seen:
                continue
            seen.add(key)
            noise = bool(NOISE_RE.search(ap or p or ""))
            ext.append({"path": p, "abs": ap, "missing": not _exists(ap), "noise": noise})
    except Exception as exc:
        data["external_files_error"] = repr(exc)
    data["external_files"] = ext
    data["missing_external_count"] = sum(1 for x in ext if x["missing"] and not x.get("noise"))
    data["missing_raw_count"] = sum(1 for x in ext if x["missing"])
    return data


def run():
    args = list(sys.argv)
    out_path = None
    if "--" in args:
        rest = args[args.index("--") + 1:]
        if rest:
            out_path = rest[0]
    try:
        data = build_report()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        data = {"ok": False, "error": repr(exc)}
    payload = json.dumps(data, indent=1, ensure_ascii=False)
    if out_path:
        tmp = out_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, out_path)
        print("INSPECT_DONE " + out_path)
    else:
        print(payload)


run()
