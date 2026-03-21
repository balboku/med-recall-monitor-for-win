# MedWatch (醫療器材召回與進階監控系統 v2)

這是一個專為醫療器材品保工程師開發的高性能監控與分析系統。v2 版本已完成全面架構優化，包含資料庫遷移、背景任務解耦與前端效能翻新。

## 🚀 核心功能與優化 (v2)
- **架構解耦 (Scalable Architecture)**: 導入 **PostgreSQL** 與 **Celery + Redis** 異步架構，確保高併發爬蟲與大數據分析不阻塞主服務。
- **全自動爬蟲引擎**: 定時抓取 OpenFDA、TFDA 及國際標準網站數據。
- **React Query 效能翻新**: 前端全面採用 **React Query (@tanstack/react-query)**，提供智慧快取、背景重整與極速的分頁搜尋體驗。
- **AI 專家分析 (Exponential Backoff)**: 透過 Google Gemini 產出專家評估報告，並具備帶有 Jitter 的指數退避機制，能應對 API 配額限制與自動輪調金鑰。
- **Prometheus 監控**: 整合 Prometheus 效能指標監控，隨時掌握系統 API 延遲與錯誤率。
- **容器化部署**: 支援 **Docker Compose** 一鍵部署完整的全疊加 (Full-stack) 服務。

## 🛠️ 技術棧
- **Frontend**: React, Vite, React Query, CSS Vanilla (Modern Glassmorphism)
- **Backend**: FastAPI, PostgreSQL, Celery, Redis
- **Monitoring**: Prometheus
- **AI**: Google Gemini API (支援多組金鑰輪調與退避重試機)

## 📦 快速啟動 (Docker 推薦)

這是最簡單且推薦的啟動方式：

```bash
# 1. 複製專案
git clone https://github.com/balboku/med-recall-monitor.git
cd med-recall-monitor

# 2. 設定環境變數
# 在 backend/ 建立 .env 並填入 GEMINI_API_KEY_1~3

# 3. 一鍵啟動
docker-compose up -d --build
```

### 服務路徑：
- **前端面板**: [http://localhost](http://localhost)
- **API 服務**: [http://localhost:8000](http://localhost:8000)
- **監控指標 (Prometheus)**: [http://localhost:9090](http://localhost:9090)

## 📝 開發配置
若需要手動開發環境：
- **Backend**: `pip install -r backend/requirements.txt`
- **Frontend**: `npm install && npm run dev`

## 🔗 聯絡與貢獻
- **Repos**: [balboku/med-recall-monitor](https://github.com/balboku/med-recall-monitor.git)
