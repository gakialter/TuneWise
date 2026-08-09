@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "TUNEWISE_VENV_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%TUNEWISE_VENV_PYTHON%" (
  echo [TuneWise] Missing virtual environment Python: "%TUNEWISE_VENV_PYTHON%" 1>&2
  echo [TuneWise] Install with: py -3.12 -m venv .venv ^&^& .venv\Scripts\python.exe -m pip install -e ".[test]" 1>&2
  exit /b 2
)
"%TUNEWISE_VENV_PYTHON%" -m tunewise.opcua_sandbox --endpoint "opc.tcp://127.0.0.1:4841/tunewise/opcua-sandbox/" --fault NORMAL
exit /b %ERRORLEVEL%
