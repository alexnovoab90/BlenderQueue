@echo off
rem BlendQueue smoke tests. The server must be running (run.bat).
rem   tests\run_smoke.bat quick | multi | cycles | format | script | overwrite | size | locate | fs | pause | interrupt
rem   tests\run_smoke.bat real "G:/path/file.blend" [render]
cd /d "%~dp0\.."
if not exist "data\tests\quick.blend" (
  echo [BlendQueue] The test .blend files are missing: generate them with
  echo     blender.exe -b --factory-startup --python tests\make_tests.py -- "%CD%\data\tests"
  pause
  exit /b 1
)
".venv\Scripts\python.exe" tests\api_smoke.py %*
pause
