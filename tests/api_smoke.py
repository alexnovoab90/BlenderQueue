"""Prueba de humo de BlendQueue contra el servidor local (debe estar corriendo).

    tests\run_smoke.bat quick        renderiza una secuencia EEVEE corta
    tests\run_smoke.bat multi        comprueba la seleccion de escena (-S)
    tests\run_smoke.bat cycles       render Cycles en GPU
    tests\run_smoke.bat format       overrides de formato: EXR, video, cola mezclada
    tests\run_smoke.bat script       scripts de Python por trabajo
    tests\run_smoke.bat real "G:/ruta/archivo.blend" [render]

Los .blend de prueba los genera tests/make_tests.py con Blender.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("BLENDQUEUE_URL", "http://127.0.0.1:8777")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "data", "tests").replace("\\", "/")


def req(method, path, body=None, timeout=180):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def find(d, key, iid):
    return next((x for x in d.get(key, []) if x.get("id") == iid), None)


def wait_file(fid, timeout=900):
    t0 = time.time()
    while time.time() - t0 < timeout:
        f = find(req("GET", "/api/state"), "files", fid)
        if f and f.get("status") in ("ready", "error"):
            return f
        time.sleep(2)
    return None


def wait_job(jid, timeout=2400):
    t0, last = time.time(), ""
    while time.time() - t0 < timeout:
        j = find(req("GET", "/api/state"), "jobs", jid)
        if j:
            p = j.get("progress") or {}
            line = "{} {:.0%} {}".format(j["status"], p.get("percent") or 0, p.get("message") or "")
            if line != last:
                print("    " + line, flush=True)
                last = line
            if j["status"] in ("done", "error", "canceled"):
                return j
        time.sleep(2)
    return None


def add_and_inspect(path):
    print("== agregar:", path)
    r = req("POST", "/api/files/add", {"paths": [path]})
    fid = r["added"][0]["id"]
    f = wait_file(fid)
    if not f or f.get("status") != "ready":
        print("FALLO DE INSPECCIÓN:", (f or {}).get("inspect_error"))
        return None
    rep = f["report"]
    print("   inspección OK en", rep.get("inspect_seconds"), "s | guardado con Blender",
          rep.get("saved_with"), "| faltan externos:", rep.get("missing_external_count"))
    for s in rep.get("scenes", []):
        print("    - {} | frames {}-{} ({}) | {} {} | {}x{} | cam {} | out {} -> {}".format(
            s["name"], s["frame_start"], s["frame_end"], s["frame_count"],
            s.get("engine"), s.get("samples") or "", s.get("resolution_x"), s.get("resolution_y"),
            s.get("camera"), s.get("filepath_raw"), s.get("filepath_abs")))
    return {"id": fid, "report": rep}


def enqueue(file_id, scene, out_dir, extra=None, frames=None):
    ov = {"output_dir": out_dir}
    if extra:
        ov.update(extra)
    body = {"file_id": file_id, "scene": scene["name"], "overrides": ov}
    fr = frames or {"start": scene["frame_start"], "end": scene["frame_end"]}
    body["frames"] = fr
    print("== encolar:", scene["name"], "frames", fr, "->", out_dir)
    r = req("POST", "/api/jobs", body)
    jid = r["job"]["id"]
    j = wait_job(jid)
    if not j:
        print("    TIMEOUT esperando el trabajo")
        return None
    print("    estado:", j["status"], "| duración:", j.get("duration_s"), "s | outputs:",
          len(j.get("outputs") or []), "| preview:", (j.get("preview") or {}).get("video"))
    if j.get("error"):
        print("    error:", str(j["error"])[:400])
    for p in (j.get("outputs") or [])[:4]:
        print("      ·", p)
    return j


def mode_quick():
    info = add_and_inspect(TESTS + "/quick.blend")
    if not info:
        return False
    j = enqueue(info["id"], info["report"]["scenes"][0], TESTS + "/renders/quick_eevee")
    return bool(j and j["status"] == "done")


def mode_multi():
    info = add_and_inspect(TESTS + "/multi.blend")
    if not info:
        return False
    scenes = info["report"]["scenes"]
    if len(scenes) < 2:
        print("FALLO: se esperaban 2 escenas, hay", len(scenes))
        return False
    j = enqueue(info["id"], scenes[1], TESTS + "/renders/multi")
    if j and j.get("outputs"):
        ok = any("EscenaB" in str(p) for p in j["outputs"])
        print("    selección de escena (-S EscenaB):", "SI" if ok else "NO")
        return ok and j["status"] == "done"
    return False


def mode_cycles():
    info = add_and_inspect(TESTS + "/quick_cycles.blend")
    if not info:
        return False
    j = enqueue(info["id"], info["report"]["scenes"][0], TESTS + "/renders/cycles",
                extra={"device": "GPU", "samples": 16})
    return bool(j and j["status"] == "done")


def mode_real(args):
    path = args[0]
    info = add_and_inspect(path)
    if not info:
        return False
    if "render" not in args:
        return True
    scenes = info["report"]["scenes"]
    if not scenes:
        return False
    s = scenes[0]
    j = enqueue(info["id"], s, TESTS + "/renders/real",
                extra={"device": "GPU", "samples": 24},
                frames={"start": s["frame_start"], "end": s["frame_start"]})
    return bool(j and j["status"] == "done")


def req_status(method, path, body=None):
    """Como req() pero devuelve (status, json) sin lanzar en errores HTTP."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


def mode_format():
    """Overrides de formato de salida: EXR, video y edicion de la cola."""
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        print(("    OK   " if cond else "    FALLA") + " " + name +
              ((" -> " + str(detail)) if detail else ""))
        ok = ok and bool(cond)

    info = add_and_inspect(TESTS + "/quick.blend")
    if not info:
        return False
    scene = info["report"]["scenes"][0]
    caps = info["report"].get("capabilities") or {}
    check("el reporte trae el formato de la escena", bool(scene.get("file_format")),
          scene.get("file_format"))
    check("el reporte trae los formatos de Blender", len(caps.get("file_format") or []) > 5,
          len(caps.get("file_format") or []))
    cat = req("GET", "/api/formats")
    check("el catalogo sale de Blender", cat.get("source") == "blender", cat.get("source"))

    print("== editar el formato de un trabajo en cola")
    req("POST", "/api/queue/pause", {"paused": True})
    jid = req("POST", "/api/jobs", {"file_id": info["id"], "scene": scene["name"],
                                    "frames": {"start": 1, "end": 1},
                                    "overrides": {"output_dir": TESTS + "/renders/format"}})["job"]["id"]
    st, r = req_status("PATCH", "/api/jobs/" + jid,
                       {"overrides": {"output_dir": TESTS + "/renders/format", "format": "FFMPEG",
                                      "ffmpeg_container": "MKV", "exr_codec": "ZIP"}})
    ov = (r.get("job") or {}).get("overrides") or {}
    check("PATCH aplica el formato", ov.get("format") == "FFMPEG", ov)
    check("PATCH descarta lo que no aplica", "exr_codec" not in ov, ov)
    check("PATCH conserva la carpeta", bool(ov.get("output_dir")), ov)
    r = req("POST", "/api/jobs/format", {"format": "PNG", "color_depth": "16"})
    check("aplicar a toda la cola", jid in (r.get("changed") or []), r.get("changed"))
    req("DELETE", "/api/jobs/" + jid)
    req("POST", "/api/queue/pause", {"paused": False})

    print("== render forzando OpenEXR")
    j = enqueue(info["id"], scene, TESTS + "/renders/format",
                extra={"format": "OPEN_EXR", "color_depth": "16", "exr_codec": "ZIP", "samples": 8},
                frames={"start": 1, "end": 2})
    outs = (j or {}).get("outputs") or []
    check("render OK", bool(j and j["status"] == "done"), (j or {}).get("error"))
    check("escribe .exr", bool(outs) and all(p.lower().endswith(".exr") for p in outs), outs[:2])

    print("== render forzando video (FFmpeg/MKV)")
    j = enqueue(info["id"], scene, TESTS + "/renders/format",
                extra={"format": "FFMPEG", "ffmpeg_container": "MKV", "ffmpeg_codec": "H264",
                       "samples": 8},
                frames={"start": 1, "end": 4})
    outs = (j or {}).get("outputs") or []
    check("render de video OK", bool(j and j["status"] == "done"), (j or {}).get("error"))
    check("un solo .mkv", len(outs) == 1 and outs[0].lower().endswith(".mkv"), outs)
    return ok


def png_size(path):
    """Ancho/alto leidos de la cabecera IHDR del PNG."""
    with open(path, "rb") as fh:
        d = fh.read(33)
    assert d[1:4] == b"PNG", "no es PNG"
    return int.from_bytes(d[16:20], "big"), int.from_bytes(d[20:24], "big")


def mode_script():
    """Scripts de Python por trabajo: biblioteca, efecto real, copia congelada y fallo."""
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        print(("    OK   " if cond else "    FALLA") + " " + name +
              ((" -> " + str(detail)) if detail else ""))
        ok = ok and bool(cond)

    info = add_and_inspect(TESTS + "/quick.blend")
    if not info:
        return False
    scene = info["report"]["scenes"][0]
    out_dir = TESTS + "/renders/script"

    print("== biblioteca de scripts")
    st, r = req_status("POST", "/api/scripts",
                       {"name": "Media resolucion", "code": "sc.render.resolution_percentage = 50"})
    check("crear script", st == 200 and r.get("script", {}).get("id"), (st, r))
    sid = (r.get("script") or {}).get("id")
    if not sid:
        return False
    check("aparece en el estado",
          any(x["id"] == sid for x in req("GET", "/api/state").get("scripts", [])))

    print("== el script cambia el render de verdad")
    j = enqueue(info["id"], scene, out_dir, extra={"script_id": sid}, frames={"start": 1, "end": 1})
    outs = (j or {}).get("outputs") or []
    check("render OK", bool(j and j["status"] == "done"), (j or {}).get("error"))
    check("el trabajo guarda el nombre del script",
          (j or {}).get("overrides", {}).get("script_name") == "Media resolucion",
          (j or {}).get("overrides"))
    if outs:
        size = png_size(outs[0])
        check("resolucion a la mitad (160x90)", size == (160, 90), size)
    else:
        check("hay salida", False)

    print("== copia congelada: editar la biblioteca no toca lo ya encolado")
    req("POST", "/api/queue/pause", {"paused": True})
    jid = req("POST", "/api/jobs", {"file_id": info["id"], "scene": scene["name"],
                                    "frames": {"start": 1, "end": 1},
                                    "overrides": {"output_dir": out_dir, "script_id": sid}})["job"]["id"]
    req("PATCH", "/api/scripts/" + sid, {"code": "sc.render.resolution_percentage = 25"})
    ov = find(req("GET", "/api/state"), "jobs", jid)["overrides"]
    check("el encolado conserva su copia", "50" in (ov.get("script") or ""), ov.get("script"))
    req("DELETE", "/api/jobs/" + jid)

    print("== un script roto deja el trabajo en error")
    sid2 = req("POST", "/api/scripts", {"name": "Roto", "code": "raise RuntimeError('boom de prueba')"})["script"]["id"]
    req("POST", "/api/queue/pause", {"paused": False})
    j = enqueue(info["id"], scene, out_dir, extra={"script_id": sid2}, frames={"start": 1, "end": 1})
    check("el trabajo falla", bool(j and j["status"] == "error"), (j or {}).get("status"))
    log = req("GET", "/api/jobs/" + j["id"] + "/log?tail=400")["log"] if j else ""
    check("el traceback queda en el log", "boom de prueba" in log, log[-160:])
    check("el error del trabajo dice la excepcion, no 'Blender quit'",
          "boom de prueba" in str((j or {}).get("error")), (j or {}).get("error"))
    check("no escribio salidas", not (j or {}).get("outputs"), (j or {}).get("outputs"))

    for x in (sid, sid2):
        req_status("DELETE", "/api/scripts/" + x)
    check("borrar de la biblioteca",
          not any(y["id"] in (sid, sid2) for y in req("GET", "/api/state").get("scripts", [])))
    return ok


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    mode = sys.argv[1]
    st = req("GET", "/api/state")
    print("estado actual: files =", len(st["files"]), "| jobs =", len(st["jobs"]),
          "| blender:", (st.get("blender") or {}).get("version"))
    ok = False
    if mode == "quick":
        ok = mode_quick()
    elif mode == "multi":
        ok = mode_multi()
    elif mode == "cycles":
        ok = mode_cycles()
    elif mode == "format":
        ok = mode_format()
    elif mode == "script":
        ok = mode_script()
    elif mode == "real":
        if len(sys.argv) < 3:
            print("falta la ruta del .blend")
            return 1
        ok = mode_real(sys.argv[2:])
    else:
        print("modo desconocido:", mode)
        return 1
    print("RESULTADO:", "OK" if ok else "FALLO")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
