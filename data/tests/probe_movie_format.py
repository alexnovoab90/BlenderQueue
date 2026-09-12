"""Sondeo: ¿cómo se configura salida de PELÍCULA (FFMPEG) en Blender 5.2?

Uso:
    blender.exe -b [archivo.blend] --python probe_movie_format.py
"""
import bpy

sc = bpy.context.scene
print("FILE:", bpy.data.filepath)
print("CURRENT file_format:", sc.render.image_settings.file_format)
items = [i.identifier for i in sc.render.image_settings.bl_rna.properties["file_format"].enum_items]
print("ITEMS image_settings.file_format:", items)
try:
    sc.render.image_settings.file_format = "FFMPEG"
    print("SET FFMPEG: OK ->", sc.render.image_settings.file_format)
except Exception as exc:
    print("SET FFMPEG FALLA:", exc)
# ¿otros sitios posibles?
for owner_name, owner in (
    ("render", sc.render),
    ("image_settings", sc.render.image_settings),
    ("ffmpeg(render)", getattr(sc.render, "ffmpeg", None)),
):
    if owner is None:
        print(owner_name, "-> no existe")
        continue
    props = [p.identifier for p in owner.bl_rna.properties
             if "mov" in p.identifier.lower() or "ffmpeg" in p.identifier.lower()]
    print(owner_name, "props movie/ffmpeg:", props)
print("hasattr render.ffmpeg:", hasattr(sc.render, "ffmpeg"))
try:
    print("ffmpeg.format actual:", sc.render.ffmpeg.format)
    conts = [i.identifier for i in sc.render.ffmpeg.bl_rna.properties["format"].enum_items]
    print("ffmpeg.format items:", conts)
except Exception as exc:
    print("ffmpeg err:", exc)
# ¿existe un flag global use_movie?
for cand in ("use_movie", "movie_format", "output_mode"):
    print("render." + cand, "->", hasattr(sc.render, cand))
