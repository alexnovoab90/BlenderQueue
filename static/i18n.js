"use strict";

/* Interface languages.
 *
 * The text in the code is English (the default language) and this file only
 * holds the English -> Spanish map: the code reads without indirect keys and
 * adding another language is copying this object. Anything untranslated falls
 * back to English.
 *
 * Server messages (API errors, a job's error line) are always English: there
 * are few of them and most carry interpolated data.
 */
const LANGS = { en: "English", es: "Español" };

const ES = {
  // ---- header ----
  "BlendQueue — local render queue for Blender": "BlendQueue — cola local de renders Blender",
  "local render queue · headless Blender": "cola local de renders · Blender headless",
  "Pause queue": "Pausar cola",
  "Resume queue": "Reanudar cola",
  "Scripts": "Scripts",
  "Settings": "Ajustes",
  "⏻ Quit": "⏻ Cerrar",
  "Stop BlendQueue and close the server window": "Detener BlendQueue y cerrar la ventana del servidor",
  "Python script library": "Biblioteca de scripts de Python",
  "Interface language": "Idioma de la interfaz",
  "Blender: not found": "Blender: no encontrado",

  // ---- adding files ----
  "Drop your .blend files here": "Arrastra aquí tus .blend",
  "or": "o",
  "choose files…": "elegir archivos…",
  "Pick a path on this computer…": "Seleccionar ruta del equipo…",
  "rendered in place, without copying": "se renderiza en su lugar, sin copiar",
  "Dropped files are looked up on disk and rendered where they are, so their relative textures and linked files keep working. A copy into":
    "Los archivos arrastrados se buscan en el disco y se renderizan donde están, así sus texturas relativas y archivos enlazados siguen funcionando. Solo se hace una copia en",
  "is only made if you ask for it. You can also register a whole folder and every .blend inside is added.":
    "si tú lo pides. También puedes registrar una carpeta completa y se agregan todos sus .blend.",
  "Only .blend files are accepted": "Solo se aceptan archivos .blend",
  "Files added; inspecting…": "Archivos agregados; inspeccionando…",
  "Network error while uploading": "Error de red al subir",
  "Found on disk, rendered in place: {list}": "Encontrado en el disco, se renderiza donde está: {list}",
  "Where is this file?": "¿Dónde está este archivo?",
  "The browser does not tell BlendQueue where a dropped file lives, and it was not found in the folders you already use. A copy cannot see the textures and linked .blend files next to the original, so they would render missing.":
    "El navegador no le dice a BlendQueue dónde está un archivo arrastrado, y no apareció en las carpetas que ya usas. Una copia no ve las texturas ni los .blend enlazados que están junto al original, así que saldrían faltantes en el render.",
  "Upload a copy anyway": "Subir una copia igual",
  "Only for a .blend that has everything packed inside": "Solo para un .blend que trae todo empaquetado",
  "Find it on disk…": "Buscarlo en el disco…",

  // ---- files and scenes ----
  "Files": "Archivos",
  "No files yet. Drop a .blend above or use “Pick a path on this computer…”.":
    "Aún no hay archivos. Arrastra un .blend arriba o usa “Seleccionar ruta del equipo…”.",
  "ready": "listo",
  "inspecting…": "inspeccionando…",
  "waiting": "en espera",
  "error": "error",
  "Re-inspect": "Re-inspeccionar",
  "Open folder": "Abrir carpeta",
  "Remove": "Quitar",
  "+ Queue all scenes": "+ Encolar todas las escenas",
  "+ Queue": "+ Encolar",
  "Overrides…": "Overrides…",
  "📁 Output…": "📁 Salida…",
  "Choose the output folder for this scene": "Elegir carpeta de salida para esta escena",
  "Choose folder…": "Elegir carpeta…",
  "Re-inspecting…": "Re-inspeccionando…",
  "Remove this file from the list? (it is not deleted from disk)":
    "¿Quitar este archivo de la lista? (no se borra del disco)",
  "Remove this file from the list? Its copy in data/uploads is deleted; your original is not touched.":
    "¿Quitar este archivo de la lista? Se borra su copia en data/uploads; tu original no se toca.",
  "uploaded copy": "copia subida",
  "A copy in data/uploads, not the original file": "Una copia en data/uploads, no el archivo original",
  "Locate the original…": "Buscar el original…",
  "This copy cannot find {n} file(s) referenced relative to the original folder: textures and linked .blend files would render missing.":
    "Esta copia no encuentra {n} archivo(s) referenciados de forma relativa a la carpeta original: las texturas y los .blend enlazados saldrían faltantes en el render.",
  "{n} external file(s) missing: they would render missing.":
    "Faltan {n} archivo(s) externos: saldrían faltantes en el render.",
  "Includes {n} linked .blend: {names}.": "Incluye {n} .blend enlazado(s): {names}.",
  "Show the list": "Ver la lista",
  "… and {n} more": "… y {n} más",
  "Found the original:\n{p}\n\nRender that one and delete the copy?":
    "Se encontró el original:\n{p}\n\n¿Renderizar ese y borrar la copia?",
  "Now using the original; the copy was deleted. Inspecting…":
    "Ahora se usa el original; la copia se borró. Inspeccionando…",
  "The original was already in the list: the copy was removed.":
    "El original ya estaba en la lista: se quitó la copia.",
  "output format": "formato de salida",
  "format forced for this job": "formato forzado para este trabajo",
  "format saved in the .blend": "formato guardado en el .blend",
  "Python script for this job": "script de Python de este trabajo",

  // ---- overrides ----
  "Frames": "Frames",
  "Engine": "Motor",
  "Samples": "Samples",
  "Device": "Dispositivo",
  "Size": "Tamaño",
  "Width × height of the render, in pixels. Leave one empty to keep the .blend's aspect ratio.":
    "Ancho × alto del render, en píxeles. Si dejas uno vacío se mantiene la proporción del .blend.",
  "size forced for this job": "tamaño forzado para este trabajo",
  "size saved in the .blend": "tamaño guardado en el .blend",
  "Video needs an even size: {a} is rendered as {b}": "El video necesita un tamaño par: {a} se renderiza como {b}",
  "Script": "Script",
  "Output": "Salida",
  "Format": "Formato",
  "Depth": "Profundidad",
  "Color": "Color",
  "EXR codec": "Códec EXR",
  "Container": "Contenedor",
  "Video codec": "Códec de video",
  "Quality %": "Calidad %",
  "Compression %": "Compresión %",
  "OUTPUT FORMAT": "FORMATO DE SALIDA",
  "(from the file)": "(del archivo)",
  "(the file's)": "(la del archivo)",
  "(the file's one)": "(el del archivo)",
  "(default)": "(por defecto)",
  "(none)": "(ninguno)",
  "(the .blend default)": "(por defecto del .blend)",
  "Others": "Otros",
  "bits": "bits",
  "BW (grayscale)": "BW (gris)",
  "RGBA (with alpha)": "RGBA (con alfa)",

  "no overwrite": "sin sobrescribir",
  "This scene skips frames that already exist (Overwrite is off in the .blend)":
    "Esta escena salta los frames que ya existen (Overwrite desmarcado en el .blend)",
  "Existing frames": "Frames existentes",
  "Overwrite": "Sobrescribir",
  "Skip existing": "Saltar los existentes",
  "Blender either skips these files or replaces them, and it does it silently. Pick what this job should do — the .blend is not modified either way.":
    "Blender los salta o los reemplaza, y lo hace en silencio. Elige qué debe hacer este trabajo; el .blend no se modifica en ninguno de los dos casos.",
  "Render only the frames that are missing": "Renderizar solo los frames que faltan",
  "Render every frame again, replacing the files": "Renderizar todos de nuevo, reemplazando los archivos",
  "{label}: {n} file(s) already exist for frames {a}-{b}.":
    "{label}: ya existen {n} archivo(s) para los frames {a}-{b}.",

  // ---- queue ----
  "Render queue": "Cola de renders",
  "Output format…": "Formato de salida…",
  "Change the output format of the queued jobs": "Cambiar el formato de salida de los trabajos en cola",
  "Script…": "Script…",
  "Apply a Python script to the queued jobs": "Aplicar un script de Python a los trabajos en cola",
  "The queue is empty. Inspect a file and queue its scenes.":
    "La cola está vacía. Inspecciona un archivo y encola sus escenas.",
  "queued": "en cola",
  "rendering": "renderizando",
  "done": "listo",
  "canceled": "cancelado",
  "Move up": "Subir",
  "Move down": "Bajar",
  "Cancel": "Cancelar",
  "Retry": "Reintentar",
  "Details": "Detalles",
  "📂 Open folder": "📂 Abrir carpeta",
  "Open the output folder in your file manager": "Abrir la carpeta de salida en el explorador de archivos",
  "🎞 Format": "🎞 Formato",
  "Change the output format of this job": "Cambiar el formato de salida de este trabajo",
  "⚙ Script": "⚙ Script",
  "Add or remove a Python script for this job": "Poner o quitar un script de Python a este trabajo",
  "Python script that runs before rendering": "script de Python que corre antes de renderizar",
  "Queued jobs do not all write the same format. Use “Output format…” to unify them.":
    "Los trabajos en cola no escriben todos el mismo formato. Usa «Formato de salida…» para unificarlos.",
  "Queued: ": "Encolado: ",
  "⏸ Pause": "⏸ Pausar",
  "▶ Resume": "▶ Reanudar",
  "paused": "en pausa",
  "Freeze this render where it is. Blender keeps its memory, so resuming continues the same frame.":
    "Congela este render donde va. Blender conserva su memoria, así que al reanudar sigue en el mismo frame.",
  "Continue the render exactly where it stopped": "Seguir el render justo donde quedó",
  "Stops starting new jobs; the render in progress keeps going. To freeze a render, use ⏸ Pause on its card.":
    "Deja de empezar trabajos nuevos; el render en curso sigue. Para congelar un render usa ⏸ Pausar en su tarjeta.",
  "In Blender: {what}": "En Blender: {what}",
  "The job is no longer in the queue": "El trabajo ya no está en la cola",

  // ---- job details ----
  "No output data.": "Sin datos de salida.",
  "Nothing to show yet.": "Aún sin salidas para mostrar.",
  "Open output folder": "Abrir carpeta de salida",
  "View log": "Ver log",
  "preview MP4 not available": "preview MP4 no disponible",
  ": the browser cannot display these files": ": el navegador no puede mostrar estos archivos",
  "Job log": "Log del trabajo",
  "(empty log)": "(log vacío)",
  "Frame": "Frame",
  "use ← → to browse": "usa ← → para navegar",

  // ---- format modal ----
  "Output format": "Formato de salida",
  "Job format": "Formato del trabajo",
  "Queue format": "Formato de la cola",
  "Apply": "Aplicar",
  "Each scene keeps the format saved in its .blend.": "Cada escena conserva el formato guardado en su .blend.",
  "Applied when rendering, on an in-memory copy: the .blend file is never modified. With “the file's one” each scene keeps what it has.":
    "Se aplica al renderizar, sobre una copia en memoria: el archivo .blend nunca se modifica. Con «el del archivo» se respeta lo que trae cada escena.",
  "Still loading Blender's formats…": "Aún cargando los formatos de Blender…",
  "Format updated": "Formato actualizado",
  "No queued jobs": "No había trabajos en cola",

  // ---- script modal ----
  "Python scripts": "Scripts de Python",
  "Choose script": "Elegir script",
  "They are stored in the app and will still be here next time.":
    "Se guardan en la app y siguen aquí la próxima vez.",
  "New": "Nuevo",
  "Duplicate": "Duplicar",
  "Delete": "Borrar",
  "Name": "Nombre",
  "Clean duplicate materials": "Limpiar materiales duplicados",
  "Python code — runs inside Blender, right before rendering":
    "Código Python — corre dentro de Blender, justo antes de renderizar",
  "It runs after the overrides, so it can change anything (including the format). If it raises, the job ends in":
    "Se ejecuta después de los overrides, así que puede cambiar cualquier cosa (incluido el formato). Si lanza una excepción el trabajo queda en",
  "with the traceback in its log and nothing is rendered. The .blend is never modified: the changes live only in the Blender session that renders that job.":
    "con el traceback en su log, sin renderizar. El .blend nunca se modifica: los cambios viven solo en la sesión de Blender que hace ese render.",
  "Save": "Guardar",
  "Apply to the job": "Aplicar al trabajo",
  "Apply to the queue": "Aplicar a la cola",
  "no script": "sin script",
  "Untitled": "Sin nombre",
  " (copy)": " (copia)",
  "Unsaved changes in the script. Discard them?": "Hay cambios sin guardar en el script. ¿Descartarlos?",
  "Script saved": "Script guardado",
  "Script deleted": "Script borrado",
  "Script applied to the job": "Script aplicado al trabajo",
  "Script removed from the job": "Script quitado del trabajo",

  // ---- file browser ----
  "Select .blend files": "Seleccionar archivos .blend",
  "Choose output folder": "Elegir carpeta de salida",
  "↑ Up": "↑ Subir",
  "Go": "Ir",
  "Type a path and press Go": "Escribe una ruta y presiona Ir",
  "Browse and tick the .blend files you want to add.": "Navega y marca los .blend que quieras agregar.",
  "Browse and tick the .blend files you want to add (they are queued once inspected).":
    "Navega y marca los .blend que quieras agregar (se encolarán al inspeccionarse).",
  "Browse to the folder and press “Use this folder”.": "Navega a la carpeta y presiona «Usar esta carpeta».",
  "Use this folder": "Usar esta carpeta",
  "Add every .blend in this folder": "Agregar todos los .blend de esta carpeta",
  "Add selected": "Agregar seleccionados",
  "Select at least one .blend": "Selecciona al menos un .blend",
  "Locate the original .blend": "Buscar el .blend original",
  "Tick the original .blend: it is rendered where it is and the copy is deleted.":
    "Marca el .blend original: se renderiza donde está y la copia se borra.",
  "Use this file": "Usar este archivo",
  "Tick exactly one .blend": "Marca un solo .blend",
  "New folder…": "Nueva carpeta…",
  "Create a folder here and open it": "Crear una carpeta aquí y entrar en ella",
  "Name of the new folder:": "Nombre de la carpeta nueva:",
  "Folder created: {name}": "Carpeta creada: {name}",
  "(empty folder)": "(carpeta vacía)",
  "Folder added; inspecting the .blend files…": "Carpeta agregada; inspeccionando los .blend…",

  // ---- settings ----
  "Path to Blender": "Ruta de Blender",
  "Check": "Verificar",
  "Desktop notification when each render finishes": "Notificación de escritorio al terminar cada render",
  "Build an MP4 preview video of each sequence": "Generar video MP4 de preview de cada secuencia",
  "Each job's output is set per scene: by default the folder saved in the .blend is used; you can change it in the scene overrides.":
    "La salida de cada trabajo se define por escena: por defecto se respeta la carpeta guardada en el .blend; puedes cambiarla en los overrides de cada escena.",
  "Test notification": "Probar notificación",
  "Save settings": "Guardar ajustes",
  "Settings saved": "Ajustes guardados",
  "Test notification sent": "Notificación de prueba enviada",
  "Not found": "No encontrado",

  // ---- shutdown ----
  "Quit BlendQueue?\nThe queue stops and the server shuts down (its window closes).":
    "¿Cerrar BlendQueue?\nSe detiene la cola y se apaga el servidor (la ventana se cierra).",
  "BlendQueue is shutting down… you can close this tab now.":
    "BlendQueue se está cerrando… ya puedes cerrar esta pestaña.",

  // ---- format catalog (sent by the server) ----
  "OpenEXR multilayer": "OpenEXR multicapa",
  "Video (FFmpeg)": "Video (FFmpeg)",
  "Uncompressed Targa": "Targa sin comprimir",
  "Uncompressed AVI": "AVI sin comprimir",
  "Uncompressed": "Sin comprimir",
  "ZIP (blocks)": "ZIP (bloques)",
  "ZIPS (per line)": "ZIPS (por línea)",
  "Pxr24 (lossy)": "Pxr24 (con pérdida)",
  "B44 (lossy)": "B44 (con pérdida)",
  "B44A (lossy)": "B44A (con pérdida)",
  "DWAA (lossy)": "DWAA (con pérdida)",
  "DWAB (lossy)": "DWAB (con pérdida)",
  "FFV1 (lossless)": "FFV1 (sin pérdida)",
  "HuffYUV (lossless)": "HuffYUV (sin pérdida)",
  "QuickTime RLE (alpha)": "QuickTime RLE (con alfa)",
  "PNG (alpha)": "PNG (con alfa)",
  "No video": "Sin video",

  // ---- plurals and phrases with data ----
  "{n} file(s)": "{n} archivo(s)",
  "saved with Blender {v}": "guardado con Blender {v}",
  "inspection {s} s": "inspección {s} s",
  "{o} objects · {s} scene(s)": "{o} objetos · {s} escena(s)",
  "{a}–{b} · {n} frames": "{a}–{b} · {n} frames",
  "{q} queued · {r} rendering · {d} done": "{q} en cola · {r} renderizando · {d} listos",
  "mixed formats: {list}": "formatos mezclados: {list}",
  "queued · frames {a}–{b}": "en cola · frames {a}–{b}",
  "frame {f} of {t} · {p}% · {e} elapsed": "frame {f} de {t} · {p}% · {e} transcurrido",
  " · last frame {s}": " · último frame {s}",
  "paused · frame {f} of {t} · {p}% · {e} rendered": "en pausa · frame {f} de {t} · {p}% · {e} renderizado",
  " · {n} paused": " · {n} en pausa",
  " · {s} per frame": " · {s} por frame",
  " · left {x}": " · resto {x}",
  " · left ~{x}": " · resto ~{x}",
  "done · {n} file(s) · {d}": "listo · {n} archivo(s) · {d}",
  "error: {e}": "error: {e}",
  "frames {a}–{b}": "frames {a}–{b}",
  "{n} output file(s)": "{n} archivo(s) de salida",
  "no preview ({why})": "sin preview ({why})",
  "{i} of {n} · ": "{i} de {n} · ",
  "Output: one video file {ext}": "Salida: un archivo de video {ext}",
  "Output: a sequence of {ext} files": "Salida: secuencia de archivos {ext}",
  "{f} · {s} — now writes: {fmt}": "{f} · {s} — ahora escribe: {fmt}",
  "{f} · {s} — now: {script}": "{f} · {s} — ahora: {script}",
  "Applies to the {n} queued job(s); finished ones are left alone.":
    "Se aplica a los {n} trabajo(s) en cola; los que ya terminaron no se tocan.",
  "Applies to the {n} queued job(s).": "Se aplica a los {n} trabajo(s) en cola.",
  "Format applied to {n} job(s)": "Formato aplicado a {n} trabajo(s)",
  "Script applied to {n} job(s)": "Script aplicado a {n} trabajo(s)",
  "Script removed from {n} job(s)": "Script quitado de {n} trabajo(s)",
  "Delete «{name}» from the library?\nJobs that already carry it keep their copy.":
    "¿Borrar «{name}» de la biblioteca?\nLos trabajos que ya lo llevan conservan su copia.",
  "Uploading {n} file(s)…": "Subiendo {n} archivo(s)…",
  "Uploading… {p}%": "Subiendo… {p}%",
  "Upload error (HTTP {s})": "Error al subir (HTTP {s})",
  "Added: {n} file(s); inspecting…": "Agregados: {n} archivo(s); inspeccionando…",
  "OK — {v}": "OK — {v}",
  "Not found — {e}": "No encontrado — {e}",
  "Video {ext}": "Video {ext}",
};

const DICTS = { en: null, es: ES };
const LANG_KEY = "blendqueue.lang";

let LANG = "en";
try {
  const saved = localStorage.getItem(LANG_KEY);
  if (saved && DICTS[saved] !== undefined) LANG = saved;
} catch (e) { /* browser without storage: English */ }

/** Translates an English string into the active language (unchanged if missing). */
function t(text) {
  const d = DICTS[LANG];
  return (d && d[text]) || text;
}

/** Like t() but filling {placeholders}: tf("{n} file(s)", { n: 3 }). */
function tf(text, vars) {
  let out = t(text);
  for (const [k, v] of Object.entries(vars || {})) out = out.split("{" + k + "}").join(String(v));
  return out;
}

/** Applies the language to the static HTML (data-i18n, data-i18n-title, data-i18n-ph). */
function applyLang() {
  document.documentElement.lang = LANG;
  document.title = t("BlendQueue — local render queue for Blender");
  for (const el of document.querySelectorAll("[data-i18n]")) {
    if (el.dataset.en === undefined) el.dataset.en = el.textContent.trim();
    el.textContent = t(el.dataset.en);
  }
  for (const el of document.querySelectorAll("[data-i18n-title]")) {
    if (el.dataset.enTitle === undefined) el.dataset.enTitle = el.title;
    el.title = t(el.dataset.enTitle);
  }
  for (const el of document.querySelectorAll("[data-i18n-ph]")) {
    if (el.dataset.enPh === undefined) el.dataset.enPh = el.placeholder;
    el.placeholder = t(el.dataset.enPh);
  }
}

function setLang(lang) {
  if (DICTS[lang] === undefined) return;
  LANG = lang;
  try { localStorage.setItem(LANG_KEY, lang); } catch (e) { /* not important */ }
  applyLang();
}
