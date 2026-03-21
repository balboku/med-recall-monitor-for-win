#!/bin/bash

# Med-Recall-Monitor 一鍵啟動與重啟腳本 (雙擊執行版)
# 適用於 Mac 環境

# 切換到腳本所在的目錄 (重要：確保在雙擊執行時能找到 docker-compose.yml)
cd "$(dirname "$0")"

set -e

echo "--------------------------------------------------------"
echo "🚀 正在重新啟動 Med-Recall-Monitor 醫療器材監控系統..."
echo "--------------------------------------------------------"

# 1. 停止並移除現有容器
echo "Step 1/3: 正在停止現行服務..."
docker-compose down

# 2. 重新編譯並啟動所有服務 (背景執行)
echo "Step 2/3: 正在重新編譯並啟動容器 (背景模式)..."
docker-compose up -d --build

# 3. 檢查服務狀態
echo "Step 3/3: 正在驗證服務狀態..."
sleep 5
echo "--------------------------------------------------------"
echo "✅ 系統啟動成功！已啟用「熱重載 (Hot-Reload)」模式。"
echo "--------------------------------------------------------"

docker-compose ps

echo ""
echo "💡 提示："
echo "   - 前端 (React): http://localhost:5173"
echo "   - 後端 (FastAPI): http://localhost:8000"
echo "   - 🔥 自動更新: 代碼修改後，容器會自動感應並重新載入，無須重複執行此腳本。"
echo "   - 查看日誌: docker-compose logs -f"
echo "--------------------------------------------------------"

echo "腳本執行完畢，按任意鍵關閉此視窗..."
read -n 1 -s
