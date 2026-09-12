"""Encola un render de prueba en BlendQueue vía API.

Uso:
    python queue_real.py [nombre.blend] [frame_ini] [frame_fin] [subcarpeta_salida]
    Por defecto: 3.2_Bolas_Animacion.blend 0 4 real
"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8777"
TESTS = "C:/Users/Alex/Developer/blendqueue/data/tests"

NAME = sys.argv[1] if len(sys.argv) > 1 else "3.2_Bolas_Animacion.blend"
F0 = int(sys.argv[2]) if len(sys.argv) > 2 else 0
F1 = int(sys.argv[3]) if len(sys.argv) > 3 else 4
SUB = sys.argv[4] if len(sys.argv) > 4 else "real"
OUT = TESTS + "/renders/" + SUB


def req(method, path, body=None, timeout=120):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


st = req("GET", "/api/state")
f = next((x for x in st["files"] if x["name"] == NAME and x["status"] == "ready"), None)
if not f:
    print("El archivo no está listo todavía. files:")
    for x in st["files"]:
        print("  -", x["name"], "|", x["status"])
    sys.exit(1)

scene = f["report"]["scenes"][0]["name"]
body = {"file_id": f["id"], "scene": scene, "frames": {"start": F0, "end": F1},
        "overrides": {"output_dir": OUT}}
r = req("POST", "/api/jobs", body)
jid = r["job"]["id"]
print("job:", jid, "|", NAME, "| escena:", scene, "| frames", F0, "-", F1, "->", OUT)

t0, last = time.time(), None
while time.time() - t0 < 2400:
    st = req("GET", "/api/state")
    j = next((x for x in st["jobs"] if x["id"] == jid), None)
    if not j:
        time.sleep(2)
        continue
    p = j.get("progress") or {}
    line = "%s %.1f%% %s" % (j["status"], (p.get("percent") or 0) * 100, p.get("message") or "")
    if line != last:
        print("   ", line, flush=True)
        last = line
    if j["status"] in ("done", "error", "canceled"):
        print("duración:", j.get("duration_s"), "s | outputs:", len(j.get("outputs") or []))
        for p2 in (j.get("outputs") or [])[:4]:
            print("   ·", p2)
        print("preview:", (j.get("preview") or {}).get("video"))
        print("error:", j.get("error"))
        break
    time.sleep(2)
else:
    print("TIMEOUT esperando el job")
