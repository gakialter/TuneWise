@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0"
python -m tools.validate_shadow_data %*
