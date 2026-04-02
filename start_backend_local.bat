@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0backend"
set "TASK_QUEUE_MODE=local"
set "PYTHONPATH=%CD%"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

call "%CD%\.venv\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
