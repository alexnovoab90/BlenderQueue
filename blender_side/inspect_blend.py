"""Fase Blender: extrae metadatos de un .blend (escenas, frames, salidas, dependencias).

Este script corre DENTRO de Blender, no en el servidor:

    blender.exe -b "archivo.blend" --python inspect_blend.py -- "salida.json"

Escribe un JSON con la información de cada escena (rango de frames, resolución,
motor, samples, cámara, formato y salida) más el chequeo de dependencias
externas (texturas, bibliotecas) que puedan faltar y los formatos de salida
que soporta esta instalación de Blender ("capabilities").
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


def _enum_items(rna_struct, prop_name):
    """Ítems de un enum leídos del RNA del tipo (lista completa, no filtrada)."""
    out, seen = [], set()
    try:
        prop = rna_struct.bl_rna.properties[prop_name]
    except Exception:
        return out
    for attr in ("enum_items_static", "enum_items"):
        try:
            items = list(getattr(prop, attr, None) or [])
        except Exception:
            items = []
        for it in items:
            if it.identifier in seen:
                continue
            seen.add(it.identifier)
            out.append({"id": it.identifier, "name": it.name})
    return out


def _capabilities():
    """Formatos de salida que ofrece esta instalación (para la UI de BlendQueue)."""
    caps = {"blender_version": bpy.app.version_string}
    try:
        ims = bpy.types.ImageFormatSettings
        for prop in ("file_format", "media_type", "color_mode", "color_depth", "exr_codec"):
            items = _enum_items(ims, prop)
            if items:
                caps[prop] = items
    except Exception as exc:
        caps["error"] = repr(exc)
    try:
        ff = bpy.types.FFmpegSettings
        for prop, key in (("format", "ffmpeg_format"), ("codec", "ffmpeg_codec")):
            items = _enum_items(ff, prop)
            if items:
                caps[key] = items
    except Exception:
        pass
    return caps


def _format_info(r):
    """Ajustes de salida de una escena (image_settings + ffmpeg)."""
    ims = r.image_settings
    fmt = ims.file_format
    info = {
        "file_format": fmt,
        "is_movie": fmt in MOVIE_FORMATS,
        "media_type": getattr(ims, "media_type", None),
        "color_mode": getattr(ims, "color_mode", None),
        "color_depth": getattr(ims, "color_depth", None),
        "use_file_extension": bool(getattr(r, "use_file_extension", True)),
    }
    for attr in ("quality", "compression"):
        try:
            info[attr] = int(getattr(ims, attr))
        except Exception:
            pass
    if fmt in ("OPEN_EXR", "OPEN_EXR_MULTILAYER"):
        info["exr_codec"] = getattr(ims, "exr_codec", None)
    if fmt == "FFMPEG":
        try:
            info["ffmpeg_container"] = r.ffmpeg.format
            info["ffmpeg_codec"] = r.ffmpeg.codec
        except Exception:
            pass
    return info


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
        "filepath_raw": r.filepath,
        "filepath_abs": _abs(r.filepath) if r.filepath else None,
    }
    try:
        info.update(_format_info(r))
    except Exception as exc:
        info["file_format"] = None
        info["format_error"] = repr(exc)
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
        "capabilities": _capabilities(),
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
