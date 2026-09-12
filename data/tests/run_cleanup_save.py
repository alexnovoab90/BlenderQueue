"""Aplica un script de limpieza a un .blend cargado y guarda el resultado.

Uso:
    blender -b "archivo.blend" --python run_cleanup_save.py -- "script.py" ["salida.blend"]
"""
import sys
import time

import bpy


def main():
    args = list(sys.argv)
    rest = args[args.index("--") + 1:] if "--" in args else []
    if not rest:
        print("CLEANUP_ERROR: faltan argumentos (script.py [salida.blend])")
        return
    script_path = rest[0]
    out_path = rest[1] if len(rest) > 1 and rest[1] else ""

    t0 = time.time()
    mats_before = len(bpy.data.materials)
    objs_before = len(bpy.data.objects)

    ns = {"__name__": "cleanup_script"}
    with open(script_path, "r", encoding="utf-8") as fh:
        code = fh.read()
    exec(compile(code, script_path, "exec"), ns)
    fn = ns.get("consolidar_locales_version_maxima")
    if not fn:
        print("CLEANUP_ERROR: no se encontró la función consolidar_locales_version_maxima")
        return

    try:
        fn()
    except Exception as exc:
        print("CLEANUP_OP_ERROR:", repr(exc))
        print("CLEANUP_FALLBACK: purga vía bpy.data.orphans_purge")
        for _ in range(3):
            bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=True)

    mats_after = len(bpy.data.materials)
    print(f"CLEANUP_STATS: materiales {mats_before} -> {mats_after} "
          f"| objetos {objs_before} -> {len(bpy.data.objects)} | {time.time() - t0:.1f}s")

    if out_path:
        bpy.ops.wm.save_as_mainfile(filepath=out_path)
        print("CLEANUP_SAVED " + out_path)
    else:
        print("CLEANUP_SIN_GUARDAR")


main()
