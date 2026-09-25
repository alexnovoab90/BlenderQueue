"""Generates BlendQueue's test .blend files into data/tests/.

    blender.exe -b --factory-startup --python tests/make_tests.py -- "<repo>/data/tests"

Creates: quick.blend (EEVEE, 8 frames), multi.blend (two scenes),
quick_cycles.blend (Cycles, 2 frames) and textured.blend (a texture next to it,
referenced with a relative path).
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


def _set_engine(sc, engine):
    try:
        sc.render.engine = engine
    except Exception:
        alt = "BLENDER_EEVEE_NEXT" if engine == "BLENDER_EEVEE" else "BLENDER_EEVEE"
        sc.render.engine = alt


def _reset():
    bpy.ops.wm.read_factory_settings(use_empty=False)


def _setup_common(sc, fps=24, res=(320, 180)):
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.fps = fps
    sc.render.image_settings.file_format = "PNG"


def _animate_cube(sc, frame_a, frame_b, x_from, x_to):
    cube = bpy.data.objects.get("Cube")
    if not cube:
        return
    cube.location.x = x_from
    cube.keyframe_insert("location", frame=frame_a)
    cube.location.x = x_to
    cube.keyframe_insert("location", frame=frame_b)


def make_quick(path):
    _reset()
    sc = bpy.context.scene
    sc.name = "Rapida"
    _set_engine(sc, "BLENDER_EEVEE")
    _setup_common(sc)
    sc.frame_start, sc.frame_end = 1, 8
    sc.render.filepath = "//render_"
    _animate_cube(sc, 1, 8, -2.5, 2.5)
    bpy.ops.wm.save_as_mainfile(filepath=path)


def make_multi(path):
    _reset()
    sc = bpy.context.scene
    sc.name = "EscenaA"
    _set_engine(sc, "BLENDER_EEVEE")
    _setup_common(sc)
    sc.frame_start, sc.frame_end = 1, 6
    sc.render.filepath = "//a_render_"
    _animate_cube(sc, 1, 6, -2.0, 2.0)
    sc_b = sc.copy()
    sc_b.name = "EscenaB"
    sc_b.use_fake_user = True  # without this Blender drops scenes with no window
    sc_b.frame_start, sc_b.frame_end = 1, 4
    sc_b.render.filepath = "//b_render_"
    bpy.ops.wm.save_as_mainfile(filepath=path)


def make_cycles(path):
    _reset()
    sc = bpy.context.scene
    sc.name = "CyclesRapida"
    _setup_common(sc, res=(160, 90))
    sc.render.engine = "CYCLES"
    sc.cycles.samples = 8
    sc.cycles.use_denoising = True
    sc.frame_start, sc.frame_end = 1, 2
    sc.render.filepath = "//cycles_"
    _animate_cube(sc, 1, 2, -1.5, 1.5)
    bpy.ops.wm.save_as_mainfile(filepath=path)


def make_textured(path):
    """A texture saved next to the .blend and referenced as '//tex/...': an
    uploaded copy of this file cannot find it, the original can."""
    _reset()
    sc = bpy.context.scene
    sc.name = "Textura"
    _set_engine(sc, "BLENDER_EEVEE")
    _setup_common(sc)
    sc.frame_start, sc.frame_end = 1, 2
    sc.render.filepath = "//tex_render_"
    folder = os.path.join(os.path.dirname(path), "tex")
    os.makedirs(folder, exist_ok=True)
    img = bpy.data.images.new("checker", 64, 64)
    img.generated_type = "COLOR_GRID"
    img.filepath_raw = os.path.join(folder, "checker.png")
    img.file_format = "PNG"
    img.save()
    mat = bpy.data.materials.new("Checker")
    mat.use_nodes = True
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = img
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    cube = bpy.data.objects.get("Cube")
    if cube:
        cube.data.materials.clear()
        cube.data.materials.append(mat)
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.file.make_paths_relative()
    bpy.ops.wm.save_mainfile()


def main():
    target = _out_dir()
    os.makedirs(target, exist_ok=True)
    jobs = [
        ("quick.blend", make_quick),
        ("multi.blend", make_multi),
        ("quick_cycles.blend", make_cycles),
        ("textured.blend", make_textured),
    ]
    for name, fn in jobs:
        path = os.path.join(target, name).replace("\\", "/")
        fn(path)
        print("TEST_BLEND_OK " + path)
    print("TESTS_DONE")


main()
