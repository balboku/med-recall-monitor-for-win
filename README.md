# MedWatch (醫療器材召回監控系統)

這是一個專為醫療器材品保工程師開發的監控系統，旨在追蹤 FDA 召回記錄、FDA MAUDE 不良事件、TFDA 警訊以及國際標準 (IEC/ISO) 的最新版本。

## 🚀 核心功能
- **全自動爬蟲引擎**: 定時抓取 OpenFDA、TFDA 及法規標準網站數據。
- **AI 智能分析報告**: 整合指定效期內的歷史紀錄並透過 Google Gemini 產出專家評估報告。
- **單筆紀錄 AI 點評**: 深入解析每一則召回或不良事件，並自動持久化儲存分析結果。
- **大數據回補工具**: 提供專屬腳本突破 OpenFDA 單次分頁 25,000 筆之限制，支援數萬筆歷史資料同步。
- **現代化介面**: 採用深色模式、Glassmorphism 設計，具備提醒通知與產品管理功能。

## 🛠️ 技術棧
- **Frontend**: React, Vite, CSS Vanilla (Modern Glassmorphism)
- **Backend**: FastAPI, SQLite, APScheduler
- **AI**: Google Gemini API (支援多組金鑰輪調)

## 📦 安裝與啟動

### 1. 後端設定 (Backend)
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# 設定 .env 中的 GEMINI_API_KEY_1, GEMINI_API_KEY_2, GEMINI_API_KEY_3
uvicorn main:app --reload
```

### 2. 前端設定 (Frontend)
```bash
cd frontend
npm install
npm run dev
```

### 3. 抓取歷史大數據 (例如 LFL 產品碼)
若需要抓取超過 25,000 筆的 MAUDE 歷史紀錄，請運行：
```bash
python3 backend/scripts/fetch_historical_maude.py
```

## 📝 開發配置 (VS Code)
本專案已配置 `.vscode/settings.json` 以正確解析後端路徑，解決 Pyre/Pylance 的型別警告。若開啟專案仍有紅線，請重啟 VS Code 視窗。

## 🔗 聯絡與貢獻
- **Repos**: [balboku/med-recall-monitor](https://github.com/balboku/med-recall-monitor.git)
