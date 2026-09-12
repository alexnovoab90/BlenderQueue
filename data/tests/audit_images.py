"""Audita las imágenes del .blend: faltantes, empacadas, y qué usa el mundo.

Uso: blender -b archivo.blend --python audit_images.py
"""
import os

import bpy


def _missing(img):
    if img is None:
        return False
    if img.source != "FILE":
        return False
    if img.packed_file is not None:
        return False
    return not os.path.exists(bpy.path.abspath(img.filepath))


print("== imágenes totales:", len(bpy.data.images))
missing = [img for img in bpy.data.images if _missing(img)]
print("== imágenes FILE faltantes:", len(missing))
for img in missing[:30]:
    print("   X %s | %r | users=%d" % (img.name, img.filepath, img.users))

for sc in bpy.data.scenes:
    w = sc.world
    print("== mundo:", w.name if w else "(sin mundo)")
    if w and w.use_nodes:
        for n in w.node_tree.nodes:
            if n.type == "TEX_ENVIRONMENT":
                im = getattr(n, "image", None)
                estado = "sin imagen"
                if im is not None:
                    if im.packed_file is not None:
                        estado = "empacada"
                    elif os.path.exists(bpy.path.abspath(im.filepath)):
                        estado = "OK"
                    else:
                        estado = "FALTA -> " + bpy.path.abspath(im.filepath)
                print("   ENV:", (im.name if im else None), "|", estado)

bad_mats = set()
for mat in bpy.data.materials:
    if not mat.use_nodes:
        continue
    for n in mat.node_tree.nodes:
        if n.type == "TEX_IMAGE" and _missing(n.image):
            bad_mats.add(mat.name)
print("== materiales con texturas faltantes:", len(bad_mats))
for m in sorted(bad_mats)[:25]:
    print("   M", m)
