@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
python -m tools.generate_demo_assets --output "%~dp0assets\demo\tw-aa-demo-v1" --seed 20260718
