#!/usr/bin/env bash
# BlendQueue launcher for macOS and Linux (see run.bat for Windows).
# Creates the virtual environment on first run, then serves on 127.0.0.1:8777.
set -euo pipefail
cd "$(dirname "$0")"

PY=".venv/bin/python"
PORT="${BLENDQUEUE_PORT:-8777}"
URL="http://127.0.0.1:$PORT/"

if [ ! -x "$PY" ]; then
  echo "[BlendQueue] Preparing the virtual environment..."
  if command -v uv >/dev/null 2>&1; then
    uv venv .venv
    uv pip install --python "$PY" -r requirements.txt
  else
    python3 -m venv .venv
    "$PY" -m pip install --upgrade pip
    "$PY" -m pip install -r requirements.txt
  fi
fi

open_browser() {
  if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 &
  elif command -v open >/dev/null 2>&1; then open "$URL" >/dev/null 2>&1 &
  fi
}

# Already running? Just open the browser, like run.bat does.
if "$PY" -c "import socket,sys; s=socket.socket(); s.settimeout(0.4); sys.exit(0 if s.connect_ex(('127.0.0.1',$PORT))==0 else 1)"; then
  open_browser
  exit 0
fi

echo "[BlendQueue] Starting at $URL  (to stop: the Quit button in the app, or Ctrl+C here)"
exec "$PY" server.py --port "$PORT"
