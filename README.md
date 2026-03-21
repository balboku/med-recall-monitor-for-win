# 🩺 Med-Recall-Monitor (MedWatch AI)

> **全方位的醫療器材全球監管與 AI 風險分析平台。** 🚀

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tech: FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![Tech: React](https://img.shields.io/badge/Frontend-React-61DAFB.svg)](https://reactjs.org/)
[![AI: Gemini](https://img.shields.io/badge/AI-Gemini%203.1-blue.svg)](https://deepmind.google/technologies/gemini/)

## 📖 專案簡介
**Med-Recall-Monitor** 是一款專為醫療器材從業者（RA/QA）設計的自動化監測與分析工具。它能即時追蹤 FDA（Recall, MAUDE）與 TFDA 的最新公告，並利用 **Gemini 3.1 AI** 進行深度的風險評估與技術失效模式分析，將碎片化的監管數據轉化為具備前瞻性的執行建議。

---

## ✨ 核心特性

- **🌐 全球數據同步**：自動爬取美國 FDA (MAUDE 不良事件 & Recall 召回) 與台灣 TFDA 的基準數據。
- **🤖 AI 深度解析**：內建專業醫材專家 Persona，自動產出符合 ISO 14971 標準的風險矩陣與技術根本原因分析。
- **📊 專業視覺化報表**：自動分類產品、型號與失效模式，並生成具備互動圖表的 HTML 專家報表。
- **📜 標準規章追蹤**：監控國際與國內醫療器材標準的版本變動，並在有更新時主動推送警示。
- **🛡️ 稽核完整性 (Audit Trail)**：系統完整記錄所有報告生成與審核細節，確保符合 GxP 合規性要求。
- **⚡ 開發者友好**：全棧 Docker 化並支援 **Hot-Reload**，代碼變更即時反映。

---

## 🛠️ 技術架構

| 組件 | 技術選擇 | 理由 |
| :--- | :--- | :--- |
| **Backend** | **FastAPI (Python)** | 高性能、自動生成 OpenAPI 文檔，適合數據密集型應用。 |
| **Worker** | **Celery + Redis** | 處理耗時的網路爬蟲與 AI 分析任務，確保前端響應不阻塞。 |
| **Frontend** | **React + Vite** | 極速開發體驗與 HMR，提供專業的醫療級 UI 管理介面。 |
| **Database** | **PostgreSQL** | 強大的關聯性數據處理，支援複雜的監管數據查詢。 |
| **AI Engine** | **Gemini 3.1 Flash Lite** | 具備市場頂尖的長文本處理能力與高達 500 RPD 的配額，適合批量報表生成。 |

---

## 🚀 快速開始

### 環境需求
- Docker & Docker Compose
- Gemini API Key (請至 Google AI Studio 申請)

### 安裝步驟

1. **複製專案**
   ```bash
   git clone https://github.com/your-repo/med-recall-monitor.git
   cd med-recall-monitor
   ```

2. **配置環境變數**
   在根目錄創建 `.env` 文件：
   ```env
   GEMINI_API_KEY_1=your_key_here
   DATABASE_URL=postgresql://user:pass@db:5432/medwatch
   REDIS_URL=redis://redis:6379/0
   ```

3. **啟動系統 (含熱重載)**
   ```bash
   chmod +x restart_system.command
   ./restart_system.command
   ```
   系統啟動後：
   - 前端：`http://localhost:5173`
   - 後端 API：`http://localhost:8000/docs`

---

## 💻 程式碼範例：AI 深度分析 API

這是我們最核心的 AI 分析調用片段，展示了如何將原始監管數據轉化為專家意見：

```python
@router.post("/analyze-record")
def analyze_record(req: AnalyzeRecordRequest):
    # 自動補齊：若前端沒傳 raw_data，系統會根據 ID 從資料庫獲取
    raw_data = req.raw_data or fetch_from_db(req.record_id)
    
    # 調用 Gemini 執行深度分析 (ISO 14971 框架)
    html_insight = ai_service.analyze_single_record(req.record_type, raw_data)
    
    # 持久化分析結果，避免重複消耗 Token
    save_to_db(req.record_id, html_insight)
    
    return {"html": html_insight}
```

---

## 🤝 貢獻指南

我們非常歡迎社群參與！您可以透過以下方式貢獻：
- 提交 Bug Report 或 Feature Request。
- 改善 AI Prompt 以提升報告的專業度。
- 增加新的爬蟲來源（如歐盟 EUDAMED）。

請先閱讀 `CONTRIBUTING.md` (Coming soon) 以了解詳情。

---

## 📄 授權協議

本專案採用 **MIT License** 授權。您可以自由使用、修改與發布，但請保留原作者署名。

---

> **Disclaimer**: 本工具生成的報告僅供參考，所有醫療器材上市後監管決策仍應由具備資格之法規或品質管理人員簽核。
