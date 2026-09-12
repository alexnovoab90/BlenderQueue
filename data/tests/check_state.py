"""Resumen rápido del estado de BlendQueue para depurar sin abrir el navegador."""
import json
import urllib.request

d = json.load(urllib.request.urlopen("http://127.0.0.1:8777/api/state", timeout=30))
print("== files ==")
for f in d["files"]:
    extra = (" | ERROR: " + (f.get("inspect_error") or "")[:120]) if f.get("status") == "error" else ""
    print("  -", f["name"], "|", f["status"], "|", f.get("id"), extra)
print("== inspector ==", d.get("inspector"))
print("== worker ==", d.get("worker"))
print("== jobs ==")
for j in d["jobs"]:
    p = j.get("progress") or {}
    print("  -", j["id"], j["file_name"], "|", j["scene"], "|", j["status"],
          "| pct:", round((p.get("percent") or 0) * 100, 1), "| outs:", len(j.get("outputs") or []))
for f in d["files"]:
    rep = f.get("report") or {}
    if "Bolas" in f["name"] and rep.get("scenes"):
        print("== REPORTE:", f["name"], "| inspección:", rep.get("inspect_seconds"), "s | guardado con", rep.get("saved_with"))
        for s in rep.get("scenes", []):
            print("   escena:", s.get("name"), "| frames", s.get("frame_start"), "-", s.get("frame_end"),
                  "(%s)" % s.get("frame_count"), "|", s.get("engine"), s.get("samples"), "|",
                  s.get("resolution_x"), "x", s.get("resolution_y"), "| cam:", s.get("camera"),
                  "| out:", s.get("filepath_raw"))
            print("      -> abs:", s.get("filepath_abs"))
        print("   faltan externos:", rep.get("missing_external_count"),
              "| crudos:", rep.get("missing_raw_count"),
              "| objetos:", (rep.get("counts") or {}).get("objects"))
