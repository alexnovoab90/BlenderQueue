"""Prueba directa de renderer.remux_preview con un MKV creado con ffmpeg."""
import os
import subprocess
import sys

sys.path.insert(0, "C:/Users/Alex/Developer/blendqueue")
from core import renderer  # noqa: E402

BASE = "C:/Users/Alex/Developer/blendqueue/data/tests/renders/quick_eevee"
src_mkv = BASE + "/_test_movie.mkv"
dest_mp4 = BASE + "/_test_preview.mp4"

# 1) armar un MKV con los PNGs del render rápido ya existente
cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
       "-framerate", "24", "-i", BASE + "/quick_Rapida_%04d.png",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", src_mkv]
r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
print("mkv creado:", os.path.exists(src_mkv), "|", (r.stderr or "")[-200:])
if not os.path.exists(src_mkv):
    sys.exit(1)

# 2) remux_preview
out = renderer.remux_preview(src_mkv, dest_mp4, log=print)
print("remux_preview ->", out)

# 3) verificar con ffprobe
if out:
    fp = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                         "format=duration,format_name:stream=codec_name,width,height",
                         "-of", "csv=p=0", dest_mp4], capture_output=True, text=True, timeout=60)
    print("ffprobe:", (fp.stdout or "").strip().replace("\n", " | "))
    print("RESULTADO:", "OK" if "h264" in (fp.stdout or "") else "REVISAR")
else:
    print("RESULTADO: FALLO")
