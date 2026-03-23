@echo off
:: 使用 UTF-8 編碼以顯示中文
chcp 65001 >nul
SETLOCAL EnableDelayedExpansion

echo --------------------------------------------------------
echo 🚀 正在準備啟動 Med-Recall-Monitor 醫療器材監控系統 (Windows)...
echo --------------------------------------------------------

:: 檢查 docker 是否安裝
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [錯誤] 找不到 docker！請確保已安裝 Docker Desktop 並在運行中。
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
        echo [錯誤] 找不到 "docker compose" 或 "docker-compose"！
        echo 請確認 Docker Desktop 已正確安裝並啟動。
        pause
        exit /b 1
    )
)

:: 額外檢查 Docker 守護進程 (daemon) 是否正在運行
!DOCKER_CMD! ps >nul 2>&1
if %errorlevel% neq 0 (
    echo [警告] Docker 服務可能尚未完全啟動 (Docker Desktop is unable to start)。
    echo 請確認 Docker Desktop 圖示已變為綠色 (Running)，然後再點擊重試。
    pause
    exit /b 1
)

echo --------------------------------------------------------
echo 🚀 正在執行指令: !DOCKER_CMD!
echo --------------------------------------------------------

:: 1. 停止並移除現有容器
echo Step 1/3: 正在停止現行服務...
!DOCKER_CMD! down

:: 2. 重新編譯並啟動所有服務 (背景執行)
echo Step 2/3: 正在重新編譯並啟動容器 (背景模式)...
!DOCKER_CMD! up -d --build
if %errorlevel% neq 0 (
    echo [錯誤] 啟動容器失敗。請檢查 Docker 狀態或網路連線。
    pause
    exit /b 1
)

:: 3. 檢查服務狀態
echo Step 3/3: 正在驗證服務狀態...
timeout /t 5 /nobreak > nul
echo --------------------------------------------------------
echo ✅ 系統啟動成功！已啟用熱重載 (Hot-Reload) 模式。
echo --------------------------------------------------------

!DOCKER_CMD! ps

echo.
echo 💡 提示：
echo    - 前端 (React): http://localhost:5173
echo    - 後端 (FastAPI): http://localhost:8000
echo    - 查看日誌: !DOCKER_CMD! logs -f
echo --------------------------------------------------------

pause
