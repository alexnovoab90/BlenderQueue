# BlendQueue

**A local render queue for Blender.** Drop in your `.blend` files, BlendQueue inspects every
scene headlessly (frame range, engine, samples, camera, output format and path), and you choose
what renders. A sequential worker runs the jobs with Blender in background mode, streams live
progress to your browser, builds an MP4 preview with ffmpeg and fires a Windows notification
when each job finishes.

No cloud, no accounts, no telemetry: a FastAPI server bound to `127.0.0.1` and a plain
HTML/CSS/JS front-end with no build step.

*[Léeme en español](README.es.md) — the interface is in Spanish.*

![BlendQueue](docs/screenshot.png)

## Why

Rendering several `.blend` files in a row usually means babysitting a terminal, or opening each
file just to check its frame range and output settings. BlendQueue keeps a queue for you: it
reads what every scene is actually configured to do, lets you override the parts you want
(frames, engine, samples, GPU/CPU, resolution, **output format**, destination folder) and runs
one job at a time so Blender never fights itself for the GPU.

## Requirements

| | |
|---|---|
| OS | Windows 10/11 — desktop toasts and "open folder" use Windows APIs |
| Blender | 3.x, 4.x or 5.x (auto-detected: installer, Steam, `PATH`, or `BLENDQUEUE_BLENDER`) |
| Python | 3.10+ (`run.bat` creates the virtualenv for you) |
| ffmpeg | optional, on `PATH` — only needed for MP4 previews |

The core (inspection, queue, rendering) is plain Python and would port to Linux/macOS by
replacing three Windows-specific bits: `os.startfile`, `taskkill` and the toast notifier.

## Install and run

```bash
git clone https://github.com/alexnovoab90/BlenderQueue.git
```

Then double-click **`run.bat`**. It creates `.venv` (with [uv](https://github.com/astral-sh/uv)
if available, otherwise `pip`), installs the dependencies and opens
<http://127.0.0.1:8777>. If the server is already running it just opens the browser.

Other port:

```bash
.venv\Scripts\python.exe server.py --port 8888 --no-browser
```

## Adding files

- **Pick a path on this machine** — registers the `.blend` *in place*. Recommended: relative
  texture paths keep working. You can register a whole folder and every `.blend` inside is added.
- **Drag and drop** — copies the file into `data/uploads/`. Careful with projects that use
  relative textures: the copy breaks them.

Inspection runs in parallel with rendering, so adding files never stalls the queue.

## Output format overrides

Every scene shows the format stored in the `.blend` (PNG 8, OpenEXR multilayer 32, Video .mp4…).
You can override it **per job**, without ever modifying the `.blend`:

- **Before queueing** — under *Overrides…* on each scene.
- **Once queued** — the *Formato* button on any queued job, or **Formato de salida…** in the
  queue header to apply one format to the whole queue at once. Handy when you queue files from
  different projects and one of them was saved with a different format: the queue header warns
  you (`formatos mezclados: …`) and one click unifies everything.

Available options follow what your Blender build reports: file format, color depth, color mode,
quality/compression, EXR codec, and FFmpeg container plus video codec. Switching to a movie
format makes BlendQueue write a single file instead of a numbered sequence, and the browser
preview adapts (linear EXR is tone-mapped by ffmpeg; multilayer EXR has no preview because
ffmpeg cannot decode it).

## How it renders

```
blender.exe -b "file.blend" -S "Scene" [--python-expr overrides] -o "output####" -s START -e END -a
```

- Without an output override, the folder saved in the `.blend` is used as-is.
- With an override, files are written as `<blend>_<scene>_####.<ext>` in the folder you picked.
- Engine, samples and device come from the file unless overridden per job.
- Overrides are applied by a generated Python snippet that runs inside Blender. Every assignment
  is guarded, so an unsupported value logs a line instead of killing the render (that also
  absorbs the `BLENDER_EEVEE` / `BLENDER_EEVEE_NEXT` rename across versions).
- Cancelling kills the Blender process (`taskkill`); retry re-queues; ↑/↓ reorder the queue.
- One render at a time — Blender already saturates the GPU/CPU.

## Project layout

```
server.py                       FastAPI server + API (entry point)
core/config.py                  paths, Blender detection, cached version check
core/store.py                   persistent state (atomic JSON): files, jobs, settings
core/inspector.py               inspection lane: runs Blender headless per .blend
core/worker.py                  sequential render worker: spawn, progress, previews, notify
core/renderer.py                command building, override codegen, progress parsing, ffmpeg
core/formats.py                 output format catalog and override validation
blender_side/inspect_blend.py   runs INSIDE Blender, reports scenes and capabilities as JSON
static/                         web interface (no build step)
tests/                          smoke tests and .blend generator
data/                           state, per-job logs, uploads, previews (git-ignored)
```

The server never imports `bpy`: everything Blender-specific happens in a subprocess, which is
why BlendQueue works with whatever Blender build you point it at.

## Tests

The smoke tests drive the real HTTP API against a running server and render actual frames.
Generate the fixtures once:

```bash
blender.exe -b --factory-startup --python tests/make_tests.py -- "%CD%/data/tests"
```

Then, with BlendQueue running:

```bash
tests\run_smoke.bat quick
```

Modes: `quick` (EEVEE sequence), `multi` (scene selection via `-S`), `cycles` (GPU),
`format` (format overrides: EXR, video, editing a queued job, bulk apply), and
`real "G:/path/file.blend" [render]` for one of your own files.

## Troubleshooting

- **Blender not found** → Settings → path to `blender.exe`, or set `BLENDQUEUE_BLENDER`.
- **Pink textures / missing files** → add the `.blend` *by path* instead of dragging it, or pack
  the textures. The inspection report counts missing external files.
- **Port busy** → `run.bat` detects a running instance and just opens the browser.
- **Closing the server window stops the queue** → in-flight jobs are marked as interrupted and
  can be retried. Prefer the ⏻ button in the header for a clean shutdown.

## Security note

BlendQueue is a local tool: it lists folders, opens Explorer windows and launches Blender.
The server binds to `127.0.0.1` only, and rejects requests whose `Host` or `Origin` is not local,
so other pages in your browser cannot drive it. Do not expose it to a network.

## License

MIT — see [LICENSE](LICENSE). Contributions welcome: issues and PRs at
<https://github.com/alexnovoab90/BlenderQueue>.
