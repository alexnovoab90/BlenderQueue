# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
run.bat                                            # create .venv if missing, serve on 127.0.0.1:8777, open browser
.venv\Scripts\python.exe server.py --port 8888 --no-browser   # run without the launcher
.venv\Scripts\python.exe -m py_compile core/*.py server.py    # syntax check (no linter configured)
```

Smoke tests drive the real HTTP API against a **running** server and render actual frames.
Fixtures are generated once by Blender into the git-ignored `data/tests/`:

```bash
blender.exe -b --factory-startup --python tests/make_tests.py -- "%CD%/data/tests"
tests\run_smoke.bat quick            # also: multi | cycles | format
tests\run_smoke.bat real "G:/path/file.blend" [render]
.venv\Scripts\python.exe tests/api_smoke.py format          # single mode, server must be up
```

`BLENDQUEUE_URL` points the tests at another port; `BLENDQUEUE_BLENDER` overrides Blender detection.
There is no unit-test framework: a "single test" is one mode of `api_smoke.py`.

## Architecture

A local FastAPI server (`server.py`) plus two background threads started in its lifespan, both
sharing one `Store`:

- **`InspectorLane`** (`core/inspector.py`) — a queue of `.blend` files. For each one it runs
  `blender -b file.blend --python blender_side/inspect_blend.py -- out.json` and stores the
  resulting report on the file record. Runs in parallel with rendering.
- **`RenderWorker`** (`core/worker.py`) — one job at a time, forever. Picks the first `queued`
  job, builds the command, spawns Blender, parses stdout line by line for progress, then builds
  the ffmpeg preview and notifies.

The front-end (`static/`) is plain JS that polls `GET /api/state` once per second and re-renders
only when a computed signature changes. There is no build step and no websocket.

**The server never imports `bpy`.** Everything Blender-specific happens in a subprocess, which is
why BlendQueue works with any Blender build (3.x–5.x). Two consequences worth remembering:

1. `blender_side/inspect_blend.py` runs *inside* Blender and is the only place `bpy` is allowed.
   It reports each scene plus a `capabilities` block (the real enum values of that installation).
2. Per-job overrides are applied by Python source **generated** in `core/renderer.py`
   (`override_expr`) and passed via `--python-expr`. Every assignment is wrapped by `_guard()` so
   an unsupported value prints a line instead of killing the render. Keep that generated code
   ASCII-only — it travels through the Windows command line.

### State

`core/store.py` holds everything in one atomic JSON file (`data/state.json`): `settings`, `files`,
`jobs` and `caps`. All mutations go through the store under an `RLock` and save immediately; the
worker and inspector never share memory other than through it. On load, `_recover()` marks jobs
left `running` (server killed mid-render) as errored so they can be retried.

### Output formats

`core/formats.py` is the single source of truth for output formats: which ones the UI offers,
their options (depth, color mode, quality/compression, EXR codec, FFmpeg container/codec), the
extension each produces, and which are movies. `normalize()` drops options that do not apply to
the chosen format and is applied to every override that enters the API.

The catalog is filtered by `capabilities` from the last successful inspection (`/api/formats`),
so the UI never offers a format that the detected Blender lacks. The effective format of a job
(`overrides.format` or the scene's own) decides the `-o` pattern (`_####` for sequences, bare stem
for movies), the extension used to locate outputs, and whether a preview is possible.

### Render command

```
blender.exe -b file.blend -S Scene [--python-expr overrides] -o pattern -s START -e END -a
```

Argument order matters: `-S` selects the scene before the expression runs, and `-o` comes after so
it always wins. Outputs are collected from Blender's `Saved: '...'` lines; movies do not print
those, so `_scan_outputs()` falls back to scanning the folder filtered by expected extension,
stem and mtime.

## Conventions

- Code comments, UI strings, commit messages and `README.es.md` are in Spanish; `README.md` is the
  English entry point. Match the file you are editing.
- Comments explain *why* (especially Blender quirks, e.g. Blender 5 filtering `file_format` by
  `media_type`), never *what*.
- `static/index.html` cache-busts with `?v=N` on the CSS and JS: bump it when changing either.
- New API routes that change state are automatically covered by the local-only middleware in
  `server.py` (rejects non-local `Host`/`Origin`); do not add CORS headers.
