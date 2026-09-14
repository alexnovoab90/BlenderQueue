@echo off
rem Pruebas de humo de BlendQueue. El servidor debe estar corriendo (run.bat).
rem   tests\run_smoke.bat quick | multi | cycles | format
rem   tests\run_smoke.bat real "G:/ruta/archivo.blend" [render]
cd /d "%~dp0\.."
if not exist "data\tests\quick.blend" (
  echo [BlendQueue] Faltan los .blend de prueba: generalos con
  echo     blender.exe -b --factory-startup --python tests\make_tests.py -- "%CD%\data\tests"
  pause
  exit /b 1
)
".venv\Scripts\python.exe" tests\api_smoke.py %*
pause
