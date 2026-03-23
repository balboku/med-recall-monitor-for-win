@echo off
SETLOCAL EnableDelayedExpansion

:: 檢查 docker 是否安裝
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] 找不到 docker! 請確保已安裝 Docker Desktop 並在運行中。
    echo 官方下載網址: https://www.docker.com/products/docker-desktop/
    pause
    exit /b 1
)

:: 建立檢測機制，優先使用 docker compose (V2)
set "DOCKER_CMD=docker compose"
docker compose version >nul 2>&1
if %errorlevel% neq 0 (
    set "DOCKER_CMD=docker-compose"
    docker-compose version >nul 2>&1
    if %errorlevel% neq 0 (
        echo [ERROR] 找不到 "docker compose" 或 "docker-compose"!
        echo 請確認 Docker Desktop 已正確安裝並啟動。
        pause
        exit /b 1
    )
)

echo --------------------------------------------------------
echo 🚀 正在使用 !DOCKER_CMD! 重新啟動 Med-Recall-Monitor 醫療器材監控系統 (Windows)...
echo --------------------------------------------------------

:: 1. 停止並移除現有容器
echo Step 1/3: 正在停止現行服務...
!DOCKER_CMD! down

:: 2. 重新編譯並啟動所有服務 (背景執行)
echo Step 2/3: 正在重新編譯並啟動容器 (背景模式)...
!DOCKER_CMD! up -d --build

:: 3. 檢查服務狀態
echo Step 3/3: 正在驗證服務狀態...
timeout /t 5 /nobreak > nul
echo --------------------------------------------------------
echo ✅ 系統啟動成功！已啟用「熱重載 (Hot-Reload)」模式。
echo --------------------------------------------------------

!DOCKER_CMD! ps

echo.
echo 💡 提示：
echo    - 前端 (React): http://localhost:5173
echo    - 後端 (FastAPI): http://localhost:8000
echo    - 🔥 自動更新: 代碼修改後，容器會自動感應並重新載入，無須重複執行此腳本。
echo    - 查看日誌: !DOCKER_CMD! logs -f
echo --------------------------------------------------------

pause
