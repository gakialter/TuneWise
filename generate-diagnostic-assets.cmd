@echo off
setlocal
set "REPO_ROOT=%~dp0"
set "PYTHONPATH=%REPO_ROOT%src;%REPO_ROOT%"
python -m tools.generate_diagnostic_assets --output "%REPO_ROOT%assets\diagnostic\tw-diagnostic-v1" --seed 20260718
endlocal
