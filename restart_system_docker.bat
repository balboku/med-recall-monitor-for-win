@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

set "DOCKER_CMD=docker compose"
docker compose version >nul 2>&1
if %errorlevel% neq 0 (
    set "DOCKER_CMD=docker-compose"
    docker-compose version >nul 2>&1
    if %errorlevel% neq 0 (
        echo [ERROR] Docker Compose was not found.
        pause
        exit /b 1
    )
)

echo --------------------------------------------------------
echo Starting Med Recall Monitor with Docker...
echo --------------------------------------------------------

%DOCKER_CMD% down
%DOCKER_CMD% up -d --build

if %errorlevel% neq 0 (
    echo [ERROR] Docker startup failed.
    pause
    exit /b 1
)

%DOCKER_CMD% ps
echo.
echo Frontend: http://localhost:5173
echo Backend : http://localhost:8000
echo Swagger : http://localhost:8000/docs
echo Prometheus: http://localhost:9090
echo --------------------------------------------------------

pause
