# BlendQueue

**Cola local de renders para Blender.** Cargas tus archivos `.blend`, BlendQueue **inspecciona
cada escena** en headless (rango de frames, motor, samples, cámara, formato y carpeta de salida)
y tú eliges qué se renderiza. Un worker secuencial ejecuta los trabajos con Blender en segundo
plano, muestra el progreso en vivo en el navegador (incluido cuánto tardó el último frame), arma
un preview MP4 con ffmpeg y avisa con una notificación de Windows al terminar cada uno.

Sin nube, sin cuentas, sin telemetría: un servidor FastAPI en `127.0.0.1` y una interfaz
HTML/CSS/JS sin paso de compilación.

*[Read this in English](README.md)*

![BlendQueue](docs/screenshot.png)

La interfaz sale en **inglés** por defecto; en la cabecera hay un selector **EN / ES** y la
elección se recuerda en ese navegador.

## Para qué sirve

Renderizar varios `.blend` seguidos suele significar quedarse mirando una consola, o abrir cada
archivo solo para ver su rango de frames y su configuración de salida. BlendQueue te lleva la
cola: lee lo que cada escena tiene configurado de verdad, te deja sobrescribir lo que quieras
(frames, motor, samples, GPU/CPU, **tamaño en píxeles**, **formato de salida**, carpeta destino) y ejecuta
un trabajo a la vez para que Blender no pelee consigo mismo por la GPU.

## Requisitos

| | |
|---|---|
| Sistema | Windows 10/11, macOS o Linux — ver [Soporte por sistema](#soporte-por-sistema) |
| Blender | 3.x, 4.x o 5.x (autodetectado: instalador, Steam, `PATH` o `BLENDQUEUE_BLENDER`) |
| Python | 3.10+ (`run.bat` / `run.sh` crea el entorno virtual solo) |
| ffmpeg | opcional, en el `PATH` — solo para los previews MP4 |

## Soporte por sistema

Todo lo que depende del sistema vive en un solo archivo, `core/system.py`: abrir una carpeta,
matar un render con sus hijos, dónde está instalado Blender y las raíces del explorador.

| | Windows | macOS | Linux |
|---|---|---|---|
| Cola, render, previews, scripts | sí | sí | sí |
| Abrir la carpeta de salida | Explorador | `open` | `xdg-open` |
| Notificación de escritorio | toast | `osascript` | `notify-send` |
| Lanzador | `run.bat` | `./run.sh` | `./run.sh` |

**Verificado en Windows 11** (suite completa de humo) **y en Linux** (Ubuntu sobre WSL: raíces del
explorador, búsqueda de Blender, matar un render con sus hijos y degradación sin escritorio).
**macOS está escrito pero sin probar** — si lo corres ahí, se agradece el reporte.

Sin sesión de escritorio esas dos funciones devuelven un mensaje claro en vez de fallar, así que
BlendQueue sigue renderizando en una máquina sin entorno gráfico.

## Instalación y uso diario

```bash
git clone https://github.com/alexnovoab90/BlenderQueue.git
```

Doble clic en **`run.bat`** (Windows) o `./run.sh` (macOS y Linux): crea `.venv` (con
[uv](https://github.com/astral-sh/uv) si lo tienes, si no con `pip`), instala las dependencias y
abre <http://127.0.0.1:8777>. Si el servidor ya está corriendo, solo abre el navegador.

Otro puerto:

```bat
.venv\Scripts\python.exe server.py --port 8888 --no-browser    :: Windows
```

```bash
.venv/bin/python server.py --port 8888 --no-browser            # macOS y Linux
```

Luego, en la interfaz:

1. Agrega archivos (ver abajo) y espera la inspección: aparecen las escenas con sus frames,
   motor, resolución, formato y salida.
2. Encola escenas con los overrides que quieras. Sin overrides se respeta lo guardado en el `.blend`.
3. Sigue la cola en vivo. Al terminar cada trabajo tienes preview (video o frames), botón
   *Abrir carpeta de salida*, log completo y notificación de escritorio.

## Cómo agregar archivos

- **Seleccionar ruta del equipo…** → registra el `.blend` *en su lugar*. También puedes
  registrar una carpeta completa y se agregan todos sus `.blend`.
- **Arrastrar y soltar** (o *elegir archivos…*) → el navegador nunca le dice a una página dónde
  está un archivo arrastrado, así que BlendQueue primero lo busca: mismo nombre, tamaño y fecha,
  en las carpetas donde ya trabajas (las de tus otros archivos y tus carpetas de render recientes,
  y las que están al lado). Si lo encuentra, lo renderiza donde está. Si no, te pide buscarlo en
  el disco, o subir igual una copia a `data/uploads/`.

Una copia no ve las texturas ni los `.blend` enlazados que están junto al original: Blender
resuelve las rutas `//` contra la carpeta de la copia y los renderiza faltantes. Cada archivo
avisa de los externos que faltan, y una copia subida tiene **Buscar el original…**, que la
reemplaza por el original (los trabajos en cola lo siguen y la copia se borra). Quitar una copia
subida de la lista también la borra; tu original nunca se toca.

La inspección corre en paralelo con los renders, así que agregar archivos nunca frena la cola.

## Tamaño del render

*Overrides…* → **Tamaño** recibe el ancho y el alto del render en píxeles, lo que necesites:
1280 × 720 o 1080 × 1350 da lo mismo. Si dejas un lado vacío se mantiene la proporción del
`.blend`. Lo que escribes es el tamaño del archivo: el porcentaje de resolución del `.blend`
vuelve a 100 %.

Los códecs de video como H.264 necesitan ancho y alto pares. Con un tamaño impar Blender no
logra iniciar el codificador y termina como si todo hubiera salido bien, sin escribir nada; por
eso BlendQueue baja un tamaño de video impar al par más cercano (un píxel como máximo) y lo deja
anotado en el log. La etiqueta de la escena siempre muestra el tamaño que se va a renderizar.

## Cambiar el formato de salida

Cada escena muestra el formato guardado en el `.blend` (PNG 8, OpenEXR multicapa 32, Video .mp4…).
Puedes sobrescribirlo **por trabajo**, sin tocar nunca el archivo `.blend`:

- **Antes de encolar** — en *Overrides…* de cada escena.
- **Ya encolado** — botón *Formato* de cualquier trabajo en cola, o **Formato de salida…** en la
  cabecera de la cola para aplicar un formato a todos de una vez. Es el caso típico: encolas
  archivos de distintos proyectos y uno venía guardado con otro formato. La cabecera te avisa
  (`formatos mezclados: …`) y con un clic queda todo unificado.

Las opciones disponibles salen de lo que reporta tu Blender: formato, profundidad de color, modo
de color, calidad/compresión, códec EXR, y contenedor + códec de video para FFmpeg. Al cambiar a
un formato de película se escribe un único archivo en vez de una secuencia numerada, y el preview
se adapta (el EXR lineal lo convierte ffmpeg; el EXR multicapa no tiene preview porque ffmpeg no
sabe leerlo).

## Frames que ya existen

Antes de encolar, BlendQueue mira la carpeta de salida. Si los frames ya están ahí te pregunta qué
hacer, porque Blender hace cualquiera de las dos cosas en silencio:

- **Sobrescribir** — renderiza todo de nuevo, reemplazando los archivos.
- **Saltar los existentes** — renderiza solo lo que falta, que es como se retoma una secuencia
  interrumpida.

Una escena cuyo `.blend` tiene Overwrite desmarcado lleva una etiqueta **sin sobrescribir**, y la
misma elección está en *Overrides…* como *Frames existentes*. Si un render termina sin escribir
nada porque se saltó todos los frames, el trabajo lo dice en vez de reportar un éxito mudo con
cero archivos.

## Scripts de Python por trabajo

Lo que no cubren los overrides, lo cubre un script: borrar materiales duplicados, cambiar el
mundo por un HDRI, armar un nodo de composición, apagar una colección.

Tienes una biblioteca con nombres (botón **Scripts** en la cabecera) y el script se aplica igual
que el formato: en una escena antes de encolar, en un trabajo ya en cola, o a toda la cola de una
vez. Corre dentro de Blender justo antes del render, *después* de los overrides de la app, así
que puede cambiar cualquier cosa, incluido lo que acaba de poner BlendQueue.

Tu código recibe `bpy`, `sc` (la escena de ese trabajo, resuelta por nombre) y `blend_path`, y
trabaja sobre la copia en memoria de Blender: **el .blend nunca se modifica**. Si lanza una
excepción el trabajo queda en error con la excepción en su línea de error y el traceback completo
en el log — nada de descubrir a las 3 horas que los 500 frames salieron mal. Lo que se ejecutó
exactamente queda guardado en `data/scripts/job_<id>.py`.

Al aplicar un script se guarda una copia en el trabajo, así que editar la biblioteca después no
cambia lo que van a ejecutar los trabajos que ya estaban en cola.

```python
# cambiar el mundo por un HDRI
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

## Cómo renderiza (por dentro)

```
blender.exe -b "archivo.blend" -S "Escena" [--python-exit-code 1] [--python-expr overrides]
            [--python data/scripts/job_<id>.py] --python-expr chequeos-finales
            -o "salida####" -s INICIO -e FIN -a
```

Lo que va entre corchetes solo aparece cuando ese trabajo lo necesita.

- **Sin override de salida** se usa tal cual la carpeta guardada en el `.blend`.
- **Con override** se escribe `<archivo>_<escena>_####.<ext>` en la carpeta elegida. El
  selector de carpetas tiene **Nueva carpeta…** para crear una en el momento.
- Motor, samples y dispositivo se toman del archivo salvo override por trabajo.
- Los overrides se aplican con un fragmento de Python generado que corre dentro de Blender. Cada
  asignación va protegida: un valor no soportado deja una línea en el log en vez de tumbar el
  render (eso también absorbe el rename `BLENDER_EEVEE` / `BLENDER_EEVEE_NEXT` entre versiones).
- El script de un trabajo va como `--python` *después* de la expresión, junto con
  `--python-exit-code 1` para que una excepción en el script haga fallar el trabajo.
- Una última expresión corre después de todo: baja a par los tamaños de video impares e imprime
  el motor, los samples y el tamaño con que Blender va a renderizar. La tarjeta del trabajo
  muestra esa línea (*En Blender: EEVEE · 10 spp · 1280×720 px*), así que un override que no se
  aplicó no pasa desapercibido.
- Blender reporta algunas fallas y aun así sale con código 0 — por ejemplo, un codificador de
  video que no arranca. Un trabajo que no escribió nada termina en **error** con el mensaje de
  Blender, salvo que los frames se hayan saltado a propósito (ver
  [Frames que ya existen](#frames-que-ya-existen)).
- Cancelar mata Blender junto con sus procesos hijos; reintentar vuelve a encolar; ↑/↓ reordenan.
- Un solo render a la vez: Blender ya satura GPU/CPU.

## Estructura

```
server.py                       servidor FastAPI + API (punto de entrada)
core/config.py                  rutas, detección de Blender, chequeo de versión cacheado
core/store.py                   estado persistente (JSON atómico): archivos, trabajos, ajustes
core/inspector.py               carril de inspección: corre Blender headless por cada .blend
core/worker.py                  worker secuencial: proceso, progreso, previews, notificaciones
core/renderer.py                armado del comando, código de overrides, parseo, ffmpeg
core/formats.py                 catálogo de formatos de salida y validación de overrides
core/system.py                  todo lo del sistema: abrir carpeta, matar procesos, buscar Blender
core/notifier.py                notificaciones de escritorio (toast / osascript / notify-send)
blender_side/inspect_blend.py   corre DENTRO de Blender y reporta escenas y capacidades en JSON
static/                         interfaz web (sin build)
static/i18n.js                  idiomas de la interfaz (inglés en el código + mapa al español)
tests/                          pruebas de humo y generador de .blend de prueba
run.bat, run.sh                 lanzadores: crean el venv si falta y levantan la app
data/                           estado, logs y scripts por trabajo, uploads, previews (fuera de git)
```

El servidor nunca importa `bpy`: todo lo de Blender ocurre en un subproceso, por eso BlendQueue
funciona con la instalación de Blender que le apuntes.

## Pruebas

Las pruebas de humo llaman a la API HTTP real contra un servidor corriendo y renderizan frames
de verdad. Genera los archivos de prueba una vez:

```bat
blender.exe -b --factory-startup --python tests/make_tests.py -- "%CD%/data/tests"
```

Y con BlendQueue abierto:

```bat
tests\run_smoke.bat quick
```

Modos: `quick` (secuencia EEVEE), `multi` (selección de escena con `-S`), `cycles` (GPU),
`format` (overrides de formato: EXR, video, editar un trabajo en cola, aplicar a toda la cola),
`script` (scripts por trabajo: biblioteca, efecto real en el render, copia congelada, fallo),
`overwrite` (frames existentes: preflight, saltarlos, forzar la sobrescritura),
`size` (tamaño en píxeles, tamaños de video impares, un render que no escribe nada y sale con
código 0), `locate` (archivos arrastrados encontrados en el disco, copias reemplazadas por su
original), `fs` (crear una carpeta desde el selector) y `real "G:/ruta/archivo.blend" [render]`
para uno de tus propios archivos.

Para probar mientras BlendQueue está renderizando, levanta un segundo servidor con su propia
carpeta de datos; así las pruebas nunca tocan tu cola:

```bash
BLENDQUEUE_DATA=/tmp/bq-test .venv/bin/python server.py --port 8790 --no-browser
BLENDQUEUE_URL=http://127.0.0.1:8790 .venv/bin/python tests/api_smoke.py size
```

## Problemas comunes

- **Blender no encontrado** → Ajustes → ruta de `blender.exe`, o define `BLENDQUEUE_BLENDER`.
- **Texturas rosadas / faltan archivos** → lee el aviso en la tarjeta del archivo. Una copia
  subida pierde todas las rutas relativas al original: usa **Buscar el original…**. Si no, los
  archivos también faltan junto al original — corrige las rutas en Blender o empaquétalos.
- **«Blender rendered nothing: …»** → es el error del propio Blender (un códec que no acepta ese
  tamaño, falta la cámara…). *Ver log* tiene la salida completa.
- **Puerto ocupado** → el lanzador detecta si ya está corriendo y solo abre el navegador.
- **«This system cannot open a file manager» (Linux)** → instala `xdg-utils`, o usa la ruta que
  muestra el trabajo. Igual con las notificaciones: necesitan `notify-send` (`libnotify-bin`).
- **Cerrar la ventana del servidor detiene la cola** → los trabajos en curso quedan marcados como
  interrumpidos y se pueden reintentar. Mejor usa el botón ⏻ de la cabecera.

## Nota de seguridad

BlendQueue es una herramienta local: lista carpetas, abre ventanas del Explorador y lanza Blender.
El servidor escucha solo en `127.0.0.1` y rechaza las peticiones cuyo `Host` u `Origin` no sean
locales, para que ninguna otra página del navegador pueda manejarlo. No lo expongas a la red.

## Licencia

MIT — ver [LICENSE](LICENSE). Se aceptan issues y PRs en
<https://github.com/alexnovoab90/BlenderQueue>.
