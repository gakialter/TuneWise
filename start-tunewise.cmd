@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
python -m uvicorn tunewise.main:app --host 127.0.0.1 --port 8000
