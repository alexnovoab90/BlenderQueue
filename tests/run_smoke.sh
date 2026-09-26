#!/usr/bin/env bash
# BlendQueue smoke tests. The server must be running (run.sh).
#   tests/run_smoke.sh quick | multi | cycles | format | script | overwrite | size | locate | fs | pause
#   tests/run_smoke.sh real "/path/file.blend" [render]
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f "data/tests/quick.blend" ]; then
  echo "[BlendQueue] The test .blend files are missing: generate them with"
  echo "    blender -b --factory-startup --python tests/make_tests.py -- \"$PWD/data/tests\""
  exit 1
fi

exec .venv/bin/python tests/api_smoke.py "$@"
