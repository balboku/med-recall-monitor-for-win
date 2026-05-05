@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

set "ROOT_DIR=%~dp0"
if "%ROOT_DIR:~-1%"=="\" set "ROOT_DIR=%ROOT_DIR:~0,-1%"
set "BACKEND_DIR=%ROOT_DIR%\backend"
set "FRONTEND_DIR=%ROOT_DIR%\frontend"
set "VENV_DIR=%BACKEND_DIR%\.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "PYTHON_BOOTSTRAP="
set "NODE_DIR="
set "DEPS_MARKER=%VENV_DIR%\\.deps_installed"

where python >nul 2>&1
if %errorlevel% equ 0 set "PYTHON_BOOTSTRAP=python"

if not defined PYTHON_BOOTSTRAP (
    where py >nul 2>&1
    if %errorlevel% equ 0 set "PYTHON_BOOTSTRAP=py -3.11"
)

if not defined PYTHON_BOOTSTRAP (
    where py >nul 2>&1
    if %errorlevel% equ 0 set "PYTHON_BOOTSTRAP=py -3"
)

if not defined PYTHON_BOOTSTRAP (
    echo [ERROR] Python was not found. Install Python 3.10+ first.
    pause
    exit /b 1
)

where npm >nul 2>&1
if %errorlevel% neq 0 (
    if exist "C:\Program Files\nodejs\npm.cmd" set "NODE_DIR=C:\Program Files\nodejs"
)

if not defined NODE_DIR (
    if not exist "C:\Program Files\nodejs\npm.cmd" (
        echo [ERROR] npm was not found. Install Node.js 20+ first.
        pause
        exit /b 1
    )
)

if defined NODE_DIR (
    set "PATH=%NODE_DIR%;%PATH%"
)

echo --------------------------------------------------------
echo Starting Med Recall Monitor in local mode...
echo --------------------------------------------------------

call "%ROOT_DIR%\stop_local_services.bat"

if exist "%PYTHON_EXE%" (
    call "%PYTHON_EXE%" -c "import sys, sysconfig; soabi = sysconfig.get_config_var('SOABI') or ''; raise SystemExit(0 if sys.version_info[:2] <= (3, 15) and 't' not in soabi else 1)" >nul 2>&1
    if errorlevel 1 (
        echo [INFO] Existing backend virtual environment uses an incompatible Python build.
        echo [INFO] Recreating %VENV_DIR% with %PYTHON_BOOTSTRAP% ...
        rmdir /s /q "%VENV_DIR%"
    )
)

if not exist "%PYTHON_EXE%" (
    echo [1/4] Creating backend virtual environment...
    call %PYTHON_BOOTSTRAP% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create backend virtual environment.
        pause
        exit /b 1
    )
)

if exist "%DEPS_MARKER%" (
    echo [2/4] Backend dependencies already present.
) else (
    echo [2/4] Installing backend dependencies...
    call "%PYTHON_EXE%" -m pip install -r "%BACKEND_DIR%\requirements-local.txt"
    if errorlevel 1 (
        echo [ERROR] Failed to install backend dependencies.
        pause
        exit /b 1
    )
    type nul > "%DEPS_MARKER%"
)

if not exist "%BACKEND_DIR%\.env" (
    echo [INFO] backend\.env was not found. Copy backend\.env.example if you need AI keys.
)

if not exist "%FRONTEND_DIR%\node_modules" (
    echo [3/4] Installing frontend dependencies...
    pushd "%FRONTEND_DIR%"
    call npm install
    set "NPM_EXIT=!errorlevel!"
    popd
    if not "!NPM_EXIT!"=="0" (
        echo [ERROR] Failed to install frontend dependencies.
        pause
        exit /b 1
    )
) else (
    echo [3/4] Frontend dependencies already present.
)

echo [4/4] Launching backend and frontend into the background...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%ROOT_DIR%\start_backend_local.bat' -WindowStyle Hidden"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%ROOT_DIR%\start_frontend_local.bat' -WindowStyle Hidden"

echo.
echo [INFO] Waiting for local services to become ready...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference = 'SilentlyContinue'; $backendReady = $false; $frontendReady = $false; for ($i = 0; $i -lt 60; $i++) { if (-not $backendReady) { try { $resp = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8000/api/health' -TimeoutSec 2; if ($resp.StatusCode -eq 200) { $backendReady = $true } } catch {} } if (-not $frontendReady) { try { $resp = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:5173' -TimeoutSec 2; if ($resp.StatusCode -eq 200) { $frontendReady = $true } } catch {} } if ($backendReady -and $frontendReady) { exit 0 } Start-Sleep -Seconds 1 }; exit 1"
if errorlevel 1 (
    echo [WARNING] Services were launched, but they did not both report ready within 60 seconds.
    echo [WARNING] Check the backend and frontend windows for error details.
) else (
    start "" "http://localhost:5173"
    echo [OK] Local services are ready.
)
echo Frontend: http://localhost:5173
echo Backend : http://localhost:8000
echo Swagger : http://localhost:8000/docs
echo.
echo Docker mode is still available via restart_system_docker.bat
echo --------------------------------------------------------

echo Press any key to close this launcher window. The app will keep running.
pause >nul
