"""Genera un .blend de prueba con salida de PELÍCULA (FFMPEG, contenedor MKV).

Uso:
    blender.exe -b --factory-startup --python make_movie_blend.py -- "C:/ruta/data/tests"
"""
import os
import sys

import bpy


def _out_dir():
    args = list(sys.argv)
    if "--" in args:
        rest = args[args.index("--") + 1:]
        if rest:
            return rest[0]
    return os.getcwd()


bpy.ops.wm.read_factory_settings(use_empty=False)
sc = bpy.context.scene
sc.name = "MovieTest"
try:
    sc.render.engine = "BLENDER_EEVEE"
except Exception:
    sc.render.engine = "BLENDER_EEVEE_NEXT"
sc.render.resolution_x, sc.render.resolution_y = 320, 180
sc.render.resolution_percentage = 100
sc.render.fps = 24
sc.frame_start, sc.frame_end = 1, 6
sc.render.image_settings.file_format = "FFMPEG"
for cont in ("MKV", "MATROSKA", "MPEG4"):
    try:
        sc.render.ffmpeg.format = cont
        break
    except Exception:
        continue

cube = bpy.data.objects.get("Cube")
if cube:
    cube.location.x = -2.0
    cube.keyframe_insert("location", frame=1)
    cube.location.x = 2.0
    cube.keyframe_insert("location", frame=6)

sc.render.filepath = "//movie_test"
target = os.path.join(_out_dir(), "movie_test.blend").replace("\\", "/")
bpy.ops.wm.save_as_mainfile(filepath=target)
print("TEST_BLEND_OK " + target)
