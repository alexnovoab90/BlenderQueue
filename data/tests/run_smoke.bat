@echo off
cd /d "%~dp0\..\.."
".venv\Scripts\python.exe" data/tests/api_smoke.py %*
pause
