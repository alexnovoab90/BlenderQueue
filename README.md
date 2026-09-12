# BlendQueue

Cola local de renders para Blender. Cargas archivos `.blend`, la app **inspecciona cada escena**
(rango de frames, motor, samples, cámara y carpeta de salida) y tú eliges qué se renderiza.
Un worker secuencial ejecuta los trabajos con Blender headless, muestra progreso en vivo en el
navegador, arma un preview MP4 de cada secuencia con ffmpeg y avisa con una **notificación de
Windows** al terminar.

## Uso diario

1. Doble clic en **`run.bat`** (hay un acceso directo en el Escritorio). Se abre `http://127.0.0.1:8777`.
2. Agrega archivos de dos formas:
   - **Seleccionar ruta del equipo…** → registra el `.blend` *en su lugar* (recomendado: conserva
     las texturas con rutas relativas). También puedes registrar una **carpeta completa** y se
     agregan todos sus `.blend`.
   - **Arrastrar y soltar** → copia el archivo a `data/uploads/` (ojo con proyectos que usan
     texturas relativas: la copia las rompe).
3. Espera la inspección: aparecen las escenas detectadas con frames, motor y salida de cada una.
4. Encola escenas con **overrides opcionales**: frames, motor (Cycles/EEVEE/Workbench), samples,
   GPU/CPU, resolución % y carpeta de salida. Sin overrides se respeta lo guardado en el `.blend`.
5. Sigue la cola en vivo. Al terminar cada trabajo: preview (video/frames), botón *Abrir carpeta
   de salida*, log completo y notificación de escritorio.

## Cómo renderiza (por dentro)

    blender.exe -b "archivo.blend" -S "Escena" [--python-expr overrides] -o "salida####" -s INICIO -e FIN -a

- **Sin override de salida** se usa tal cual la carpeta guardada en el `.blend`.
- **Con override** se escribe `<archivo>_<escena>_####.<ext>` en la carpeta elegida.
- Motor/samples/dispositivo se toman del archivo salvo override por trabajo.
- Cancelar mata el proceso Blender (`taskkill`); reintentar vuelve a encolar; reordenar con ↑/↓.
- Un solo render a la vez (Blender satura GPU/CPU); la inspección corre en paralelo con los renders.

## Estructura

    server.py                    servidor FastAPI + API (punto de entrada)
    core/                        store (estado), inspector, worker (cola), renderer, notifier, config
    blender_side/inspect_blend.py   script que corre DENTRO de Blender y reporta escenas en JSON
    static/                      interfaz web (HTML/CSS/JS sin build step)
    run.bat                      lanzador (crea el venv si falta)
    data/                        estado, logs por trabajo, uploads, salidas locales, previews
    data/tests/                  pruebas de humo

## Pruebas

    data\tests\run_smoke.bat quick     (también: multi | cycles)
    data\tests\run_smoke.bat real "G:/ruta/archivo.blend" [render]

## Problemas comunes

- **Blender no encontrado** → Ajustes → ruta de `blender.exe` (por defecto autodetecta el de
  `D:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe`).
- **Texturas rosadas / faltan archivos** → agrega el `.blend` por *ruta* (sin copiar) o empaqueta
  las texturas. El reporte de inspección muestra cuántos archivos externos faltan.
- **Puerto ocupado** → `run.bat` detecta si ya está corriendo y solo abre el navegador; para otro
  puerto: `.venv\Scripts\python.exe server.py --port 8888`.
- **Cerrar la ventana del servidor detiene la cola** (los trabajos en curso quedan marcados como
  interrumpidos y se pueden reintentar).
