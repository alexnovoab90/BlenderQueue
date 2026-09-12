"use strict";

/* ============================ utilidades ============================ */
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

/* ============================ tick principal ============================ */
async function tick() {
  try {
    state = await api("/api/state");
  } catch (e) {
    return; // servidor caído: se reintenta solo
  }
  renderStatus(state);
  renderFiles(state);
  renderQueue(state);
  if (!$("#settingsModal").classList.contains("hidden")) fillSettings();
}

setInterval(tick, 1000);
tick();

/* ============================ cabecera ============================ */
function renderStatus(st) {
  const b = $("#blenderBadge");
  if (st.blender.ok) {
    b.textContent = "Blender: " + (st.blender.version || "OK");
    b.className = "badge ok";
    b.title = st.blender.path || "";
  } else {
    b.textContent = "Blender: no encontrado";
    b.className = "badge err";
    b.title = st.blender.error || "";
  }
  const pause = $("#btnPause");
  pause.textContent = st.worker.paused ? "Reanudar cola" : "Pausar cola";
  pause.classList.toggle("warn", !!st.worker.paused);
}

/* ============================ archivos ============================ */
function renderFiles(st) {
  const insp = st.inspector && st.inspector.current_file_id;
  $("#filesCount").textContent = st.files.length ? st.files.length + " archivo(s)" : "";
  const sig = JSON.stringify(st.files.map(f => ({
    i: f.id, s: f.status, e: f.inspect_error, t: f.inspected_at,
    r: f.report ? f.report.inspect_seconds : null
  }))) + "|" + (insp || "");
  if (sig === filesSig) return;
  filesSig = sig;
  const el = $("#filesList");
  el.innerHTML = st.files.map(f => fileCard(f, insp === f.id)).join("")
    || '<div class="empty muted">Aún no hay archivos. Arrastra un .blend arriba o usa “Seleccionar ruta del equipo…”.</div>';
}

function fileCard(f, inspecting) {
  let chip = '<span class="chip done">listo</span>';
  if (f.status === "inspecting") chip = '<span class="chip running">inspeccionando…</span>';
  else if (f.status === "pending") chip = '<span class="chip queued">en espera</span>';
  else if (f.status === "error") chip = '<span class="chip error">error</span>';

  const r = f.report || {};
  const meta = [];
  if (f.size) meta.push(fmtBytes(f.size));
  if (r.saved_with) meta.push("guardado con Blender " + r.saved_with);
  if (r.inspect_seconds) meta.push("inspección " + r.inspect_seconds + " s");
  if (r.counts) meta.push(r.counts.objects + " objetos · " + r.counts.scenes + " escena(s)");
  if (r.missing_external_count) meta.push("⚠ faltan " + r.missing_external_count + " archivo(s) externo(s)");

  const scenes = (r.scenes || []).map(s => sceneRow(f, s)).join("");

  return '<div class="file-card ' + f.status + '" data-id="' + f.id + '">' +
    '<div class="file-head">' +
      '<div class="file-title"><span class="fname">' + esc(f.name) + '</span>' + chip + '</div>' +
      '<div class="file-actions">' +
        '<button class="btn sm ghost" data-act="inspect" data-id="' + f.id + '">Re-inspeccionar</button>' +
        '<button class="btn sm ghost" data-act="open-file" data-path="' + esc(f.path) + '">Abrir carpeta</button>' +
        '<button class="btn sm ghost danger" data-act="remove-file" data-id="' + f.id + '">Quitar</button>' +
      '</div>' +
    '</div>' +
    '<div class="file-path muted" title="' + esc(f.path) + '">' + esc(f.path) + '</div>' +
    '<div class="file-meta muted">' + meta.join(" · ") + '</div>' +
    (f.inspect_error ? '<div class="err">' + esc(f.inspect_error) + '</div>' : '') +
    (f.status === "ready" ?
      '<div class="scenes">' + scenes +
        '<div class="scenes-foot"><button class="btn sm" data-act="enqueue-all" data-id="' + f.id + '">+ Encolar todas las escenas</button></div>' +
      '</div>' : '') +
    '</div>';
}

function sceneRow(f, s) {
  const key = f.id + "|" + s.name;
  const d = overrideDraft[key] || {};
  const frames = (s.frame_start != null) ? (s.frame_start + "–" + s.frame_end + " · " + s.frame_count + " frames") : "";
  const eng = engineLabel(s.engine) + (s.samples ? " · " + s.samples + " spp" : "") + (s.device ? " " + s.device : "");
  const res = s.resolution_x ? (s.resolution_x + "×" + s.resolution_y) : "";
  const out = s.filepath_raw || "(por defecto del .blend)";

  return '<div class="scene" data-file="' + f.id + '" data-scene="' + esc(s.name) + '">' +
    '<div class="scene-top">' +
      '<span class="scene-name">' + esc(s.name) + '</span>' +
      '<span class="tags">' +
        '<span class="tag">' + frames + '</span>' +
        '<span class="tag">' + esc(eng) + '</span>' +
        '<span class="tag">' + esc(res) + '</span>' +
        (s.camera ? '<span class="tag">cam ' + esc(s.camera) + '</span>' : '') +
        '<span class="tag out' + (d.out ? ' out-own' : '') + '" data-raw="' + esc(s.filepath_raw || '') + '" data-abs="' + esc(s.filepath_abs || '') + '" title="' + esc(d.out || s.filepath_abs || '') + '">→ ' + esc(d.out || out) + '</span>' +
      '</span>' +
      '<span class="scene-actions">' +
        '<button class="btn sm ghost" data-act="pick-out" title="Elegir carpeta de salida para esta escena">📁 Salida…</button>' +
        '<button class="btn sm ghost" data-act="toggle-ov">Overrides…</button>' +
        '<button class="btn sm primary" data-act="enqueue">+ Encolar</button>' +
      '</span>' +
    '</div>' +
    '<div class="overrides hidden">' +
      '<label>Frames <input class="input num ov-start" type="number" style="width:76px" value="' + esc(d.start ?? s.frame_start ?? "") + '"> – ' +
        '<input class="input num ov-end" type="number" style="width:76px" value="' + esc(d.end ?? s.frame_end ?? "") + '"></label>' +
      '<label>Motor <select class="input ov-engine">' +
        '<option value="">(del archivo)</option>' +
        '<option value="CYCLES"' + (d.engine === "CYCLES" ? " selected" : "") + '>Cycles</option>' +
        '<option value="BLENDER_EEVEE"' + (d.engine === "BLENDER_EEVEE" ? " selected" : "") + '>EEVEE</option>' +
        '<option value="BLENDER_WORKBENCH"' + (d.engine === "BLENDER_WORKBENCH" ? " selected" : "") + '>Workbench</option>' +
      '</select></label>' +
      '<label>Samples <input class="input num ov-samples" type="number" min="1" style="width:70px" value="' + esc(d.samples ?? "") + '"></label>' +
      '<label>Dispositivo <select class="input ov-device">' +
        '<option value="">(del archivo)</option>' +
        '<option value="GPU"' + (d.device === "GPU" ? " selected" : "") + '>GPU</option>' +
        '<option value="CPU"' + (d.device === "CPU" ? " selected" : "") + '>CPU</option>' +
      '</select></label>' +
      '<label>Resolución % <input class="input num ov-res" type="number" min="1" max="400" style="width:64px" value="' + esc(d.res ?? "") + '"></label>' +
      '<label class="grow">Salida <input class="input ov-out" placeholder="(la del archivo)" value="' + esc(d.out ?? "") + '"></label>' +
      '<button class="btn sm ghost" data-act="pick-out">Elegir carpeta…</button>' +
    '</div>' +
    '</div>';
}

function readOverrideRow(row) {
  const g = sel => { const el = row.querySelector(sel); return el ? el.value : ""; };
  return { start: g(".ov-start"), end: g(".ov-end"), engine: g(".ov-engine"),
           samples: g(".ov-samples"), device: g(".ov-device"), res: g(".ov-res"), out: g(".ov-out") };
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
  tag.textContent = "→ " + (d.out || raw || "(por defecto del .blend)");
  tag.title = d.out || tag.dataset.abs || "";
  if (d.out) {
    tag.classList.add("out-own");
  } else {
    tag.classList.remove("out-own");
  }
}

/* ============================ cola ============================ */
function renderQueue(st) {
  const jobs = st.jobs || [];
  const counts = { queued: 0, running: 0, done: 0, error: 0, canceled: 0 };
  jobs.forEach(j => { if (counts[j.status] != null) counts[j.status]++; });
  $("#queueSummary").textContent =
    jobs.length ? (counts.queued + " en cola · " + counts.running + " renderizando · " + counts.done + " listos") : "";

  const el = $("#queueList");
  const sig = jobs.map(j => j.id + ":" + j.status).join("|") + "|" + (st.worker.current_job_id || "");
  if (sig !== queueSig) {
    queueSig = sig;
    el.innerHTML = jobs.map(jobCard).join("")
      || '<div class="empty muted">La cola está vacía. Inspecciona un archivo y encola sus escenas.</div>';
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
  if (j.status === "queued") return "en cola · frames " + fr.start + "–" + fr.end;
  if (j.status === "running") {
    let t = "frame " + (p.frame ?? "…") + " de " + (p.total_frames ?? (fr.end - fr.start + 1)) +
            " · " + pct + "% · " + fmtDur(p.elapsed_s) + " transcurrido";
    if (p.remaining_text) t += " · resto " + p.remaining_text;
    else if (p.eta_s != null) t += " · resto ~" + fmtDur(p.eta_s);
    return t;
  }
  if (j.status === "done") return "listo · " + (j.outputs || []).length + " archivo(s) · " + fmtDur(j.duration_s);
  if (j.status === "error") return "error: " + (j.error || "");
  if (j.status === "canceled") return "cancelado";
  return j.status;
}

function summarizeOverrides(ov) {
  if (!ov) return "";
  const parts = [];
  if (ov.engine) parts.push(engineLabel(ov.engine));
  if (ov.samples) parts.push(ov.samples + " spp");
  if (ov.device) parts.push(ov.device);
  if (ov.resolution_percentage) parts.push(ov.resolution_percentage + "%");
  if (ov.output_dir) {
    const tail = String(ov.output_dir).split(/[\\/]/).filter(Boolean).pop() || "salida";
    parts.push("📁 " + tail);
  }
  return parts.join(" · ");
}

function jobCard(j) {
  const chipLabels = { queued: "en cola", running: "renderizando", done: "listo", error: "error", canceled: "cancelado" };
  const fr = j.frames || {};
  const ovs = summarizeOverrides(j.overrides);
  const acts = [];
  if (j.status === "queued") {
    acts.push('<button class="btn sm ghost" data-act="move-up" data-id="' + j.id + '" title="Subir">↑</button>');
    acts.push('<button class="btn sm ghost" data-act="move-down" data-id="' + j.id + '" title="Bajar">↓</button>');
    acts.push('<button class="btn sm ghost" data-act="cancel" data-id="' + j.id + '">Cancelar</button>');
    acts.push('<button class="btn sm ghost danger" data-act="delete" data-id="' + j.id + '">✕</button>');
  } else if (j.status === "running") {
    acts.push('<button class="btn sm ghost" data-act="cancel" data-id="' + j.id + '">Cancelar</button>');
  } else {
    if (j.status === "done") {
      acts.push('<button class="btn sm primary" data-act="open-folder" data-id="' + j.id + '" title="Abrir la carpeta de salida en el Explorador">📂 Abrir carpeta</button>');
    }
    acts.push('<button class="btn sm ghost" data-act="retry" data-id="' + j.id + '">Reintentar</button>');
    acts.push('<button class="btn sm ghost danger" data-act="delete" data-id="' + j.id + '">✕</button>');
  }
  acts.push('<button class="btn sm" data-act="details" data-id="' + j.id + '">Detalles</button>');

  return '<div class="job ' + j.status + '" data-id="' + j.id + '">' +
    '<div class="job-head">' +
      '<span class="chip ' + j.status + '">' + (chipLabels[j.status] || j.status) + '</span>' +
      '<span class="job-title">' + esc(j.file_name) + ' <span class="muted">·</span> ' + esc(j.scene) + '</span>' +
      '<span class="job-sub muted">frames ' + fr.start + '–' + fr.end + (ovs ? " · " + ovs : "") + '</span>' +
      '<span class="job-actions">' + acts.join("") + '</span>' +
    '</div>' +
    '<div class="bar ' + j.status + '"><div></div></div>' +
    '<div class="job-progress muted"></div>' +
    (j.status === "running" ? '<div class="job-tail"></div>' : '') +
    '<div class="job-details hidden" data-details="' + j.id + '"></div>' +
    '</div>';
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
  catch (e) { box.innerHTML = '<div class="muted">Sin datos de salida.</div>'; return; }
  const outs = (data.outputs || []).filter(o => o.exists);
  let html = "";
  const prev = data.preview || {};
  if (prev.video) html += '<video controls preload="metadata" src="/api/jobs/' + jid + '/video"></video>';
  if (outs.length) {
    const picks = pickFrames(outs, 8).filter(o => o.frame != null);
    if (picks.length) {
      html += '<div class="strip">' + picks.map(o =>
        '<img loading="lazy" src="/api/jobs/' + jid + '/frames/' + o.frame + '" data-act="view-frame" data-jid="' + jid + '" data-frame="' + o.frame + '" title="frame ' + o.frame + '">'
      ).join("") + '</div>';
    }
  }
  html += '<div class="details-actions">' +
    '<button class="btn sm ghost" data-act="open-folder" data-id="' + jid + '">Abrir carpeta de salida</button>' +
    '<button class="btn sm ghost" data-act="view-log" data-id="' + jid + '">Ver log</button>' +
    '<span class="muted">' + outs.length + ' archivo(s) de salida' +
    (outs.length && !prev.video && outs.length > 1 ? " · preview MP4 no disponible" : "") +
    '</span></div>';
  box.innerHTML = html || '<div class="muted">Aún sin salidas para mostrar.</div>';
  box.dataset.loaded = "1";
}

/* ============================ acciones (delegación) ============================ */
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
    else if (act === "inspect") { await api("/api/files/" + btn.dataset.id + "/inspect", { method: "POST" }); toast("Re-inspeccionando…"); }
    else if (act === "remove-file") {
      if (confirm("¿Quitar este archivo de la lista? (no se borra del disco)")) {
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
  const row = e.target.closest(".scene");
  if (row && e.target.matches("input, select")) {
    snapshotRow(row);
    if (e.target.matches(".ov-out")) updateSceneOutTag(row);
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
  if (Object.keys(ov).length) body.overrides = ov;
  await api("/api/jobs", { method: "POST", body: JSON.stringify(body) });
  toast("Encolado: " + row.dataset.scene, "ok");
}

async function enqueueAll(fid) {
  const rows = $$('.scene[data-file="' + fid + '"]');
  for (const row of rows) {
    try { await enqueueScene(row); } catch (err) { toast(String(err.message || err), "error"); }
  }
}

function openFrame(jid, frame) {
  const job = (state.jobs || []).find(j => j.id === jid);
  const img = $("#frameImg");
  img.dataset.jid = jid;
  img.dataset.frame = String(frame);
  img.src = "/api/jobs/" + jid + "/frames/" + frame;
  $("#frameLabel").textContent = (job ? job.file_name + " · " + job.scene : "Frame") + " — frame " + frame;
  $("#frameInfo").textContent = "usa ← → para navegar";
  $("#frameModal").classList.remove("hidden");
}

$("#framePrev").addEventListener("click", () => {
  const img = $("#frameImg");
  const f = Number(img.dataset.frame) - 1;
  img.dataset.frame = String(f);
  img.src = "/api/jobs/" + img.dataset.jid + "/frames/" + f;
  $("#frameLabel").textContent = "frame " + f;
});
$("#frameNext").addEventListener("click", () => {
  const img = $("#frameImg");
  const f = Number(img.dataset.frame) + 1;
  img.dataset.frame = String(f);
  img.src = "/api/jobs/" + img.dataset.jid + "/frames/" + f;
  $("#frameLabel").textContent = "frame " + f;
});

/* ============================ subida (drag & drop / input) ============================ */
function setupDropzone() {
  const dz = $("#dropzone");
  ["dragenter", "dragover"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add("over"); }));
  ["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove("over"); }));
  dz.addEventListener("drop", e => {
    const fl = Array.from(e.dataTransfer.files || []).filter(f => f.name.toLowerCase().endsWith(".blend"));
    if (fl.length) uploadFiles(fl);
    else toast("Solo se aceptan archivos .blend", "warn");
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
  status.textContent = "Subiendo " + fl.length + " archivo(s)…";
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/files/upload");
  xhr.upload.onprogress = e => {
    if (e.lengthComputable) status.textContent = "Subiendo… " + Math.round(e.loaded / e.total * 100) + "%";
  };
  xhr.onload = () => {
    status.textContent = "";
    if (xhr.status >= 200 && xhr.status < 300) toast("Archivos agregados; inspeccionando…", "ok");
    else toast("Error al subir (HTTP " + xhr.status + ")", "error");
    tick();
  };
  xhr.onerror = () => { status.textContent = ""; toast("Error de red al subir", "error"); };
  xhr.send(fd);
}

/* ============================ explorador de archivos ============================ */
const fs = { mode: "add", selected: new Set(), path: "", targetInput: null };

async function openFs(mode, targetInput = null, startPath = "") {
  fs.mode = mode;
  fs.targetInput = targetInput || null;
  if (startPath) fs.path = startPath;
  fs.selected = new Set();
  $("#fsTitle").textContent = mode === "pick-dir" ? "Elegir carpeta de salida" : "Seleccionar archivos .blend";
  $("#fsHint").textContent = mode === "pick-dir"
    ? "Navega a la carpeta y presiona “Usar esta carpeta”."
    : "Navega y marca los .blend que quieras agregar (se encolarán al inspeccionarse).";
  $("#fsPickDir").textContent = mode === "pick-dir" ? "Usar esta carpeta" : "Agregar todos los .blend de esta carpeta";
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
  }).join("") || '<div class="muted" style="padding:8px">(carpeta vacía)</div>';
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
  if (!paths.length) { toast("Selecciona al menos un .blend", "warn"); return; }
  try {
    await api("/api/files/add", { method: "POST", body: JSON.stringify({ paths }) });
    closeModal("fsModal");
    toast("Agregados: " + paths.length + " archivo(s); inspeccionando…", "ok");
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
    toast("Carpeta agregada; inspeccionando los .blend…", "ok");
  } catch (err) { toast(String(err.message || err), "error"); }
  tick();
});

/* ============================ ajustes ============================ */
function fillSettings() {
  if (!state) return;
  const s = state.settings || {}, b = state.blender || {};
  $("#setBlender").value = s.blender_path || b.path || "";
  $("#setNotif").checked = !!s.notifications;
  $("#setPreview").checked = !!s.preview_video;
  $("#setBlenderStatus").textContent = b.ok ? ("OK — " + b.version) : ("No encontrado — " + (b.error || ""));
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
    $("#setBlenderStatus").textContent = info.ok ? ("OK — " + info.version) : ("No encontrado — " + (info.error || ""));
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
    toast("Ajustes guardados", "ok");
    tick();
  } catch (err) { toast(String(err.message || err), "error"); }
});

$("#setNotifyTest").addEventListener("click", async () => {
  try { await api("/api/notify/test", { method: "POST" }); toast("Notificación de prueba enviada", "ok"); }
  catch (err) { toast(String(err.message || err), "error"); }
});

/* ============================ log ============================ */
async function viewLog(jid) {
  try {
    const d = await api("/api/jobs/" + jid + "/log?tail=500");
    $("#logContent").textContent = d.log || "(log vacío)";
    $("#logModal").classList.remove("hidden");
  } catch (err) { toast(String(err.message || err), "error"); }
}

/* ============================ modales genéricos ============================ */
function closeModal(id) { $("#" + id).classList.add("hidden"); }
$$(".modal").forEach(m => m.addEventListener("click", e => { if (e.target === m) m.classList.add("hidden"); }));
$$("[data-close]").forEach(b => b.addEventListener("click", () => closeModal(b.dataset.close)));
document.addEventListener("keydown", e => {
  if (e.key === "Escape") $$(".modal").forEach(m => m.classList.add("hidden"));
});

/* ============================ inicio ============================ */
$("#btnPause").addEventListener("click", async () => {
  try { await api("/api/queue/pause", { method: "POST", body: JSON.stringify({}) }); tick(); }
  catch (err) { toast(String(err.message || err), "error"); }
});

setupDropzone();
