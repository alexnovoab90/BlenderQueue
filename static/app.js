"use strict";

/* ============================ helpers ============================ */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

let state = null;
let queueSig = null;
let filesSig = null;
const openDetails = new Set();
const overrideDraft = {};
const prevStatuses = {};

function fmtBytes(n) {
  if (n == null) return "?";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0; n = Number(n);
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return n.toFixed(n >= 100 ? 0 : 1) + " " + u[i];
}

function fmtDur(s) {
  if (s == null) return "—";
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  const mm = String(m).padStart(2, "0"), ss = String(x).padStart(2, "0");
  return h ? h + ":" + mm + ":" + ss : m + ":" + ss;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function engineLabel(e) {
  if (!e) return "?";
  if (e === "CYCLES") return "Cycles";
  if (e.includes("EEVEE")) return "EEVEE";
  if (e.includes("WORKBENCH")) return "Workbench";
  return e;
}

async function api(path, opts = {}) {
  const o = Object.assign({ headers: { "Content-Type": "application/json" } }, opts);
  const r = await fetch(path, o);
  if (!r.ok) {
    let msg = "HTTP " + r.status;
    try { const j = await r.json(); msg = j.detail || JSON.stringify(j); } catch (e) { }
    throw new Error(msg);
  }
  return r.json();
}

function toast(msg, kind = "info", ms = 5000) {
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 400); }, ms);
}

let actx = null;
function beep() {
  try {
    actx = actx || new (window.AudioContext || window.webkitAudioContext)();
    const o = actx.createOscillator(), g = actx.createGain();
    o.type = "sine"; o.frequency.value = 880;
    g.gain.setValueAtTime(0.0001, actx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.1, actx.currentTime + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, actx.currentTime + 0.4);
    o.connect(g); g.connect(actx.destination);
    o.start(); o.stop(actx.currentTime + 0.45);
  } catch (e) { }
}

/* ============================ output formats ============================ */
/* The server builds the catalog from the detected Blender's own enums, so the
   UI never offers a format that install does not support. */
const FORMAT_KEYS = ["format", "color_depth", "color_mode", "quality",
                     "exr_codec", "ffmpeg_container", "ffmpeg_codec"];
let FMT = null;
let fmtKey = null;

async function loadFormats(key) {
  try {
    FMT = await api("/api/formats");
    fmtKey = key;
    filesSig = null;   // redraw the scenes, now with the format selects
    queueSig = null;
  } catch (e) { /* retried on the next tick */ }
}

function fmtSpec(id) {
  return ((FMT && FMT.formats) || []).find(f => f.id === id) || null;
}

function fmtExt(id, container) {
  const s = fmtSpec(id);
  if (!s) return "";
  if (s.ffmpeg) {
    const c = ((FMT && FMT.ffmpeg_containers) || []).find(x => x.id === (container || "MPEG4"));
    return (c && c.ext) || ".mp4";
  }
  return s.ext || "";
}

function fmtLabel(id, container, depth) {
  const s = fmtSpec(id);
  if (!s) return id || "—";
  if (s.ffmpeg) return tf("Video {ext}", { ext: fmtExt(id, container) });
  let txt = t(s.label);
  if (depth && (s.depths || []).length > 1) txt += " " + depth;
  return txt;
}

function optionList(items, value, blank) {
  let h = blank ? '<option value="">' + esc(blank) + "</option>" : "";
  for (const it of items) {
    const id = (it && it.id !== undefined) ? it.id : it;
    const label = (it && it.label !== undefined) ? it.label : id;
    h += '<option value="' + esc(id) + '"' +
      (String(value ?? "") === String(id) ? " selected" : "") + ">" + esc(t(String(label))) + "</option>";
  }
  return h;
}

/** Format controls (the same ones in the scene overrides and in the modal). */
function formatFields(v) {
  v = v || {};
  const all = (FMT && FMT.formats) || [];
  const common = all.filter(f => f.common);
  const rest = all.filter(f => !f.common);
  let opts = '<option value="">' + esc(t("(the file's one)")) + '</option>' +
    optionList(common, v.format, null);
  if (rest.length) opts += '<optgroup label="' + esc(t("Others")) + '">' +
    optionList(rest, v.format, null) + "</optgroup>";
  return '' +
    '<label class="fmt-opt"><span>' + esc(t("Format")) + '</span>' +
      '<select class="input fmt-format">' + opts + '</select></label>' +
    '<label class="fmt-opt hidden" data-need="depth"><span>' + esc(t("Depth")) + '</span>' +
      '<select class="input fmt-depth"></select></label>' +
    '<label class="fmt-opt hidden" data-need="mode"><span>' + esc(t("Color")) + '</span>' +
      '<select class="input fmt-mode"></select></label>' +
    '<label class="fmt-opt hidden" data-need="quality"><span class="fmt-quality-label">' + esc(t("Quality %")) + '</span>' +
      '<input class="input num fmt-quality" type="number" min="0" max="100" style="width:72px" value="' +
        esc(v.quality ?? "") + '"></label>' +
    '<label class="fmt-opt hidden" data-need="exr"><span>' + esc(t("EXR codec")) + '</span>' +
      '<select class="input fmt-exr">' +
        optionList((FMT && FMT.exr_codecs) || [], v.exr_codec, t("(default)")) + '</select></label>' +
    '<label class="fmt-opt hidden" data-need="ffmpeg"><span>' + esc(t("Container")) + '</span>' +
      '<select class="input fmt-container">' +
        optionList((FMT && FMT.ffmpeg_containers) || [], v.ffmpeg_container || "MPEG4", null) + '</select></label>' +
    '<label class="fmt-opt hidden" data-need="ffmpeg"><span>' + esc(t("Video codec")) + '</span>' +
      '<select class="input fmt-codec">' +
        optionList((FMT && FMT.ffmpeg_codecs) || [], v.ffmpeg_codec, t("(default)")) + '</select></label>';
}

/** Shows only the options that apply to the chosen format. */
function syncFormatFields(root, v) {
  if (!root) return;
  v = v || {};
  const sel = root.querySelector(".fmt-format");
  if (!sel) return;
  const s = fmtSpec(sel.value);
  const depths = (s && s.depths) || [];
  const modes = (s && s.modes) || [];
  const show = (need, on) => root.querySelectorAll('[data-need="' + need + '"]')
    .forEach(el => el.classList.toggle("hidden", !on));
  show("depth", depths.length > 1);
  show("mode", modes.length > 0);
  show("quality", !!(s && s.quality_kind));
  show("exr", !!(s && s.exr));
  show("ffmpeg", !!(s && s.ffmpeg));

  const dsel = root.querySelector(".fmt-depth");
  if (dsel) {
    const want = v.color_depth !== undefined ? v.color_depth : dsel.value;
    dsel.innerHTML = optionList(depths.map(d => ({ id: d, label: d + " " + t("bits") })), want, t("(default)"));
  }
  const msel = root.querySelector(".fmt-mode");
  if (msel) {
    const want = v.color_mode !== undefined ? v.color_mode : msel.value;
    const avail = ((FMT && FMT.color_modes) || []).filter(m => modes.includes(m.id));
    msel.innerHTML = optionList(avail, want, t("(default)"));
  }
  const ql = root.querySelector(".fmt-quality-label");
  if (ql) ql.textContent = t((s && s.quality_label) || "Quality %");
}

/** Reads the visible controls and builds the format override. */
function readFormat(root) {
  const out = {};
  if (!root) return out;
  const sel = root.querySelector(".fmt-format");
  const fmt = sel ? sel.value : "";
  if (!fmt) return out;               // "(the file's one)": no override
  out.format = fmt;
  const g = q => {
    const el = root.querySelector(q);
    return (el && !el.closest(".hidden")) ? el.value : "";
  };
  const depth = g(".fmt-depth"); if (depth) out.color_depth = depth;
  const mode = g(".fmt-mode"); if (mode) out.color_mode = mode;
  const q = g(".fmt-quality"); if (q !== "") out.quality = Number(q);
  const exr = g(".fmt-exr"); if (exr) out.exr_codec = exr;
  const cont = g(".fmt-container"); if (cont) out.ffmpeg_container = cont;
  const codec = g(".fmt-codec"); if (codec) out.ffmpeg_codec = codec;
  return out;
}

/* ============================ Python scripts ============================ */
function scriptsList() { return (state && state.scripts) || []; }

function scriptById(id) { return scriptsList().find(s => s.id === id) || null; }

function scriptsSig() { return scriptsList().map(s => s.id + ":" + s.name).join(","); }

function scriptOptions(selected) {
  return optionList(scriptsList().map(s => ({ id: s.id, label: s.name })), selected, t("(none)"));
}

/* ============================ main tick ============================ */
async function tick() {
  try {
    state = await api("/api/state");
  } catch (e) {
    return; // server down: it retries by itself
  }
  if (!FMT || state.formats_key !== fmtKey) await loadFormats(state.formats_key);
  renderStatus(state);
  renderFiles(state);
  renderQueue(state);
  if (!$("#settingsModal").classList.contains("hidden")) fillSettings();
}

setInterval(tick, 1000);
tick();

/* ============================ header ============================ */
function renderStatus(st) {
  const b = $("#blenderBadge");
  if (st.blender.ok) {
    b.textContent = "Blender: " + (st.blender.version || "OK");
    b.className = "badge ok";
    b.title = st.blender.path || "";
  } else {
    b.textContent = t("Blender: not found");
    b.className = "badge err";
    b.title = st.blender.error || "";
  }
  const pause = $("#btnPause");
  pause.textContent = st.worker.paused ? t("Resume queue") : t("Pause queue");
  pause.classList.toggle("warn", !!st.worker.paused);
}

/* ============================ files ============================ */
function renderFiles(st) {
  const insp = st.inspector && st.inspector.current_file_id;
  $("#filesCount").textContent = st.files.length ? tf("{n} file(s)", { n: st.files.length }) : "";
  const sig = JSON.stringify(st.files.map(f => ({
    i: f.id, s: f.status, e: f.inspect_error, t: f.inspected_at,
    r: f.report ? f.report.inspect_seconds : null
  }))) + "|" + (insp || "") + "|" + scriptsSig();
  if (sig === filesSig) return;
  filesSig = sig;
  const el = $("#filesList");
  el.innerHTML = st.files.map(f => fileCard(f, insp === f.id)).join("")
    || '<div class="empty muted">' +
       esc(t("No files yet. Drop a .blend above or use “Pick a path on this computer…”.")) + '</div>';
  // The format selects depend on the chosen format: sync them after drawing.
  $$(".ov-format", el).forEach(root => {
    const row = root.closest(".scene");
    const d = (row && overrideDraft[row.dataset.file + "|" + row.dataset.scene]) || {};
    syncFormatFields(root, d.fmt || {});
  });
}

function fileCard(f, inspecting) {
  let chip = '<span class="chip done">' + esc(t("ready")) + '</span>';
  if (f.status === "inspecting") chip = '<span class="chip running">' + esc(t("inspecting…")) + '</span>';
  else if (f.status === "pending") chip = '<span class="chip queued">' + esc(t("waiting")) + '</span>';
  else if (f.status === "error") chip = '<span class="chip error">' + esc(t("error")) + '</span>';

  const r = f.report || {};
  const meta = [];
  if (f.size) meta.push(fmtBytes(f.size));
  if (r.saved_with) meta.push(tf("saved with Blender {v}", { v: r.saved_with }));
  if (r.inspect_seconds) meta.push(tf("inspection {s} s", { s: r.inspect_seconds }));
  if (r.counts) meta.push(tf("{o} objects · {s} scene(s)", { o: r.counts.objects, s: r.counts.scenes }));
  if (r.missing_external_count) meta.push(tf("⚠ {n} external file(s) missing", { n: r.missing_external_count }));

  const scenes = (r.scenes || []).map(s => sceneRow(f, s)).join("");

  return '<div class="file-card ' + f.status + '" data-id="' + f.id + '">' +
    '<div class="file-head">' +
      '<div class="file-title"><span class="fname">' + esc(f.name) + '</span>' + chip + '</div>' +
      '<div class="file-actions">' +
        '<button class="btn sm ghost" data-act="inspect" data-id="' + f.id + '">' + esc(t("Re-inspect")) + '</button>' +
        '<button class="btn sm ghost" data-act="open-file" data-path="' + esc(f.path) + '">' + esc(t("Open folder")) + '</button>' +
        '<button class="btn sm ghost danger" data-act="remove-file" data-id="' + f.id + '">' + esc(t("Remove")) + '</button>' +
      '</div>' +
    '</div>' +
    '<div class="file-path muted" title="' + esc(f.path) + '">' + esc(f.path) + '</div>' +
    '<div class="file-meta muted">' + meta.join(" · ") + '</div>' +
    (f.inspect_error ? '<div class="err">' + esc(f.inspect_error) + '</div>' : '') +
    (f.status === "ready" ?
      '<div class="scenes">' + scenes +
        '<div class="scenes-foot"><button class="btn sm" data-act="enqueue-all" data-id="' + f.id + '">' + esc(t("+ Queue all scenes")) + '</button></div>' +
      '</div>' : '') +
    '</div>';
}

function sceneRow(f, s) {
  const key = f.id + "|" + s.name;
  const d = overrideDraft[key] || {};
  const frames = (s.frame_start != null)
    ? tf("{a}–{b} · {n} frames", { a: s.frame_start, b: s.frame_end, n: s.frame_count }) : "";
  const eng = engineLabel(s.engine) + (s.samples ? " · " + s.samples + " spp" : "") + (s.device ? " " + s.device : "");
  const res = s.resolution_x ? (s.resolution_x + "×" + s.resolution_y) : "";
  const out = s.filepath_raw || t("(the .blend default)");
  const ovFmt = (d.fmt && d.fmt.format) ? d.fmt : null;
  const fmtTxt = ovFmt
    ? fmtLabel(ovFmt.format, ovFmt.ffmpeg_container, ovFmt.color_depth)
    : (s.file_format ? fmtLabel(s.file_format, s.ffmpeg_container, s.color_depth) : "");

  return '<div class="scene" data-file="' + f.id + '" data-scene="' + esc(s.name) + '">' +
    '<div class="scene-top">' +
      '<span class="scene-name">' + esc(s.name) + '</span>' +
      '<span class="tags">' +
        '<span class="tag">' + frames + '</span>' +
        '<span class="tag">' + esc(eng) + '</span>' +
        '<span class="tag">' + esc(res) + '</span>' +
        (fmtTxt ? '<span class="tag fmt' + (ovFmt ? ' out-own' : '') + '" title="' + esc(t("output format")) + '"' +
          ' data-fmt="' + esc(s.file_format || '') + '" data-cont="' + esc(s.ffmpeg_container || '') +
          '" data-depth="' + esc(s.color_depth || '') + '">' + esc(fmtTxt) + '</span>' : '') +
        '<span class="tag script' + (d.script_id && scriptById(d.script_id) ? '' : ' hidden') +
          '" title="' + esc(t("Python script for this job")) + '">' +
          esc(d.script_id && scriptById(d.script_id) ? scriptById(d.script_id).name : '') + '</span>' +
        (s.camera ? '<span class="tag">cam ' + esc(s.camera) + '</span>' : '') +
        '<span class="tag out' + (d.out ? ' out-own' : '') + '" data-raw="' + esc(s.filepath_raw || '') + '" data-abs="' + esc(s.filepath_abs || '') + '" title="' + esc(d.out || s.filepath_abs || '') + '">→ ' + esc(d.out || out) + '</span>' +
      '</span>' +
      '<span class="scene-actions">' +
        '<button class="btn sm ghost" data-act="pick-out" title="' + esc(t("Choose the output folder for this scene")) + '">' + esc(t("📁 Output…")) + '</button>' +
        '<button class="btn sm ghost" data-act="toggle-ov">' + esc(t("Overrides…")) + '</button>' +
        '<button class="btn sm primary" data-act="enqueue">' + esc(t("+ Queue")) + '</button>' +
      '</span>' +
    '</div>' +
    '<div class="overrides hidden">' +
      '<label>' + esc(t("Frames")) + ' <input class="input num ov-start" type="number" style="width:76px" value="' + esc(d.start ?? s.frame_start ?? "") + '"> – ' +
        '<input class="input num ov-end" type="number" style="width:76px" value="' + esc(d.end ?? s.frame_end ?? "") + '"></label>' +
      '<label>' + esc(t("Engine")) + ' <select class="input ov-engine">' +
        '<option value="">' + esc(t("(from the file)")) + '</option>' +
        '<option value="CYCLES"' + (d.engine === "CYCLES" ? " selected" : "") + '>Cycles</option>' +
        '<option value="BLENDER_EEVEE"' + (d.engine === "BLENDER_EEVEE" ? " selected" : "") + '>EEVEE</option>' +
        '<option value="BLENDER_WORKBENCH"' + (d.engine === "BLENDER_WORKBENCH" ? " selected" : "") + '>Workbench</option>' +
      '</select></label>' +
      '<label>' + esc(t("Samples")) + ' <input class="input num ov-samples" type="number" min="1" style="width:70px" value="' + esc(d.samples ?? "") + '"></label>' +
      '<label>' + esc(t("Device")) + ' <select class="input ov-device">' +
        '<option value="">' + esc(t("(from the file)")) + '</option>' +
        '<option value="GPU"' + (d.device === "GPU" ? " selected" : "") + '>GPU</option>' +
        '<option value="CPU"' + (d.device === "CPU" ? " selected" : "") + '>CPU</option>' +
      '</select></label>' +
      '<label>' + esc(t("Resolution %")) + ' <input class="input num ov-res" type="number" min="1" max="400" style="width:64px" value="' + esc(d.res ?? "") + '"></label>' +
      '<label>' + esc(t("Script")) + ' <select class="input ov-script">' + scriptOptions(d.script_id) + '</select></label>' +
      '<label class="grow">' + esc(t("Output")) + ' <input class="input ov-out" placeholder="' + esc(t("(the file's)")) + '" value="' + esc(d.out ?? "") + '"></label>' +
      '<button class="btn sm ghost" data-act="pick-out">' + esc(t("Choose folder…")) + '</button>' +
      '<div class="fmt-fields ov-format" data-label="' + esc(t("OUTPUT FORMAT")) + '">' + formatFields(d.fmt || {}) + '</div>' +
    '</div>' +
    '</div>';
}

function readOverrideRow(row) {
  const g = sel => { const el = row.querySelector(sel); return el ? el.value : ""; };
  return { start: g(".ov-start"), end: g(".ov-end"), engine: g(".ov-engine"),
           samples: g(".ov-samples"), device: g(".ov-device"), res: g(".ov-res"), out: g(".ov-out"),
           script_id: g(".ov-script"),
           fmt: readFormat(row.querySelector(".ov-format")) };
}

function snapshotRow(row) {
  const key = row.dataset.file + "|" + row.dataset.scene;
  overrideDraft[key] = readOverrideRow(row);
}

function updateSceneOutTag(row) {
  const tag = row.querySelector(".tag.out");
  if (!tag) return;
  const d = readOverrideRow(row);
  const raw = tag.dataset.raw || "";
  tag.textContent = "→ " + (d.out || raw || t("(the .blend default)"));
  tag.title = d.out || tag.dataset.abs || "";
  if (d.out) {
    tag.classList.add("out-own");
  } else {
    tag.classList.remove("out-own");
  }
}

function updateSceneFmtTag(row) {
  const tag = row.querySelector(".tag.fmt");
  if (!tag) return;
  const v = readFormat(row.querySelector(".ov-format"));
  if (v.format) {
    tag.textContent = fmtLabel(v.format, v.ffmpeg_container, v.color_depth);
    tag.classList.add("out-own");
    tag.title = t("format forced for this job");
  } else {
    tag.textContent = tag.dataset.fmt
      ? fmtLabel(tag.dataset.fmt, tag.dataset.cont, tag.dataset.depth)
      : "—";
    tag.classList.remove("out-own");
    tag.title = t("format saved in the .blend");
  }
}

function updateSceneScriptTag(row) {
  const tag = row.querySelector(".tag.script");
  const sel = row.querySelector(".ov-script");
  if (!tag || !sel) return;
  const sc = scriptById(sel.value);
  tag.textContent = sc ? sc.name : "";
  tag.classList.toggle("hidden", !sc);
}

/* ============================ queue ============================ */
/** Format the job will write with: the override, or the .blend's own. */
function jobFormatId(j) {
  return ((j.overrides || {}).format) || j.scene_format || "";
}

function jobFormatText(j) {
  const ov = j.overrides || {};
  const id = jobFormatId(j);
  if (!id) return "";
  return fmtLabel(id, ov.ffmpeg_container || j.scene_container, ov.color_depth);
}

function renderQueue(st) {
  const jobs = st.jobs || [];
  const counts = { queued: 0, running: 0, done: 0, error: 0, canceled: 0 };
  jobs.forEach(j => { if (counts[j.status] != null) counts[j.status]++; });
  $("#queueSummary").textContent =
    jobs.length ? tf("{q} queued · {r} rendering · {d} done",
                     { q: counts.queued, r: counts.running, d: counts.done }) : "";

  const queued = jobs.filter(j => j.status === "queued");
  const distinct = [...new Set(queued.map(jobFormatId).filter(Boolean))];
  const warn = $("#queueFormatWarn");
  if (distinct.length > 1) {
    warn.textContent = tf("mixed formats: {list}", { list: distinct.map(id => fmtLabel(id)).join(", ") });
    warn.title = t("Queued jobs do not all write the same format. Use “Output format…” to unify them.");
    warn.classList.remove("hidden");
  } else {
    warn.classList.add("hidden");
  }
  $("#btnQueueFormat").disabled = queued.length === 0;
  $("#btnQueueScript").disabled = queued.length === 0;

  const el = $("#queueList");
  const sig = jobs.map(j => j.id + ":" + j.status + ":" + JSON.stringify(j.overrides || {}) +
    ":" + JSON.stringify(j.frames || {})).join("|") + "|" + (st.worker.current_job_id || "");
  if (sig !== queueSig) {
    queueSig = sig;
    el.innerHTML = jobs.map(jobCard).join("")
      || '<div class="empty muted">' +
         esc(t("The queue is empty. Inspect a file and queue its scenes.")) + '</div>';
    for (const id of openDetails) {
      const box = document.querySelector('[data-details="' + id + '"]');
      if (box) { box.classList.remove("hidden"); loadDetails(id); }
    }
  }

  for (const j of jobs) {
    const card = el.querySelector('.job[data-id="' + j.id + '"]');
    if (!card) continue;
    const p = j.progress || {};
    const pct = j.status === "done" ? 100 : Math.round((p.percent || 0) * 100);
    const bar = card.querySelector(".bar > div");
    if (bar) bar.style.width = pct + "%";
    const info = card.querySelector(".job-progress");
    if (info) info.textContent = progressText(j, pct);
    const tail = card.querySelector(".job-tail");
    if (tail && j.status === "running" && j.id === st.worker.current_job_id) {
      const lines = st.log_tail || [];
      tail.textContent = lines.length ? lines[lines.length - 1] : "";
    }
  }

  for (const j of jobs) {
    const prev = prevStatuses[j.id];
    if (prev && prev !== j.status && prev === "running" && j.status === "done") beep();
    prevStatuses[j.id] = j.status;
  }
}

function progressText(j, pct) {
  const p = j.progress || {};
  const fr = j.frames || {};
  if (j.status === "queued") return tf("queued · frames {a}–{b}", { a: fr.start, b: fr.end });
  if (j.status === "running") {
    let txt = tf("frame {f} of {t} · {p}% · {e} elapsed", {
      f: p.frame ?? "…", t: p.total_frames ?? (fr.end - fr.start + 1),
      p: pct, e: fmtDur(p.elapsed_s) });
    if (p.remaining_text) txt += tf(" · left {x}", { x: p.remaining_text });
    else if (p.eta_s != null) txt += tf(" · left ~{x}", { x: fmtDur(p.eta_s) });
    return txt;
  }
  if (j.status === "done") return tf("done · {n} file(s) · {d}",
                                     { n: (j.outputs || []).length, d: fmtDur(j.duration_s) });
  if (j.status === "error") return tf("error: {e}", { e: j.error || "" });
  if (j.status === "canceled") return t("canceled");
  return j.status;
}

function summarizeOverrides(ov) {
  if (!ov) return "";
  const parts = [];
  if (ov.engine) parts.push(engineLabel(ov.engine));
  if (ov.samples) parts.push(ov.samples + " spp");
  if (ov.device) parts.push(ov.device);
  if (ov.resolution_percentage) parts.push(ov.resolution_percentage + "%");
  if (ov.color_mode) parts.push(ov.color_mode);
  if (ov.exr_codec) parts.push(ov.exr_codec);
  if (ov.ffmpeg_codec) {
    const c = ((FMT && FMT.ffmpeg_codecs) || []).find(x => x.id === ov.ffmpeg_codec);
    parts.push((c && c.label) || ov.ffmpeg_codec);
  }
  if (ov.quality != null && ov.format) {
    const sp = fmtSpec(ov.format);
    parts.push(tf(sp && sp.quality_kind === "compression" ? "compression {q}%" : "quality {q}%",
                  { q: ov.quality }));
  }
  if (ov.output_dir) {
    const tail = String(ov.output_dir).split(/[\\/]/).filter(Boolean).pop() || t("output");
    parts.push("📁 " + tail);
  }
  return parts.join(" · ");
}

function jobCard(j) {
  const chipLabels = { queued: t("queued"), running: t("rendering"), done: t("done"),
                       error: t("error"), canceled: t("canceled") };
  const fr = j.frames || {};
  const ovs = summarizeOverrides(j.overrides);
  const fmtTxt = jobFormatText(j);
  const scriptTxt = (j.overrides || {}).script_name;
  const acts = [];
  if (j.status === "queued") {
    acts.push('<button class="btn sm ghost" data-act="move-up" data-id="' + j.id + '" title="' + esc(t("Move up")) + '">↑</button>');
    acts.push('<button class="btn sm ghost" data-act="move-down" data-id="' + j.id + '" title="' + esc(t("Move down")) + '">↓</button>');
    acts.push('<button class="btn sm ghost" data-act="cancel" data-id="' + j.id + '">' + esc(t("Cancel")) + '</button>');
    acts.push('<button class="btn sm ghost danger" data-act="delete" data-id="' + j.id + '">✕</button>');
  } else if (j.status === "running") {
    acts.push('<button class="btn sm ghost" data-act="cancel" data-id="' + j.id + '">' + esc(t("Cancel")) + '</button>');
  } else {
    if (j.status === "done") {
      acts.push('<button class="btn sm primary" data-act="open-folder" data-id="' + j.id + '" title="' + esc(t("Open the output folder in your file manager")) + '">' + esc(t("📂 Open folder")) + '</button>');
    }
    acts.push('<button class="btn sm ghost" data-act="retry" data-id="' + j.id + '">' + esc(t("Retry")) + '</button>');
    acts.push('<button class="btn sm ghost danger" data-act="delete" data-id="' + j.id + '">✕</button>');
  }
  if (j.status === "queued") {
    acts.push('<button class="btn sm ghost" data-act="job-format" data-id="' + j.id +
      '" title="' + esc(t("Change the output format of this job")) + '">' + esc(t("🎞 Format")) + '</button>');
    acts.push('<button class="btn sm ghost" data-act="job-script" data-id="' + j.id +
      '" title="' + esc(t("Add or remove a Python script for this job")) + '">' + esc(t("⚙ Script")) + '</button>');
  }
  acts.push('<button class="btn sm" data-act="details" data-id="' + j.id + '">' + esc(t("Details")) + '</button>');

  return '<div class="job ' + j.status + '" data-id="' + j.id + '">' +
    '<div class="job-head">' +
      '<span class="chip ' + j.status + '">' + (chipLabels[j.status] || j.status) + '</span>' +
      '<span class="job-title">' + esc(j.file_name) + ' <span class="muted">·</span> ' + esc(j.scene) + '</span>' +
      (scriptTxt ? '<span class="chip script" title="' +
        esc(t("Python script that runs before rendering")) + '">⚙ ' +
        esc(scriptTxt) + '</span>' : '') +
      (fmtTxt ? '<span class="chip fmt' + ((j.overrides || {}).format ? ' own' : '') +
        '" title="' + esc((j.overrides || {}).format ? t("format forced for this job") : t("format saved in the .blend")) +
        '">' + esc(fmtTxt) + '</span>' : '') +
      '<span class="job-sub muted">' + esc(tf("frames {a}–{b}", { a: fr.start, b: fr.end })) +
        (ovs ? " · " + esc(ovs) : "") + '</span>' +
      '<span class="job-actions">' + acts.join("") + '</span>' +
    '</div>' +
    '<div class="bar ' + j.status + '"><div></div></div>' +
    '<div class="job-progress muted"></div>' +
    (j.status === "running" ? '<div class="job-tail"></div>' : '') +
    '<div class="job-details hidden" data-details="' + j.id + '"></div>' +
    '</div>';
}

const WEB_IMAGE_EXTS = [".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif"];
const detailFrames = {};   // jid -> frames the browser can actually display

function fileExt(name) {
  const i = String(name || "").lastIndexOf(".");
  return i >= 0 ? String(name).slice(i).toLowerCase() : "";
}

function isWebImage(name) {
  return WEB_IMAGE_EXTS.includes(fileExt(name));
}

function pickFrames(outs, n) {
  if (outs.length <= n) return outs;
  const res = [], step = (outs.length - 1) / (n - 1);
  for (let i = 0; i < n; i++) res.push(outs[Math.round(i * step)]);
  return res.filter((v, i, a) => a.indexOf(v) === i);
}

async function loadDetails(jid) {
  const box = document.querySelector('[data-details="' + jid + '"]');
  if (!box || box.dataset.loaded) return;
  let data;
  try { data = await api("/api/jobs/" + jid + "/outputs"); }
  catch (e) { box.innerHTML = '<div class="muted">' + esc(t("No output data.")) + '</div>'; return; }
  const outs = (data.outputs || []).filter(o => o.exists);
  // EXR, TIFF, DPX... the browser cannot draw them: only the MP4 is left.
  const shots = outs.filter(o => isWebImage(o.name));
  detailFrames[jid] = shots.map(o => o.frame).filter(f => f != null);
  let html = "";
  const prev = data.preview || {};
  if (prev.video) html += '<video controls preload="metadata" src="/api/jobs/' + jid + '/video"></video>';
  const picks = pickFrames(shots, 8).filter(o => o.frame != null);
  if (picks.length) {
    html += '<div class="strip">' + picks.map(o =>
      '<img loading="lazy" src="/api/jobs/' + jid + '/frames/' + o.frame + '" data-act="view-frame" data-jid="' + jid + '" data-frame="' + o.frame + '" title="frame ' + o.frame + '">'
    ).join("") + '</div>';
  }
  const notes = [];
  if (outs.length && !shots.length) {
    notes.push(fileExt(outs[0].name).replace(".", "").toUpperCase() +
      t(": the browser cannot display these files"));
  }
  if (prev.note) notes.push(tf("no preview ({why})", { why: prev.note }));
  else if (outs.length > 1 && !prev.video) notes.push(t("preview MP4 not available"));
  html += '<div class="details-actions">' +
    '<button class="btn sm ghost" data-act="open-folder" data-id="' + jid + '">' + esc(t("Open output folder")) + '</button>' +
    '<button class="btn sm ghost" data-act="view-log" data-id="' + jid + '">' + esc(t("View log")) + '</button>' +
    '<span class="muted">' + esc(tf("{n} output file(s)", { n: outs.length })) +
    (notes.length ? " · " + notes.join(" · ") : "") +
    '</span></div>';
  box.innerHTML = html || '<div class="muted">' + esc(t("Nothing to show yet.")) + '</div>';
  box.dataset.loaded = "1";
}

/* ============================ format modal ============================ */
let fmtTarget = null;   // {mode: "job", id} | {mode: "queue"}

function openFormatModal(mode, job) {
  if (!FMT) { toast(t("Still loading Blender's formats…"), "warn"); return; }
  const ov = (job && job.overrides) || {};
  const v = {};
  for (const k of FORMAT_KEYS) if (ov[k] != null && ov[k] !== "") v[k] = ov[k];
  fmtTarget = mode === "job" ? { mode: "job", id: job.id } : { mode: "queue" };

  const queued = ((state && state.jobs) || []).filter(j => j.status === "queued");
  $("#fmtTitle").textContent = mode === "job" ? t("Job format") : t("Queue format");
  $("#fmtScope").textContent = mode === "job"
    ? tf("{f} · {s} — now writes: {fmt}",
         { f: job.file_name, s: job.scene, fmt: jobFormatText(job) || t("whatever the .blend has") })
    : tf("Applies to the {n} queued job(s); finished ones are left alone.", { n: queued.length });
  const root = $("#fmtFields");
  root.innerHTML = formatFields(v);
  syncFormatFields(root, v);
  updateFmtPreview();
  $("#fmtModal").classList.remove("hidden");
}

function updateFmtPreview() {
  const el = $("#fmtPreview");
  if (!el) return;
  const v = readFormat($("#fmtFields"));
  if (!v.format) { el.textContent = t("Each scene keeps the format saved in its .blend."); return; }
  const sp = fmtSpec(v.format) || {};
  const ext = fmtExt(v.format, v.ffmpeg_container);
  el.textContent = sp.movie ? tf("Output: one video file {ext}", { ext })
                            : tf("Output: a sequence of {ext} files", { ext });
}

$("#fmtApply").addEventListener("click", async () => {
  const v = readFormat($("#fmtFields"));
  try {
    if (fmtTarget && fmtTarget.mode === "job") {
      const job = ((state && state.jobs) || []).find(j => j.id === fmtTarget.id);
      if (!job) throw new Error(t("The job is no longer in the queue"));
      const ov = {};
      for (const [k, val] of Object.entries(job.overrides || {})) {
        if (!FORMAT_KEYS.includes(k)) ov[k] = val;
      }
      Object.assign(ov, v);
      await api("/api/jobs/" + fmtTarget.id, { method: "PATCH", body: JSON.stringify({ overrides: ov }) });
      toast(t("Format updated"), "ok");
    } else {
      const r = await api("/api/jobs/format", { method: "POST", body: JSON.stringify(v) });
      const n = (r.changed || []).length;
      toast(n ? tf("Format applied to {n} job(s)", { n }) : t("No queued jobs"), n ? "ok" : "warn");
    }
    closeModal("fmtModal");
    queueSig = null;
    tick();
  } catch (err) { toast(String(err.message || err), "error"); }
});

$("#btnQueueFormat").addEventListener("click", () => openFormatModal("queue"));

/* ============================ script library ============================ */
let scriptTarget = null;   // null = library only | {mode:"job", id} | {mode:"queue"}
let scriptEditing = "";    // id of the script open in the editor ("" = new one)

function openScriptModal(target, preselect) {
  scriptTarget = target || null;
  const jobs = ((state && state.jobs) || []);
  const queued = jobs.filter(j => j.status === "queued");
  const job = target && target.mode === "job" ? jobs.find(j => j.id === target.id) : null;

  $("#scriptTitle").textContent = target ? t("Choose script") : t("Python scripts");
  $("#scriptScope").textContent = !target ? t("They are stored in the app and will still be here next time.")
    : target.mode === "job"
      ? (job ? tf("{f} · {s} — now: {script}", { f: job.file_name, s: job.scene,
                  script: (job.overrides || {}).script_name || t("no script") }) : "")
      : tf("Applies to the {n} queued job(s).", { n: queued.length });
  $("#scriptApply").classList.toggle("hidden", !target);
  $("#scriptApply").textContent = target && target.mode === "queue" ? t("Apply to the queue") : t("Apply to the job");

  const want = preselect !== undefined ? preselect
    : (job ? (job.overrides || {}).script_id || "" : (scriptsList()[0] || {}).id || "");
  fillScriptPick(want);
  $("#scriptModal").classList.remove("hidden");
}

function fillScriptPick(selected) {
  $("#scriptPick").innerHTML = scriptOptions(selected);
  loadScriptIntoEditor(selected || "");
}

function loadScriptIntoEditor(id) {
  scriptEditing = id || "";
  const sc = scriptById(scriptEditing);
  $("#scriptName").value = sc ? sc.name : "";
  $("#scriptCode").value = sc ? sc.code : "";
  $("#scriptDel").disabled = !sc;
  $("#scriptDup").disabled = !sc;
}

function editorIsDirty() {
  const sc = scriptById(scriptEditing);
  if (!sc) return !!($("#scriptName").value.trim() || $("#scriptCode").value.trim());
  return sc.name !== $("#scriptName").value || sc.code !== $("#scriptCode").value;
}

/** Saves the open script (new or edited) and returns its id. */
async function saveScript() {
  const body = { name: $("#scriptName").value.trim() || t("Untitled"), code: $("#scriptCode").value };
  const r = scriptEditing
    ? await api("/api/scripts/" + scriptEditing, { method: "PATCH", body: JSON.stringify(body) })
    : await api("/api/scripts", { method: "POST", body: JSON.stringify(body) });
  const id = r.script.id;
  await tick();
  fillScriptPick(id);
  return id;
}

$("#scriptPick").addEventListener("change", e => {
  if (editorIsDirty() && !confirm(t("Unsaved changes in the script. Discard them?"))) {
    e.target.value = scriptEditing;
    return;
  }
  loadScriptIntoEditor(e.target.value);
});

$("#scriptNew").addEventListener("click", () => {
  $("#scriptPick").value = "";
  loadScriptIntoEditor("");
  $("#scriptName").focus();
});

$("#scriptDup").addEventListener("click", () => {
  const sc = scriptById(scriptEditing);
  if (!sc) return;
  scriptEditing = "";
  $("#scriptPick").value = "";
  $("#scriptName").value = sc.name + t(" (copy)");
  $("#scriptCode").value = sc.code;
});

$("#scriptSave").addEventListener("click", async () => {
  try { await saveScript(); toast(t("Script saved"), "ok"); }
  catch (err) { toast(String(err.message || err), "error"); }
});

$("#scriptDel").addEventListener("click", async () => {
  const sc = scriptById(scriptEditing);
  if (!sc || !confirm(tf("Delete «{name}» from the library?\nJobs that already carry it keep their copy.", { name: sc.name }))) return;
  try {
    await api("/api/scripts/" + sc.id, { method: "DELETE" });
    await tick();
    fillScriptPick((scriptsList()[0] || {}).id || "");
    toast(t("Script deleted"), "ok");
  } catch (err) { toast(String(err.message || err), "error"); }
});

$("#scriptApply").addEventListener("click", async () => {
  try {
    let id = $("#scriptPick").value;
    if (id && editorIsDirty()) id = await saveScript();   // apply what you see, not the old copy
    if (scriptTarget && scriptTarget.mode === "job") {
      const job = ((state && state.jobs) || []).find(j => j.id === scriptTarget.id);
      if (!job) throw new Error(t("The job is no longer in the queue"));
      const ov = {};
      for (const [k, v] of Object.entries(job.overrides || {})) {
        if (!["script", "script_name", "script_id"].includes(k)) ov[k] = v;
      }
      if (id) ov.script_id = id;
      await api("/api/jobs/" + scriptTarget.id, { method: "PATCH", body: JSON.stringify({ overrides: ov }) });
      toast(id ? t("Script applied to the job") : t("Script removed from the job"), "ok");
    } else {
      const r = await api("/api/jobs/script", { method: "POST", body: JSON.stringify({ script_id: id }) });
      const n = (r.changed || []).length;
      toast(n ? tf(id ? "Script applied to {n} job(s)" : "Script removed from {n} job(s)", { n })
              : t("No queued jobs"), n ? "ok" : "warn");
    }
    closeModal("scriptModal");
    queueSig = null;
    tick();
  } catch (err) { toast(String(err.message || err), "error"); }
});

$("#btnScripts").addEventListener("click", () => openScriptModal(null));
$("#btnQueueScript").addEventListener("click", () => openScriptModal({ mode: "queue" }));

/* ============================ actions (delegated) ============================ */
document.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-act]");
  if (!btn) return;
  const act = btn.dataset.act;
  try {
    if (act === "enqueue") await enqueueScene(btn.closest(".scene"));
    else if (act === "enqueue-all") await enqueueAll(btn.dataset.id);
    else if (act === "toggle-ov") {
      const ov = btn.closest(".scene").querySelector(".overrides");
      ov.classList.toggle("hidden");
    }
    else if (act === "pick-out") {
      const row = btn.closest(".scene");
      const input = row.querySelector(".ov-out");
      const tag = row.querySelector(".tag.out");
      const abs = (input && input.value) || (tag ? tag.dataset.abs : "") || "";
      openFs("pick-dir", input, abs ? abs.replace(/[\\/][^\\/]*$/, "") : "");
    }
    else if (act === "inspect") { await api("/api/files/" + btn.dataset.id + "/inspect", { method: "POST" }); toast(t("Re-inspecting…")); }
    else if (act === "remove-file") {
      if (confirm(t("Remove this file from the list? (it is not deleted from disk)"))) {
        await api("/api/files/" + btn.dataset.id, { method: "DELETE" });
      }
    }
    else if (act === "open-file") await api("/api/open", { method: "POST", body: JSON.stringify({ path: btn.dataset.path }) });
    else if (act === "move-up") await api("/api/jobs/" + btn.dataset.id + "/move", { method: "POST", body: JSON.stringify({ direction: -1 }) });
    else if (act === "move-down") await api("/api/jobs/" + btn.dataset.id + "/move", { method: "POST", body: JSON.stringify({ direction: 1 }) });
    else if (act === "cancel") await api("/api/jobs/" + btn.dataset.id + "/cancel", { method: "POST" });
    else if (act === "retry") await api("/api/jobs/" + btn.dataset.id + "/retry", { method: "POST" });
    else if (act === "delete") await api("/api/jobs/" + btn.dataset.id, { method: "DELETE" });
    else if (act === "open-folder") await api("/api/jobs/" + btn.dataset.id + "/open", { method: "POST" });
    else if (act === "view-log") await viewLog(btn.dataset.id);
    else if (act === "job-script") {
      const job = ((state && state.jobs) || []).find(j => j.id === btn.dataset.id);
      if (job) openScriptModal({ mode: "job", id: job.id });
    }
    else if (act === "job-format") {
      const job = ((state && state.jobs) || []).find(j => j.id === btn.dataset.id);
      if (job) openFormatModal("job", job);
    }
    else if (act === "details") {
      const box = document.querySelector('[data-details="' + btn.dataset.id + '"]');
      if (box) {
        box.classList.toggle("hidden");
        if (!box.classList.contains("hidden")) { openDetails.add(btn.dataset.id); await loadDetails(btn.dataset.id); }
        else openDetails.delete(btn.dataset.id);
      }
    }
    else if (act === "view-frame") openFrame(btn.dataset.jid, Number(btn.dataset.frame));
  } catch (err) {
    toast(String(err.message || err), "error");
  }
  tick();
});

document.addEventListener("input", (e) => {
  if (e.target.closest("#fmtFields")) {
    if (e.target.matches(".fmt-format")) syncFormatFields($("#fmtFields"), {});
    updateFmtPreview();
    return;
  }
  const row = e.target.closest(".scene");
  if (row && e.target.matches("input, select")) {
    if (e.target.matches(".fmt-format")) syncFormatFields(row.querySelector(".ov-format"), {});
    snapshotRow(row);
    if (e.target.matches(".ov-out")) updateSceneOutTag(row);
    if (e.target.closest(".ov-format")) updateSceneFmtTag(row);
    if (e.target.matches(".ov-script")) updateSceneScriptTag(row);
  }
});

async function enqueueScene(row) {
  if (!row) return;
  const d = readOverrideRow(row);
  const body = { file_id: row.dataset.file, scene: row.dataset.scene };
  const fr = {};
  if (d.start !== "") fr.start = Number(d.start);
  if (d.end !== "") fr.end = Number(d.end);
  if (Object.keys(fr).length) body.frames = fr;
  const ov = {};
  if (d.engine) ov.engine = d.engine;
  if (d.samples !== "") ov.samples = Number(d.samples);
  if (d.device) ov.device = d.device;
  if (d.res !== "") ov.resolution_percentage = Number(d.res);
  if (d.out) ov.output_dir = d.out;
  if (d.script_id) ov.script_id = d.script_id;
  Object.assign(ov, d.fmt || {});
  if (Object.keys(ov).length) body.overrides = ov;
  await api("/api/jobs", { method: "POST", body: JSON.stringify(body) });
  toast(t("Queued: ") + row.dataset.scene, "ok");
}

async function enqueueAll(fid) {
  const rows = $$('.scene[data-file="' + fid + '"]');
  for (const row of rows) {
    try { await enqueueScene(row); } catch (err) { toast(String(err.message || err), "error"); }
  }
}

function showFrame(jid, frame) {
  const job = (state.jobs || []).find(j => j.id === jid);
  const list = detailFrames[jid] || [];
  const img = $("#frameImg");
  img.dataset.jid = jid;
  img.dataset.frame = String(frame);
  img.src = "/api/jobs/" + jid + "/frames/" + frame;
  $("#frameLabel").textContent = (job ? job.file_name + " · " + job.scene : t("Frame")) + " — frame " + frame;
  const pos = list.indexOf(frame);
  $("#frameInfo").textContent = (pos >= 0 && list.length
    ? tf("{i} of {n} · ", { i: pos + 1, n: list.length })
    : "") + t("use ← → to browse");
  $("#framePrev").disabled = pos === 0;
  $("#frameNext").disabled = pos >= 0 && pos === list.length - 1;
}

function openFrame(jid, frame) {
  showFrame(jid, frame);
  $("#frameModal").classList.remove("hidden");
}

/** Steps through the frames that actually exist (never past the render). */
function stepFrame(delta) {
  const img = $("#frameImg");
  const jid = img.dataset.jid;
  const list = detailFrames[jid] || [];
  const cur = Number(img.dataset.frame);
  const idx = list.indexOf(cur);
  if (idx < 0) { showFrame(jid, cur + delta); return; }
  const next = Math.max(0, Math.min(list.length - 1, idx + delta));
  if (next !== idx) showFrame(jid, list[next]);
}

$("#framePrev").addEventListener("click", () => stepFrame(-1));
$("#frameNext").addEventListener("click", () => stepFrame(1));

/* ============================ upload (drag & drop / input) ============================ */
function setupDropzone() {
  const dz = $("#dropzone");
  ["dragenter", "dragover"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add("over"); }));
  ["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove("over"); }));
  dz.addEventListener("drop", e => {
    const fl = Array.from(e.dataTransfer.files || []).filter(f => f.name.toLowerCase().endsWith(".blend"));
    if (fl.length) uploadFiles(fl);
    else toast(t("Only .blend files are accepted"), "warn");
  });
  $("#btnBrowseFiles").addEventListener("click", () => $("#fileInput").click());
  $("#fileInput").addEventListener("change", e => {
    const fl = Array.from(e.target.files || []).filter(f => f.name.toLowerCase().endsWith(".blend"));
    if (fl.length) uploadFiles(fl);
    e.target.value = "";
  });
  $("#btnBrowse").addEventListener("click", () => openFs("add"));
}

function uploadFiles(fl) {
  const fd = new FormData();
  for (const f of fl) fd.append("files", f, f.name);
  const status = $("#uploadStatus");
  status.textContent = tf("Uploading {n} file(s)…", { n: fl.length });
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/files/upload");
  xhr.upload.onprogress = e => {
    if (e.lengthComputable) status.textContent = tf("Uploading… {p}%", { p: Math.round(e.loaded / e.total * 100) });
  };
  xhr.onload = () => {
    status.textContent = "";
    if (xhr.status >= 200 && xhr.status < 300) toast(t("Files added; inspecting…"), "ok");
    else toast(tf("Upload error (HTTP {s})", { s: xhr.status }), "error");
    tick();
  };
  xhr.onerror = () => { status.textContent = ""; toast(t("Network error while uploading"), "error"); };
  xhr.send(fd);
}

/* ============================ file browser ============================ */
const fs = { mode: "add", selected: new Set(), path: "", targetInput: null };

async function openFs(mode, targetInput = null, startPath = "") {
  fs.mode = mode;
  fs.targetInput = targetInput || null;
  if (startPath) fs.path = startPath;
  fs.selected = new Set();
  $("#fsTitle").textContent = mode === "pick-dir" ? t("Choose output folder") : t("Select .blend files");
  $("#fsHint").textContent = mode === "pick-dir"
    ? t("Browse to the folder and press “Use this folder”.")
    : t("Browse and tick the .blend files you want to add (they are queued once inspected).");
  $("#fsPickDir").textContent = mode === "pick-dir" ? t("Use this folder") : t("Add every .blend in this folder");
  $("#fsAdd").classList.toggle("hidden", mode === "pick-dir");
  $("#fsModal").classList.remove("hidden");
  await fsGo(mode === "pick-dir" ? (fs.path || "") : "");
}

async function fsGo(path) {
  let data;
  try { data = await api("/api/fs/list?path=" + encodeURIComponent(path || "")); }
  catch (err) { toast(String(err.message || err), "error"); return; }
  fs.path = data.path;
  $("#fsPath").value = data.path || "";
  const list = $("#fsList");
  list.dataset.parent = data.parent || "";
  list.innerHTML = (data.entries || []).map(en => {
    if (en.type === "dir" || en.type === "drive") {
      return '<div class="fs-item dir" data-nav="' + esc(en.path) + '"><span class="ico">📁</span>' +
        '<span class="fname">' + esc(en.name) + '</span></div>';
    }
    return '<label class="fs-item blend"><input type="checkbox" value="' + esc(en.path) + '"' +
      (fs.selected.has(en.path) ? " checked" : "") + '><span class="ico">🎬</span>' +
      '<span class="fname">' + esc(en.name) + '</span><span class="muted">' + fmtBytes(en.size) + '</span></label>';
  }).join("") || '<div class="muted" style="padding:8px">' + esc(t("(empty folder)")) + '</div>';
}

$("#fsList").addEventListener("click", e => {
  const item = e.target.closest("[data-nav]");
  if (item) fsGo(item.dataset.nav);
});
$("#fsList").addEventListener("change", e => {
  if (e.target.matches('input[type="checkbox"]')) {
    if (e.target.checked) fs.selected.add(e.target.value);
    else fs.selected.delete(e.target.value);
  }
});
$("#fsUp").addEventListener("click", () => fsGo($("#fsList").dataset.parent || ""));
$("#fsGo").addEventListener("click", () => fsGo($("#fsPath").value.trim()));
$("#fsPath").addEventListener("keydown", e => { if (e.key === "Enter") fsGo($("#fsPath").value.trim()); });

$("#fsAdd").addEventListener("click", async () => {
  const paths = Array.from(fs.selected);
  if (!paths.length) { toast(t("Select at least one .blend"), "warn"); return; }
  try {
    await api("/api/files/add", { method: "POST", body: JSON.stringify({ paths }) });
    closeModal("fsModal");
    toast(tf("Added: {n} file(s); inspecting…", { n: paths.length }), "ok");
  } catch (err) { toast(String(err.message || err), "error"); }
  tick();
});

$("#fsPickDir").addEventListener("click", async () => {
  if (!fs.path) return;
  if (fs.mode === "pick-dir") {
    if (fs.targetInput) {
      fs.targetInput.value = fs.path;
      const row = fs.targetInput.closest(".scene");
      if (row) {
        snapshotRow(row);
        updateSceneOutTag(row);
      }
    }
    closeModal("fsModal");
    return;
  }
  try {
    await api("/api/files/add", { method: "POST", body: JSON.stringify({ paths: [fs.path] }) });
    closeModal("fsModal");
    toast(t("Folder added; inspecting the .blend files…"), "ok");
  } catch (err) { toast(String(err.message || err), "error"); }
  tick();
});

/* ============================ settings ============================ */
function fillSettings() {
  if (!state) return;
  const s = state.settings || {}, b = state.blender || {};
  $("#setBlender").value = s.blender_path || b.path || "";
  $("#setBlender").placeholder = { mac: "/Applications/Blender.app/Contents/MacOS/Blender",
                                   linux: "/usr/bin/blender" }[state.platform] || String.raw`D:\...\blender.exe`;
  $("#setNotif").checked = !!s.notifications;
  $("#setPreview").checked = !!s.preview_video;
  $("#setBlenderStatus").textContent = b.ok ? tf("OK — {v}", { v: b.version })
                                              : tf("Not found — {e}", { e: b.error || "" });
}

$("#btnSettings").addEventListener("click", () => {
  fillSettings();
  $("#settingsModal").classList.remove("hidden");
});

$("#setBlenderCheck").addEventListener("click", async () => {
  try {
    const p = $("#setBlender").value.trim();
    await api("/api/settings", { method: "POST", body: JSON.stringify({ blender_path: p }) });
    const info = await api("/api/blender/check?force=1");
    $("#setBlenderStatus").textContent = info.ok ? tf("OK — {v}", { v: info.version })
                                                 : tf("Not found — {e}", { e: info.error || "" });
  } catch (err) { toast(String(err.message || err), "error"); }
});

$("#setSave").addEventListener("click", async () => {
  try {
    await api("/api/settings", {
      method: "POST",
      body: JSON.stringify({
        blender_path: $("#setBlender").value.trim(),
        notifications: $("#setNotif").checked,
        preview_video: $("#setPreview").checked,
      })
    });
    closeModal("settingsModal");
    toast(t("Settings saved"), "ok");
    tick();
  } catch (err) { toast(String(err.message || err), "error"); }
});

$("#setNotifyTest").addEventListener("click", async () => {
  try { await api("/api/notify/test", { method: "POST" }); toast(t("Test notification sent"), "ok"); }
  catch (err) { toast(String(err.message || err), "error"); }
});

/* ============================ log ============================ */
async function viewLog(jid) {
  try {
    const d = await api("/api/jobs/" + jid + "/log?tail=500");
    $("#logContent").textContent = d.log || t("(empty log)");
    $("#logModal").classList.remove("hidden");
  } catch (err) { toast(String(err.message || err), "error"); }
}

/* ============================ generic modals ============================ */
function closeModal(id) { $("#" + id).classList.add("hidden"); }
$$(".modal").forEach(m => m.addEventListener("click", e => { if (e.target === m) m.classList.add("hidden"); }));
$$("[data-close]").forEach(b => b.addEventListener("click", () => closeModal(b.dataset.close)));
document.addEventListener("keydown", e => {
  if (e.key === "Escape") { $$(".modal").forEach(m => m.classList.add("hidden")); return; }
  if (!$("#frameModal").classList.contains("hidden")) {
    if (e.key === "ArrowLeft") { e.preventDefault(); stepFrame(-1); }
    else if (e.key === "ArrowRight") { e.preventDefault(); stepFrame(1); }
  }
});

/* ============================ startup ============================ */
$("#btnPause").addEventListener("click", async () => {
  try { await api("/api/queue/pause", { method: "POST", body: JSON.stringify({}) }); tick(); }
  catch (err) { toast(String(err.message || err), "error"); }
});

$("#btnShutdown").addEventListener("click", async () => {
  if (!confirm(t("Quit BlendQueue?\nThe queue stops and the server shuts down (its window closes)."))) return;
  try { await api("/api/shutdown", { method: "POST" }); } catch (e) { }
  toast(t("BlendQueue is shutting down… you can close this tab now."), "warn", 12000);
});

$("#langSel").value = LANG;
$("#langSel").addEventListener("change", e => {
  setLang(e.target.value);
  filesSig = null;   // redraw everything that JS builds
  queueSig = null;
  tick();
});

applyLang();
setupDropzone();
