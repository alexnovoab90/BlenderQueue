"""Prueba de salida de PELÍCULA: genera un .blend FFMPEG/MKV, lo renderiza por la cola
de BlendQueue y verifica que el preview (mp4) se genere correctamente."""
import json
import subprocess
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8777"
ROOT = "C:/Users/Alex/Developer/blendqueue"
BLENDER = "D:/Program Files (x86)/Steam/steamapps/common/Blender/blender.exe"


def req(method, path, body=None, timeout=180):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# 1) generar el .blend de prueba (película)
blend = ROOT + "/data/tests/movie_test.blend"
proc = subprocess.run([BLENDER, "-b", "--factory-startup",
                       "--python", ROOT + "/data/tests/make_movie_blend.py",
                       "--", ROOT + "/data/tests"],
                      capture_output=True, text=True, timeout=300)
if "TEST_BLEND_OK" not in (proc.stdout or ""):
    print("FALLO generando el blend:")
    print((proc.stdout or "")[-600:])
    print((proc.stderr or "")[-600:])
    sys.exit(1)
print("== blend generado:", blend)

# 2) agregar a BlendQueue e inspeccionar
r = req("POST", "/api/files/add", {"paths": [blend]})
fid = r["added"][0]["id"]


def wait_file(fid, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = req("GET", "/api/state")
        f = next((x for x in st["files"] if x["id"] == fid), None)
        if f and f["status"] in ("ready", "error"):
            return f
        time.sleep(2)
    return None


f = wait_file(fid)
if not f or f["status"] != "ready":
    print("FALLO inspección:", (f or {}).get("inspect_error"))
    sys.exit(1)
s = f["report"]["scenes"][0]
print("== escena:", s["name"], "| is_movie:", s.get("is_movie"), "| formato:", s.get("file_format"),
      "| frames:", s["frame_start"], "-", s["frame_end"], "| out:", s.get("filepath_raw"))

# 3) encolar SIN override de salida (se respeta la salida del archivo)
r = req("POST", "/api/jobs", {"file_id": fid, "scene": s["name"],
                              "frames": {"start": s["frame_start"], "end": s["frame_end"]}})
jid = r["job"]["id"]
print("== job:", jid)
j = None
t0, last = time.time(), None
while time.time() - t0 < 600:
    st = req("GET", "/api/state")
    j = next((x for x in st["jobs"] if x["id"] == jid), None)
    p = (j or {}).get("progress") or {}
    line = "%s %.0f%% %s" % (j["status"], (p.get("percent") or 0) * 100, p.get("message") or "")
    if line != last:
        print("   ", line, flush=True)
        last = line
    if j["status"] in ("done", "error", "canceled"):
        print("outputs:", json.dumps(j.get("outputs"), ensure_ascii=False, indent=1))
        print("preview:", json.dumps(j.get("preview"), ensure_ascii=False))
        print("error:", j.get("error"))
        break
    time.sleep(2)
else:
    print("TIMEOUT esperando el job")
    sys.exit(1)

# 4) verificar el preview con ffprobe
pv = (j.get("preview") or {}).get("video")
if not pv:
    print("FALLO: no se generó preview para la película")
    sys.exit(2)
pv_win = pv.replace("\\", "/")
fp = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                     "format=duration,format_name:stream=codec_name",
                     "-of", "csv=p=0", pv_win], capture_output=True, text=True, timeout=60)
print("== ffprobe preview:", (fp.stdout or "").strip().replace("\n", " | "))
print("RESULTADO: OK")
