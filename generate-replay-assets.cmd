@echo off
setlocal
set "REPOSITORY_ROOT=%~dp0"
set "PYTHONPATH=%REPOSITORY_ROOT%src;%REPOSITORY_ROOT%"
python "%REPOSITORY_ROOT%tools\generate_replay_assets.py" --output "%REPOSITORY_ROOT%assets\simulator-private\tw-replay-simulator-v1"
