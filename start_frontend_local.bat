@echo off
chcp 65001 >nul
setlocal

if exist "C:\Program Files\nodejs\npm.cmd" (
    set "PATH=C:\Program Files\nodejs;%PATH%"
)

cd /d "%~dp0frontend"
set "VITE_API_PROXY_TARGET=http://127.0.0.1:8000"

call npm run dev -- --host 0.0.0.0
