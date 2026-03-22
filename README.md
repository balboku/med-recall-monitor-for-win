# Med-Recall-Monitor

醫療器材監控與 AI 分析系統，整合 FDA Recall、FDA MAUDE、TFDA 安全警訊與標準版本追蹤，提供儀表板、告警、歷史查詢與 AI 報告生成功能。

## 專案目標

這套系統的核心目的不是單純「爬資料」，而是把監控流程拆成 4 個連續階段：

1. 定義監控產品
2. 定時抓取外部監管資料
3. 寫入本地資料庫並產生告警
4. 由前端查詢資料，或交給 AI 生成深度分析報告

## 系統執行邏輯

### 1. 啟動階段

當 `backend/main.py` 啟動 FastAPI 時，會依序做這幾件事：

1. 初始化資料庫與補 migration
2. 建立預設的標準追蹤清單
3. 啟動 APScheduler
4. 掛載各 API 路由

這代表 API server 本身除了提供 REST API，也會負責排程發送背景任務。

### 2. 排程與背景任務

系統採用兩層背景機制：

- `APScheduler`
  - 跑在 FastAPI process 內
  - 只負責「定時觸發」
- `Celery + Redis`
  - 真正執行爬蟲與報告生成
  - 避免 API 被長時間工作阻塞

目前預設排程如下：

- FDA Recall：每 24 小時
- FDA MAUDE：每 24 小時
- TFDA：每 24 小時
- Standards：每 168 小時

可用環境變數覆蓋：

- `CRAWL_INTERVAL_FDA_RECALL`
- `CRAWL_INTERVAL_FDA_MAUDE`
- `CRAWL_INTERVAL_TFDA`
- `CRAWL_INTERVAL_STANDARDS`

### 3. 爬蟲資料流

#### FDA Recall

- 讀取 `products` 表中 `is_active = 1` 的產品
- 以 `fda_product_codes` 與 `keywords` 組成 openFDA 查詢
- 抓取召回資料後寫入 `recalls`
- 若是新資料，新增 `alerts`
- 執行結果寫入 `crawl_logs`

#### FDA MAUDE

- 同樣以啟用中的產品為來源
- 以 product code 與關鍵字組成事件搜尋條件
- 將不良事件寫入 `adverse_events`
- 若是新資料，新增 `alerts`
- 執行結果寫入 `crawl_logs`

#### TFDA

- 讀取 TFDA 安全警訊頁面
- 以產品關鍵字比對標題
- 命中的項目以召回形式寫入 `recalls`
- 新資料建立 `alerts`

#### Standards

- 追蹤 `standards` 表中的標準網址
- 解析 IEC / ISO 頁面版本資訊
- 若版本更新或進入修訂狀態，更新 `standards.has_update`
- 同步建立 `alerts`

### 4. 前端使用邏輯

前端頁面對應的主要工作如下：

- `Dashboard`
  - 顯示 KPI、趨勢、最新爬蟲記錄、未讀告警
- `Products`
  - 建立監控產品
  - 設定關鍵字與 FDA product code
  - 啟用或停用監控
- `Recalls`
  - 查詢召回資料
- `Events`
  - 查詢不良事件資料
- `Standards`
  - 管理追蹤中的法規標準
- `Reports`
  - 針對選定產品與日期區間產生 AI 報告
- `Settings`
  - 系統設定頁面

### 5. AI 報告生成流程

從前端按下「生成深度報告」後，系統流程如下：

1. `POST /api/reports/generate/{product_id}` 建立一筆 `reports` 紀錄，狀態先設為 `generating`
2. API 觸發 `generate_report_task` Celery 任務
3. 背景任務先補抓該產品在指定日期區間的 FDA Recall / MAUDE 歷史資料
4. 從資料庫撈出該區間的召回與事件
5. 統計品牌分布、失效模式、死亡/傷害/故障數量
6. 呼叫 Gemini 生成批次摘要與最終 HTML 報告
7. 回寫 `reports.report_html`、`stats_json`、`total_records_analyzed`
8. 完成後把狀態改回 `draft`，等待人工審核或下載

## 主要資料表

實務上最重要的是以下幾張表：

- `products`
  - 監控對象定義
- `recalls`
  - FDA / TFDA 召回與警訊
- `adverse_events`
  - FDA MAUDE 不良事件
- `standards`
  - 標準追蹤清單與版本狀態
- `alerts`
  - 系統告警與未讀提醒
- `reports`
  - AI 報告與簽核狀態
- `crawl_logs`
  - 每次爬蟲執行結果
- `audit_log`
  - 稽核軌跡

## 技術架構

| 元件 | 技術 |
| --- | --- |
| Backend API | FastAPI |
| Scheduler | APScheduler |
| Async Worker | Celery |
| Queue / Broker | Redis |
| Frontend | React + Vite |
| Database | SQLite 或 PostgreSQL |
| AI | Google Gemini |
| Monitoring | Prometheus |

## 實際部署與啟動方式

### Docker Compose 服務

`docker-compose.yml` 目前會啟動：

- `postgres`
- `redis`
- `backend`
- `celery_worker`
- `frontend`
- `prometheus`

### 環境變數

目前 Compose 設定是從 `backend/.env` 載入，不是根目錄 `.env`。

最少請準備：

```env
GEMINI_API_KEY_1=your_key
FDA_API_KEY=optional
DATABASE_URL=postgresql://medwatch_user:medwatch_password@postgres:5432/medwatch
REDIS_URL=redis://redis:6379/0
ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

補充說明：

- 若 `DATABASE_URL` 沒有設定，後端會退回使用 `backend/data/monitor.db` 的 SQLite
- `backend/config.py` 內的 `DATABASE_URL` 常數只是預設字串，真正連線是否使用 PostgreSQL，是由 `backend/database.py` 讀環境變數決定

### 本機啟動

```bash
chmod +x restart_system.command
./restart_system.command
```

啟動後可使用：

- Frontend: `http://localhost:5173`
- Backend API: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`
- Prometheus: `http://localhost:9090`

## 建議使用流程

第一次使用建議照這個順序：

1. 啟動整套系統
2. 到 `Products` 新增監控產品
3. 填入關鍵字與 FDA product code
4. 透過 API 手動觸發一次爬蟲，或等待排程執行
5. 在 `Dashboard / Recalls / Events` 確認資料是否進來
6. 到 `Reports` 對指定產品與日期區間生成 AI 報告

常用 API：

- `GET /api/health`
- `POST /api/crawl/{crawler_name}`
- `GET /api/crawl/logs`
- `GET /api/dashboard`
- `GET /api/reports`

其中 `crawler_name` 可為：

- `fda_recall`
- `fda_maude`
- `tfda`
- `standards`
- `all`
