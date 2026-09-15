"""Catalog of Blender output formats and validation of the per-job overrides.

Blender stores the output format in ``scene.render.image_settings`` (plus
``scene.render.ffmpeg`` for video). BlendQueue can override it per job, so a
queue holding mixed files -- one PNG, one multilayer EXR, one video -- gets
unified without opening Blender or touching the .blend files.

This module is the single source of truth for:
  * which formats the interface offers and with which options (depth, quality...),
  * which extension each one produces (used to find the render outputs),
  * which formats are movies (changes the ``-o`` pattern and the preview).

The identifiers are Blender's own enums. Inspecting a .blend reads the real
enums of that installation and they filter this catalog (see ``catalog``), so
the UI never offers something the detected Blender does not have.
"""
from __future__ import annotations

# quality_kind: "quality" -> image_settings.quality; "compression" -> image_settings.compression
FORMATS: list[dict] = [
    {"id": "PNG", "label": "PNG", "ext": ".png", "media": "IMAGE", "common": True,
     "depths": ["8", "16"], "modes": ["BW", "RGB", "RGBA"],
     "quality_kind": "compression", "quality_label": "Compression %"},
    {"id": "JPEG", "label": "JPEG", "ext": ".jpg", "media": "IMAGE", "common": True,
     "depths": ["8"], "modes": ["BW", "RGB"],
     "quality_kind": "quality", "quality_label": "Quality %"},
    {"id": "OPEN_EXR", "label": "OpenEXR", "ext": ".exr", "media": "IMAGE", "common": True,
     "depths": ["16", "32"], "modes": ["BW", "RGB", "RGBA"], "exr": True},
    {"id": "OPEN_EXR_MULTILAYER", "label": "OpenEXR multilayer", "ext": ".exr",
     "media": "MULTI_LAYER_IMAGE", "common": True,
     "depths": ["16", "32"], "modes": ["BW", "RGB", "RGBA"], "exr": True},
    {"id": "FFMPEG", "label": "Video (FFmpeg)", "ext": ".mp4", "media": "VIDEO",
     "common": True, "movie": True, "ffmpeg": True,
     "depths": [], "modes": ["BW", "RGB", "RGBA"]},
    {"id": "WEBP", "label": "WebP", "ext": ".webp", "media": "IMAGE", "common": True,
     "depths": ["8"], "modes": ["BW", "RGB", "RGBA"],
     "quality_kind": "quality", "quality_label": "Quality %"},
    {"id": "TIFF", "label": "TIFF", "ext": ".tif", "media": "IMAGE", "common": True,
     "depths": ["8", "16"], "modes": ["BW", "RGB", "RGBA"]},
    {"id": "TARGA", "label": "Targa", "ext": ".tga", "media": "IMAGE",
     "depths": ["8"], "modes": ["BW", "RGB", "RGBA"]},
    {"id": "TARGA_RAW", "label": "Uncompressed Targa", "ext": ".tga", "media": "IMAGE",
     "depths": ["8"], "modes": ["BW", "RGB", "RGBA"]},
    {"id": "BMP", "label": "BMP", "ext": ".bmp", "media": "IMAGE",
     "depths": ["8"], "modes": ["BW", "RGB"]},
    {"id": "IRIS", "label": "Iris", "ext": ".rgb", "media": "IMAGE",
     "depths": ["8"], "modes": ["BW", "RGB", "RGBA"]},
    {"id": "JPEG2000", "label": "JPEG 2000", "ext": ".jp2", "media": "IMAGE",
     "depths": ["8", "12", "16"], "modes": ["BW", "RGB", "RGBA"],
     "quality_kind": "quality", "quality_label": "Quality %"},
    {"id": "AVIF", "label": "AVIF", "ext": ".avif", "media": "IMAGE",
     "depths": ["8", "10", "12"], "modes": ["RGB", "RGBA"],
     "quality_kind": "quality", "quality_label": "Quality %"},
    {"id": "DPX", "label": "DPX", "ext": ".dpx", "media": "IMAGE",
     "depths": ["8", "10", "12", "16"], "modes": ["BW", "RGB", "RGBA"]},
    {"id": "CINEON", "label": "Cineon", "ext": ".cin", "media": "IMAGE",
     "depths": ["10"], "modes": ["BW", "RGB"]},
    {"id": "HDR", "label": "Radiance HDR", "ext": ".hdr", "media": "IMAGE",
     "depths": [], "modes": ["BW", "RGB"]},
    {"id": "AVI_JPEG", "label": "AVI JPEG", "ext": ".avi", "media": "VIDEO", "movie": True,
     "depths": [], "modes": ["BW", "RGB"],
     "quality_kind": "quality", "quality_label": "Quality %"},
    {"id": "AVI_RAW", "label": "Uncompressed AVI", "ext": ".avi", "media": "VIDEO",
     "movie": True, "depths": [], "modes": ["BW", "RGB"]},
]

BY_ID = {f["id"]: f for f in FORMATS}
MOVIE_FORMATS = {f["id"] for f in FORMATS if f.get("movie")}

# scene.render.ffmpeg.format -> container and resulting extension
FFMPEG_CONTAINERS: list[dict] = [
    {"id": "MPEG4", "label": "MPEG-4 (.mp4)", "ext": ".mp4"},
    {"id": "MKV", "label": "Matroska (.mkv)", "ext": ".mkv"},
    {"id": "QUICKTIME", "label": "QuickTime (.mov)", "ext": ".mov"},
    {"id": "WEBM", "label": "WebM (.webm)", "ext": ".webm"},
    {"id": "AVI", "label": "AVI (.avi)", "ext": ".avi"},
    {"id": "OGG", "label": "Ogg Theora (.ogv)", "ext": ".ogv"},
    {"id": "FLASH", "label": "Flash (.flv)", "ext": ".flv"},
    {"id": "DV", "label": "DV (.dv)", "ext": ".dv"},
    {"id": "MPEG1", "label": "MPEG-1 (.mpg)", "ext": ".mpg"},
    {"id": "MPEG2", "label": "MPEG-2 (.dvd)", "ext": ".dvd"},
]
FFMPEG_CONTAINER_IDS = {c["id"] for c in FFMPEG_CONTAINERS}

# scene.render.ffmpeg.codec
FFMPEG_CODECS: list[dict] = [
    {"id": "H264", "label": "H.264"},
    {"id": "HEVC", "label": "H.265 / HEVC"},
    {"id": "AV1", "label": "AV1"},
    {"id": "WEBM", "label": "VP9 (WebM)"},
    {"id": "THEORA", "label": "Theora"},
    {"id": "MPEG4", "label": "MPEG-4"},
    {"id": "MPEG2", "label": "MPEG-2"},
    {"id": "MPEG1", "label": "MPEG-1"},
    {"id": "DNXHD", "label": "DNxHD"},
    {"id": "FFV1", "label": "FFV1 (lossless)"},
    {"id": "HUFFYUV", "label": "HuffYUV (lossless)"},
    {"id": "QTRLE", "label": "QuickTime RLE (alpha)"},
    {"id": "PNG", "label": "PNG (alpha)"},
    {"id": "DV", "label": "DV"},
    {"id": "NONE", "label": "No video"},
]
FFMPEG_CODEC_IDS = {c["id"] for c in FFMPEG_CODECS}

EXR_CODECS: list[dict] = [
    {"id": "NONE", "label": "Uncompressed"},
    {"id": "ZIP", "label": "ZIP (blocks)"},
    {"id": "ZIPS", "label": "ZIPS (per line)"},
    {"id": "PIZ", "label": "PIZ"},
    {"id": "RLE", "label": "RLE"},
    {"id": "PXR24", "label": "Pxr24 (lossy)"},
    {"id": "B44", "label": "B44 (lossy)"},
    {"id": "B44A", "label": "B44A (lossy)"},
    {"id": "DWAA", "label": "DWAA (lossy)"},
    {"id": "DWAB", "label": "DWAB (lossy)"},
]
EXR_CODEC_IDS = {c["id"] for c in EXR_CODECS}

COLOR_MODES: list[dict] = [
    {"id": "BW", "label": "BW (grayscale)"},
    {"id": "RGB", "label": "RGB"},
    {"id": "RGBA", "label": "RGBA (with alpha)"},
]

# Override keys that belong to the output format.
FORMAT_KEYS = ("format", "color_depth", "color_mode", "quality",
               "exr_codec", "ffmpeg_container", "ffmpeg_codec")


def spec(fmt: str | None) -> dict | None:
    return BY_ID.get(fmt or "")


def is_movie(fmt: str | None) -> bool:
    return (fmt or "") in MOVIE_FORMATS


def media_type(fmt: str | None) -> str | None:
    s = spec(fmt)
    return s.get("media") if s else None


def extension(fmt: str | None, container: str | None = None) -> str | None:
    """Extension Blender will give the file with this format."""
    s = spec(fmt)
    if not s:
        return None
    if s.get("ffmpeg"):
        for c in FFMPEG_CONTAINERS:
            if c["id"] == (container or "MPEG4"):
                return c["ext"]
        return ".mp4"
    return s.get("ext")


def label(fmt: str | None, container: str | None = None, depth: str | None = None) -> str:
    """Short label for the UI: 'OpenEXR multilayer 32', 'Video .mp4', 'PNG 16'."""
    s = spec(fmt)
    if not s:
        return fmt or "—"
    if s.get("ffmpeg"):
        return "Video " + (extension(fmt, container) or ".mp4")
    txt = s["label"]
    depths = s.get("depths") or []
    if depth and depth in depths and len(depths) > 1:
        txt += " " + str(depth)
    return txt


def _clamp_int(value, lo: int, hi: int):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return None


def normalize(ov: dict | None) -> dict:
    """Cleans the format overrides: drops invalid values and values that do not
    apply to the chosen format (e.g. an EXR codec with PNG output)."""
    ov = dict(ov or {})
    fmt = str(ov.get("format") or "").strip().upper() or None
    if fmt and fmt not in BY_ID:
        fmt = None
    if not fmt:
        for k in FORMAT_KEYS:
            ov.pop(k, None)
        return ov

    s = BY_ID[fmt]
    out = dict(ov)
    out["format"] = fmt

    depth = str(out.get("color_depth") or "").strip()
    if depth and depth in (s.get("depths") or []):
        out["color_depth"] = depth
    else:
        out.pop("color_depth", None)

    mode = str(out.get("color_mode") or "").strip().upper()
    if mode and mode in (s.get("modes") or []):
        out["color_mode"] = mode
    else:
        out.pop("color_mode", None)

    if s.get("quality_kind"):
        q = _clamp_int(out.get("quality"), 0, 100)
        if q is None:
            out.pop("quality", None)
        else:
            out["quality"] = q
    else:
        out.pop("quality", None)

    if s.get("exr"):
        codec = str(out.get("exr_codec") or "").strip().upper()
        if codec in EXR_CODEC_IDS:
            out["exr_codec"] = codec
        else:
            out.pop("exr_codec", None)
    else:
        out.pop("exr_codec", None)

    if s.get("ffmpeg"):
        cont = str(out.get("ffmpeg_container") or "").strip().upper()
        out["ffmpeg_container"] = cont if cont in FFMPEG_CONTAINER_IDS else "MPEG4"
        codec = str(out.get("ffmpeg_codec") or "").strip().upper()
        if codec in FFMPEG_CODEC_IDS:
            out["ffmpeg_codec"] = codec
        else:
            out.pop("ffmpeg_codec", None)
    else:
        out.pop("ffmpeg_container", None)
        out.pop("ffmpeg_codec", None)
    return out


def summary(ov: dict | None) -> str:
    """Readable summary of the format override: 'OpenEXR multilayer 32 - ZIP'."""
    ov = ov or {}
    fmt = ov.get("format")
    if not fmt:
        return ""
    parts = [label(fmt, ov.get("ffmpeg_container"), ov.get("color_depth"))]
    if ov.get("color_mode"):
        parts.append(str(ov["color_mode"]))
    if ov.get("exr_codec"):
        parts.append(str(ov["exr_codec"]))
    if ov.get("ffmpeg_codec"):
        parts.append(next((c["label"] for c in FFMPEG_CODECS if c["id"] == ov["ffmpeg_codec"]),
                          str(ov["ffmpeg_codec"])))
    if ov.get("quality") is not None:
        kind = (spec(fmt) or {}).get("quality_kind")
        parts.append(("compression " if kind == "compression" else "quality ")
                     + str(ov["quality"]) + "%")
    return " · ".join(parts)


def _ids(caps: dict | None, key: str) -> set:
    out = set()
    for it in (caps or {}).get(key) or []:
        if isinstance(it, dict) and it.get("id"):
            out.add(str(it["id"]))
        elif isinstance(it, str):
            out.add(it)
    return out


def catalog(caps: dict | None = None) -> dict:
    """Catalog for the UI, filtered by what the detected Blender supports.

    ``caps`` comes from the inspection report (the real enums of that install);
    without ``caps`` the full catalog is returned.
    """
    avail = _ids(caps, "file_format")
    fmts = []
    for f in FORMATS:
        if avail and f["id"] not in avail:
            continue
        item = {k: f.get(k) for k in
                ("id", "label", "ext", "media", "depths", "modes",
                 "quality_kind", "quality_label")}
        item["movie"] = bool(f.get("movie"))
        item["ffmpeg"] = bool(f.get("ffmpeg"))
        item["exr"] = bool(f.get("exr"))
        item["common"] = bool(f.get("common"))
        fmts.append(item)

    def _filter(items, key):
        ids = _ids(caps, key)
        return [i for i in items if not ids or i["id"] in ids]

    return {
        "formats": fmts,
        "ffmpeg_containers": _filter(FFMPEG_CONTAINERS, "ffmpeg_format"),
        "ffmpeg_codecs": _filter(FFMPEG_CODECS, "ffmpeg_codec"),
        "exr_codecs": _filter(EXR_CODECS, "exr_codec"),
        "color_modes": COLOR_MODES,
        "source": "blender" if avail else "builtin",
    }
