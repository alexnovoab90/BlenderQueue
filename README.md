# BlendQueue

**A local render queue for Blender.** Drop in your `.blend` files, BlendQueue inspects every
scene headlessly (frame range, engine, samples, camera, output format and path), and you choose
what renders. A sequential worker runs the jobs with Blender in background mode, shows live
progress in your browser (including how long the last frame took), builds an MP4 preview with
ffmpeg and fires a Windows notification when each job finishes.

No cloud, no accounts, no telemetry: a FastAPI server bound to `127.0.0.1` and a plain
HTML/CSS/JS front-end with no build step.

*[Léeme en español](README.es.md)*

![BlendQueue](docs/screenshot.png)

The interface is in **English** by default; the header has an **EN / ES** switch and the choice
is remembered per browser.

## Why

Rendering several `.blend` files in a row usually means babysitting a terminal, or opening each
file just to check its frame range and output settings. BlendQueue keeps a queue for you: it
reads what every scene is actually configured to do, lets you override the parts you want
(frames, engine, samples, GPU/CPU, **size in pixels**, **output format**, destination folder) and runs
one job at a time so Blender never fights itself for the GPU.

## Requirements

| | |
|---|---|
| OS | Windows 10/11, macOS or Linux — see [Platform support](#platform-support) |
| Blender | 3.x, 4.x or 5.x (auto-detected: installer, Steam, `PATH`, or `BLENDQUEUE_BLENDER`) |
| Python | 3.10+ (`run.bat` / `run.sh` creates the virtualenv for you) |
| ffmpeg | optional, on `PATH` — only needed for MP4 previews |

## Platform support

Everything OS-specific lives in one file, `core/system.py`: opening a folder, killing a render
together with its children, where Blender is installed and the roots of the file browser.

| | Windows | macOS | Linux |
|---|---|---|---|
| Queue, render, previews, scripts | yes | yes | yes |
| Open the output folder | Explorer | `open` | `xdg-open` |
| Pause a render in progress | process suspend | `SIGSTOP` / `SIGCONT` | `SIGSTOP` / `SIGCONT` |
| Desktop notification | toast | `osascript` | `notify-send` |
| Launcher | `run.bat` | `./run.sh` | `./run.sh` |

**Verified on Windows 11** (full smoke suite) **and on Linux** (Ubuntu under WSL: browser roots,
Blender lookup, killing a render with its children, pausing and resuming one, and graceful
degradation without a desktop).
**macOS is written but untested** — if you run it there, reports are welcome.

Without a desktop session the two integration features return a clear message instead of failing,
so BlendQueue still renders on a headless box.

## Install and run

```bash
git clone https://github.com/alexnovoab90/BlenderQueue.git
```

Then double-click **`run.bat`** (Windows) or run **`./run.sh`** (macOS and Linux). Either one
creates `.venv` (with [uv](https://github.com/astral-sh/uv) if available, otherwise `pip`),
installs the dependencies and opens <http://127.0.0.1:8777>. If the server is already running it
just opens the browser.

Other port:

```bat
.venv\Scripts\python.exe server.py --port 8888 --no-browser    :: Windows
```

```bash
.venv/bin/python server.py --port 8888 --no-browser            # macOS and Linux
```

## Adding files

- **Pick a path on this computer…** — registers the `.blend` *in place*. You can register a
  whole folder and every `.blend` inside is added.
- **Drag and drop** (or *choose files…*) — a browser never tells a page where a dropped file
  lives, so BlendQueue looks for it first: same name, size and date, in the folders you already
  work in (those of your other files and recent render folders, and the folders next to them).
  Found, it is rendered in place. Not found, you are asked to find it on disk — or to upload a
  copy into `data/uploads/` anyway.

A copy cannot see the textures and linked `.blend` files next to the original: Blender resolves
`//` paths against the copy's folder and renders them missing. Each file card warns about missing
external files, and an uploaded copy gets **Locate the original…**, which swaps it for the
original (queued jobs follow it, the copy is deleted). Removing an uploaded copy from the list
deletes it as well; your original is never touched.

Inspection runs in parallel with rendering, so adding files never stalls the queue.

## Output size

*Overrides…* → **Size** takes the width and height of the render in pixels — whatever you need,
1280 × 720 or 1080 × 1350 alike. Leave one side empty to keep the `.blend`'s aspect ratio. What
you type is the size of the file: the `.blend`'s resolution percentage is reset to 100 %.

Video codecs such as H.264 need an even width and height. With an odd size Blender cannot start
the encoder and exits as if all went well, having written nothing, so BlendQueue rounds an odd
video size down to even (one pixel at most) and says so in the log. The scene tag always shows
the size that will actually be rendered.

## Output format overrides

Every scene shows the format stored in the `.blend` (PNG 8, OpenEXR multilayer 32, Video .mp4…).
You can override it **per job**, without ever modifying the `.blend`:

- **Before queueing** — under *Overrides…* on each scene.
- **Once queued** — the *Format* button on any queued job, or **Output format…** in the queue
  header to apply one format to the whole queue at once. Handy when you queue files from
  different projects and one of them was saved with a different format: the queue header warns
  you (`mixed formats: …`) and one click unifies everything.

Available options follow what your Blender build reports: file format, color depth, color mode,
quality/compression, EXR codec, and FFmpeg container plus video codec. Switching to a movie
format makes BlendQueue write a single file instead of a numbered sequence, and the browser
preview adapts (linear EXR is tone-mapped by ffmpeg; multilayer EXR has no preview because
ffmpeg cannot decode it).

## Existing frames

Before queueing, BlendQueue looks at the output folder. If frames are already there it asks what
to do, because Blender does either thing silently:

- **Overwrite** — render everything again, replacing the files.
- **Skip existing** — render only what is missing, which is how you resume an interrupted sequence.

A scene whose `.blend` has Overwrite off carries a **no overwrite** tag, and the same choice sits
in *Overrides…* as *Existing frames*. If a render ends up writing nothing because every frame was
skipped, the job says so instead of reporting a silent success with zero files.

## Python scripts per job

Anything the built-in overrides don't cover, a script can: delete duplicate materials, swap the
world for an HDRI, build a compositing setup, disable a collection.

Keep a named library (**Scripts** in the header) and apply a script the same way you apply a
format — on a scene before queueing, on a queued job, or to the whole queue at once. It runs
inside Blender right before the render, *after* the app's own overrides, so it can change
anything, including what BlendQueue just set.

Your code receives `bpy`, `sc` (this job's scene, resolved by name) and `blend_path`, and runs on
Blender's in-memory copy: **the .blend is never modified**. If it raises, the job fails with the
exception on its error line and the full traceback in its log — no half-configured 500-frame
render. Exactly what ran is kept at `data/scripts/job_<id>.py`.

Applying a script copies it into the job, so editing the library later never changes what an
already-queued job will run.

```python
# swap the world for an HDRI
img = bpy.data.images.load(r"D:\hdri\sunrise_4k.exr", check_existing=True)
world = sc.world or bpy.data.worlds.new("HDRI")
sc.world = world
world.use_nodes = True
nt = world.node_tree
nt.nodes.clear()
env = nt.nodes.new("ShaderNodeTexEnvironment"); env.image = img
bg = nt.nodes.new("ShaderNodeBackground")
out = nt.nodes.new("ShaderNodeOutputWorld")
nt.links.new(env.outputs["Color"], bg.inputs["Color"])
nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
```

## How it renders

```
blender.exe -b "file.blend" -S "Scene" [--python-exit-code 1] [--python-expr overrides]
            [--python data/scripts/job_<id>.py] --python-expr final-checks
            -o "output####" -s START -e END -a
```

The bracketed parts only appear when that job needs them.

- Without an output override, the folder saved in the `.blend` is used as-is.
- With an override, files are written as `<blend>_<scene>_####.<ext>` in the folder you picked.
  The folder picker has **New folder…** to create one on the spot.
- Engine, samples and device come from the file unless overridden per job.
- Overrides are applied by a generated Python snippet that runs inside Blender. Every assignment
  is guarded, so an unsupported value logs a line instead of killing the render (that also
  absorbs the `BLENDER_EEVEE` / `BLENDER_EEVEE_NEXT` rename across versions).
- A per-job script is passed as `--python` *after* the expression, together with
  `--python-exit-code 1` so that a script raising an exception fails the job.
- A last expression runs after everything else: it rounds odd video sizes to even and prints the
  engine, samples and size Blender is about to use. The job card shows that line (*In Blender:
  EEVEE · 10 spp · 1280×720 px*), so an override that did not apply cannot go unnoticed.
- Blender reports some failures and still exits with code 0 — a video encoder that cannot start,
  for one. A job that wrote nothing ends in **error** with Blender's own message, unless the
  frames were skipped on purpose (see [Existing frames](#existing-frames)).
- **⏸ Pause** on the job in progress freezes Blender where it is: the process is suspended and
  keeps its memory (VRAM included), and **▶ Resume** continues the very same frame. Paused time
  counts neither as render time nor toward the time per frame. **Pause queue** in the header is a
  different thing: it only stops the next job from starting.
- Cancelling kills Blender together with its child processes, paused or not; retry re-queues;
  ↑/↓ reorder the queue.
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
core/system.py                  everything OS-specific: open folder, kill tree, Blender lookup
core/notifier.py                desktop notifications (toast / osascript / notify-send)
blender_side/inspect_blend.py   runs INSIDE Blender, reports scenes and capabilities as JSON
static/                         web interface (no build step)
static/i18n.js                  interface languages (English in the code + a Spanish map)
tests/                          smoke tests and .blend generator
run.bat, run.sh                 launchers: create the venv if missing and serve the app
data/                           state, per-job logs and scripts, uploads, previews (git-ignored)
```

The server never imports `bpy`: everything Blender-specific happens in a subprocess, which is
why BlendQueue works with whatever Blender build you point it at.

## Tests

The smoke tests drive the real HTTP API against a running server and render actual frames.
Generate the fixtures once:

```bat
blender.exe -b --factory-startup --python tests/make_tests.py -- "%CD%/data/tests"
```

Then, with BlendQueue running:

```bat
tests\run_smoke.bat quick
```

Modes: `quick` (EEVEE sequence), `multi` (scene selection via `-S`), `cycles` (GPU),
`format` (format overrides: EXR, video, editing a queued job, bulk apply),
`script` (per-job Python: library, real effect on the render, frozen copy, failure),
`overwrite` (existing frames: preflight, skipping them, forcing the overwrite),
`size` (size in pixels, odd video sizes, a render that writes nothing with exit code 0),
`locate` (dropped files found on disk, uploaded copies swapped for their originals),
`fs` (creating a folder from the picker), `pause` (pausing the render in progress, resuming it,
cancelling it while paused), and `real "G:/path/file.blend" [render]` for one of your own files.

To test while BlendQueue is busy rendering, start a second server on its own data folder so the
tests never touch your queue:

```bash
BLENDQUEUE_DATA=/tmp/bq-test .venv/bin/python server.py --port 8790 --no-browser
BLENDQUEUE_URL=http://127.0.0.1:8790 .venv/bin/python tests/api_smoke.py size
```

## Troubleshooting

- **Blender not found** → Settings → path to `blender.exe`, or set `BLENDQUEUE_BLENDER`.
- **Pink textures / missing files** → read the warning on the file card. An uploaded copy loses
  every path relative to the original: use **Locate the original…**. Otherwise the files are
  missing next to the original too — fix the paths in Blender or pack them.
- **"Blender rendered nothing: …"** → that is Blender's own error (a codec that does not accept
  the size, no camera…). *View log* has the full output.
- **Port busy** → the launcher detects a running instance and just opens the browser.
- **"This system cannot open a file manager" (Linux)** → install `xdg-utils`, or use the path
  shown in the job. Same idea for notifications: they need `notify-send` (`libnotify-bin`).
- **Closing the server window stops the queue** → in-flight jobs are marked as interrupted and
  can be retried. Prefer the ⏻ button in the header for a clean shutdown.

## Security note

BlendQueue is a local tool: it lists folders, opens Explorer windows and launches Blender.
The server binds to `127.0.0.1` only, and rejects requests whose `Host` or `Origin` is not local,
so other pages in your browser cannot drive it. Do not expose it to a network.

## License

MIT — see [LICENSE](LICENSE). Contributions welcome: issues and PRs at
<https://github.com/alexnovoab90/BlenderQueue>.
