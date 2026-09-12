"""Analiza un reporte de inspección de BlendQueue (JSON de blender_side/inspect_blend.py)."""
import collections
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "data/inspect/f-61c126e51a.json"
with open(path, encoding="utf-8") as fh:
    d = json.load(fh)

print("archivo:", d.get("blend_filepath"))
print("guardado con Blender:", d.get("saved_with"), "| inspección:", d.get("inspect_seconds"), "s")
print("counts:", d.get("counts"))
print()
print("== escenas ==")
for s in d.get("scenes", []):
    print(" -", s.get("name"), "| frames", s.get("frame_start"), "-", s.get("frame_end"),
          "(%s)" % s.get("frame_count"), "| fps:", s.get("fps"), "| step:", s.get("frame_step"))
    print("   engine:", s.get("engine"), "| samples:", s.get("samples"), "| resolution:",
          s.get("resolution_x"), "x", s.get("resolution_y"), "(base", s.get("resolution_native"), "%", s.get("resolution_percentage"), ")")
    print("   camara:", s.get("camera"), "| formato:", s.get("file_format"), "| is_movie:", s.get("is_movie"))
    print("   out:", repr(s.get("filepath_raw")), "->", s.get("filepath_abs"))
print()
ext = d.get("external_files") or []
missing = [e for e in ext if e.get("missing")]
print("== externos: total", len(ext), "| faltan:", len(missing))
roots = collections.Counter()
for e in missing:
    p = e.get("abs") or e.get("path") or ""
    if len(p) > 2 and p[1:3] in (":\\", ":/"):
        root = p[:3].upper()
    elif p.startswith("//"):
        root = "(relativo //)"
    else:
        root = "(otro)"
    roots[root] += 1
print("faltantes por raíz:", dict(roots))
print()
print("== ejemplos de FALTANTES ==")
for e in missing[:20]:
    print("   x", e.get("path"))
print()
print("== ejemplos de EXISTENTES ==")
ok = [x for x in ext if not x.get("missing")]
for e in ok[:8]:
    print("   ✓", e.get("path"))
print()
libs = d.get("libraries") or []
print("== librerías enlazadas:", len(libs))
for lib in libs[:10]:
    print("   ", ("x " if lib.get("missing") else "✓ "), lib.get("path"))
