import os
import logging
import threading
import platform
from contextlib import asynccontextmanager
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version as package_version
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from database import init_db, migrate_db
from scheduler import init_scheduler, shutdown_scheduler
from config import (
    CRAWL_INTERVAL_FDA_RECALL,
    CRAWL_INTERVAL_FDA_MAUDE,
    CRAWL_INTERVAL_TFDA,
    CRAWL_INTERVAL_STANDARDS,
)
from crawlers.standards import StandardsCrawler
from crawlers.fda_recall import FDARecallCrawler
from crawlers.fda_maude import FDAMaudeCrawler
from crawlers.tfda import TFDACrawler
from routes import products, recalls, events, standards, dashboard, reports, analytics
from typing import Dict, Type, Any


# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _safe_package_version(name: str) -> str:
    try:
        return package_version(name)
    except PackageNotFoundError:
        return "unknown"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用程式生命週期管理"""
    # 啟動
    logger.info("🚀 啟動醫療器材監控系統 v2（品保強化版）")
    init_db()
    migrate_db()  # P1-2: 對既有 DB 補充 Audit Trail 欄位

    # 初始化預設標準
    std_crawler = StandardsCrawler()
    std_crawler.init_default_standards()

    # 啟動排程器
    init_scheduler()

    yield

    # 關閉
    shutdown_scheduler()
    logger.info("🛑 系統已關閉")


app = FastAPI(
    title="醫療器材召回與法規監控系統",
    description="監控拋棄式無線超音波刀相關召回記錄、不良事件及法規標準（v2: ISO 13485 Audit Trail 強化版）",
    version="2.0.0",
    lifespan=lifespan,
)

# 加入 Prometheus 監控指標 Endpoint
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator().instrument(app).expose(app)
except ImportError:
    logger.warning("prometheus_fastapi_instrumentator 未安裝，忽略指標暴露")

# P2-3: CORS 改用環境變數白名單，不使用 allow_origins=["*"]
_allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:4173")
ALLOWED_ORIGINS = [o.strip() for o in _allowed_origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Operator"],
)

# 掛載路由
app.include_router(products.router)
app.include_router(recalls.router)
app.include_router(events.router)
app.include_router(standards.router)
app.include_router(dashboard.router)
app.include_router(reports.router)
app.include_router(analytics.router)  # P3-2: 趨勢分析、競品分析、MRM 月報


@app.get("/")
def root():
    return {
        "message": "醫療器材召回與法規監控系統 API",
        "version": "2.0.0",
        "features": ["Audit Trail", "Report Signing", "Crawler Failure Alerts", "CAPA Integration"]
    }


# P2-2: 健康監控端點 — 資料新鮮度狀態
@app.get("/api/health")
def health_check():
    """系統健康狀態：各爬蟲最後成功時間、資料新鮮度、失敗告警數"""
    from database import get_db
    conn = get_db()
    try:
        crawlers = ["fda_recall", "fda_maude", "tfda", "standards"]
        crawler_health = {}

        for name in crawlers:
            row = conn.execute("""
                SELECT status, completed_at, records_found, new_records, error_message
                FROM crawl_logs
                WHERE crawler_name = ?
                ORDER BY completed_at DESC LIMIT 1
            """, (name,)).fetchone()

            if row:
                crawler_health[name] = {
                    "last_status": row["status"],
                    "last_run": row["completed_at"],
                    "records_found": row["records_found"],
                    "new_records": row["new_records"],
                    "error": row["error_message"],
                }
            else:
                crawler_health[name] = {"last_status": "never_run", "last_run": None}

        # 統計失敗告警數
        failure_alerts = conn.execute("""
            SELECT COUNT(*) as cnt FROM alerts
            WHERE alert_type='crawler_failure' AND is_read=0
        """).fetchone()["cnt"]

        # 資料庫基本統計
        total_recalls = conn.execute("SELECT COUNT(*) as cnt FROM recalls").fetchone()["cnt"]
        total_events = conn.execute("SELECT COUNT(*) as cnt FROM adverse_events").fetchone()["cnt"]

        return {
            "status": "ok",
            "timestamp": datetime.now().isoformat(),
            "version": "2.0.0",
            "crawlers": crawler_health,
            "unread_failure_alerts": failure_alerts,
            "data_summary": {
                "total_recalls": total_recalls,
                "total_adverse_events": total_events,
            }
        }
    finally:
        conn.close()


@app.get("/api/system-info")
def get_system_info():
    from database import DATABASE_URL as ACTIVE_DATABASE_URL
    return {
        "api_version": app.version,
        "database_backend": "postgresql" if ACTIVE_DATABASE_URL else "sqlite",
        "scheduler": {
            "mode": "interval",
            "crawlers": {
                "fda_recall": {"interval_hours": CRAWL_INTERVAL_FDA_RECALL},
                "fda_maude": {"interval_hours": CRAWL_INTERVAL_FDA_MAUDE},
                "tfda": {"interval_hours": CRAWL_INTERVAL_TFDA},
                "standards": {"interval_hours": CRAWL_INTERVAL_STANDARDS},
            },
        },
        "stack": {
            "python": platform.python_version(),
            "fastapi": _safe_package_version("fastapi"),
            "celery": _safe_package_version("celery"),
            "redis_client": _safe_package_version("redis"),
            "httpx": _safe_package_version("httpx"),
        },
        "runtime": {
            "allowed_origins": ALLOWED_ORIGINS,
        },
    }


@app.post("/api/crawl/{crawler_name}")
async def trigger_crawl(crawler_name: str, historical: bool = False):
    """手動觸發爬蟲（轉交 Celery 非同步執行），支援 historical=true 抓取大量數據"""
    from celery_app import run_crawler_task
    valid_crawlers = ["fda_recall", "fda_maude", "tfda", "standards", "all"]

    if crawler_name not in valid_crawlers:
        raise HTTPException(status_code=404, detail=f"未知的爬蟲: {crawler_name}")

    if crawler_name == "all":
        for name in ["fda_recall", "fda_maude", "tfda", "standards"]:
            logger.info(f"API: 觸發 Celery 背景爬取任務: {name} (historical={historical})")
            run_crawler_task.delay(name, historical)
        return {"message": "已在背景 Celery 佇列啟動所有爬蟲任務", "historical": historical}
    else:
        logger.info(f"API: 觸發 Celery 背景爬取任務: {crawler_name} (historical={historical})")
        run_crawler_task.delay(crawler_name, historical)
        return {"message": f"已在背景 Celery 佇列啟動 {crawler_name} 爬蟲任務", "historical": historical}


@app.get("/api/crawl/logs")
def get_crawl_logs():
    """取得爬蟲執行記錄"""
    from database import get_db
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM crawl_logs ORDER BY COALESCE(completed_at, started_at) DESC LIMIT 50"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
