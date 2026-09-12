"""Encola un render corto del archivo real (película MKV) para validar el flujo completo."""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8777"
NAME = "3.2_Bolas_Animacion.blend"


def req(method, path, body=None, timeout=120):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


st = req("GET", "/api/state")
f = next((x for x in st["files"] if x["name"] == NAME and x["status"] == "ready"), None)
if not f:
    print("El archivo real no está listo todavía. files:")
    for x in st["files"]:
        print("  -", x["name"], "|", x["status"])
    sys.exit(1)

fstart, fend = 0, 4
body = {"file_id": f["id"], "scene": "Scene", "frames": {"start": fstart, "end": fend},
        "overrides": {"output_dir": "C:/Users/Alex/Developer/blendqueue/data/tests/renders/real"}}
r = req("POST", "/api/jobs", body)
jid = r["job"]["id"]
print("job encolado:", jid, "| frames", fstart, "-", fend)

t0, last = time.time(), None
while time.time() - t0 < 1500:
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
        print("outputs:", json.dumps(j.get("outputs"), ensure_ascii=False, indent=1))
        print("preview:", json.dumps(j.get("preview"), ensure_ascii=False))
        print("error:", j.get("error"))
        try:
            log = req("GET", "/api/jobs/" + jid + "/log?tail=50")["log"]
            print("--- log (cola):")
            print(log[-2200:])
        except Exception as exc:
            print("no log:", exc)
        break
    time.sleep(3)
else:
    print("TIMEOUT esperando el job")
