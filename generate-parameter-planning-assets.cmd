@echo off
setlocal
cd /d "%~dp0"
python -m tools.generate_parameter_planning_assets --output assets\planning\tw-parameter-planning-v1
