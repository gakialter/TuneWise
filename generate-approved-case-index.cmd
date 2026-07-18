@echo off
setlocal
set "REPO_ROOT=%~dp0"
set "PYTHONPATH=%REPO_ROOT%src;%REPO_ROOT%"
python -m tools.generate_approved_case_index --output "%REPO_ROOT%assets\cases\tw-approved-case-index-v1" --seed 20260718 --diagnostic-manifest "%REPO_ROOT%assets\diagnostic\tw-diagnostic-v1\manifest.json"
endlocal
