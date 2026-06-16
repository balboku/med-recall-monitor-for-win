@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0backend"
set "TASK_QUEUE_MODE=local"
set "PYTHONPATH=%CD%"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem 注意：本專案位於 OneDrive 同步資料夾，--reload 的檔案監看在此並不可靠
rem （改了程式碼常不會真的重載，且關閉時容易殘留孤兒 worker 程序繼續用舊碼服務 8000）。
rem 因此改為不帶 --reload：啟動即載入「當前」程式碼，Ctrl+C 也能乾淨關閉。
rem 若日後修改了 backend 程式碼，請關閉本視窗(Ctrl+C)後重新執行本檔即可。
call "%CD%\.venv\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000
