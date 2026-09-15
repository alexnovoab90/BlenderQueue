@echo off
title BlendQueue
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" goto setup
goto run

:setup
echo [BlendQueue] Preparing the virtual environment...
where uv >nul 2>nul
if errorlevel 1 goto setuppip
uv venv .venv
uv pip install --python ".venv\Scripts\python.exe" -r requirements.txt
goto run

:setuppip
python -m venv .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt

:run
".venv\Scripts\python.exe" -c "import socket,sys; s=socket.socket(); s.settimeout(0.4); sys.exit(0 if s.connect_ex(('127.0.0.1',8777))==0 else 1)" >nul 2>nul
if errorlevel 1 goto serve
start "" http://127.0.0.1:8777/
exit /b 0

:serve
echo [BlendQueue] Starting at http://127.0.0.1:8777/  (to stop: the Quit button in the app, or close this window)
".venv\Scripts\python.exe" server.py
if errorlevel 1 pause
