import logging
import os
import platform
from contextlib import asynccontextmanager
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version as package_version

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List

from config import (
    CRAWL_INTERVAL_FDA_MAUDE,
    CRAWL_INTERVAL_FDA_RECALL,
    CRAWL_INTERVAL_STANDARDS,
    CRAWL_INTERVAL_TFDA,
)
from crawlers.standards import StandardsCrawler
from database import init_db, migrate_db
from product_manager import sync_to_db
from env_loader import load_environment
from routes import analytics, dashboard, events, products, recalls, reports, standards
from scheduler import init_scheduler, shutdown_scheduler
from task_queue import enqueue_crawler, get_task_queue_mode, shutdown_task_queue


load_environment()

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
    logger.info("Starting Med Recall Monitor API")
    init_db()
    migrate_db()

    # Sync products from JSON to Database to satisfy existing relational constraints
    sync_to_db()

    StandardsCrawler().init_default_standards()
    init_scheduler()

    yield

    shutdown_scheduler()
    shutdown_task_queue()
    logger.info("Stopped Med Recall Monitor API")


app = FastAPI(
    title="Med Recall Monitor API",
    description="Local-first backend for recall monitoring, alerts, analytics, and AI reports.",
    version="2.0.0",
    lifespan=lifespan,
)

try:
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator().instrument(app).expose(app)
except ImportError:
    logger.warning("prometheus_fastapi_instrumentator is not installed; /metrics is disabled")

_allowed_origins_env = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
)
ALLOWED_ORIGINS = [origin.strip() for origin in _allowed_origins_env.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Operator"],
)

app.include_router(products.router)
app.include_router(recalls.router)
app.include_router(events.router)
app.include_router(standards.router)
app.include_router(dashboard.router)
app.include_router(reports.router)
app.include_router(analytics.router)


@app.get("/")
def root():
    return {
        "message": "Med Recall Monitor API",
        "version": app.version,
        "features": [
            "Audit Trail",
            "Report Signing",
            "Crawler Failure Alerts",
            "CAPA Integration",
            "Local Task Queue",
        ],
    }


@app.get("/api/health")
def health_check():
    from database import get_db

    conn = get_db()
    try:
        crawlers = ["fda_recall", "fda_maude", "tfda", "standards"]
        crawler_health = {}

        for name in crawlers:
            row = conn.execute(
                """
                SELECT status, completed_at, records_found, new_records, error_message
                FROM crawl_logs
                WHERE crawler_name = ?
                ORDER BY completed_at DESC LIMIT 1
                """,
                (name,),
            ).fetchone()

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

        failure_alerts = conn.execute(
            """
            SELECT COUNT(*) as cnt FROM alerts
            WHERE alert_type='crawler_failure' AND is_read=0
            """
        ).fetchone()["cnt"]

        total_recalls = conn.execute("SELECT COUNT(*) as cnt FROM recalls").fetchone()["cnt"]
        total_events = conn.execute("SELECT COUNT(*) as cnt FROM adverse_events").fetchone()["cnt"]

        return {
            "status": "ok",
            "timestamp": datetime.now().isoformat(),
            "version": app.version,
            "task_queue_mode": get_task_queue_mode(),
            "crawlers": crawler_health,
            "unread_failure_alerts": failure_alerts,
            "data_summary": {
                "total_recalls": total_recalls,
                "total_adverse_events": total_events,
            },
        }
    finally:
        conn.close()


@app.get("/api/system-info")
def get_system_info():
    from database import DATABASE_URL as active_database_url

    return {
        "api_version": app.version,
        "database_backend": "postgresql" if active_database_url else "sqlite",
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
            "task_queue_mode": get_task_queue_mode(),
        },
    }


class CrawlRequest(BaseModel):
    historical: bool = False
    product_ids: Optional[List[int]] = None
    standard_id: Optional[int] = None

@app.post("/api/crawl/{crawler_name}")
async def trigger_crawl(crawler_name: str, payload: Optional[CrawlRequest] = None):
    historical = payload.historical if payload else False
    product_ids = payload.product_ids if payload else None
    standard_id = payload.standard_id if payload else None

    valid_crawlers = ["fda_recall", "fda_maude", "tfda", "standards", "all"]
    if crawler_name not in valid_crawlers:
        raise HTTPException(status_code=404, detail=f"Unknown crawler: {crawler_name}")

    if crawler_name == "all":
        mode = None
        for name in ["fda_recall", "fda_maude", "tfda", "standards"]:
            mode = enqueue_crawler(name, historical, product_ids, standard_id)
            logger.info(
                "Triggered crawler=%s historical=%s product_ids=%s standard_id=%s via %s",
                name,
                historical,
                product_ids,
                standard_id,
                mode,
            )
        return {
            "message": "All crawlers have been queued.",
            "historical": historical,
            "product_ids": product_ids,
            "dispatch_mode": mode,
        }

    mode = enqueue_crawler(crawler_name, historical, product_ids, standard_id)
    logger.info(
        "Triggered crawler=%s historical=%s product_ids=%s standard_id=%s via %s",
        crawler_name,
        historical,
        product_ids,
        standard_id,
        mode,
    )
    return {
        "message": f"Crawler {crawler_name} has been queued.",
        "historical": historical,
        "product_ids": product_ids,
        "dispatch_mode": mode,
    }


@app.get("/api/crawl/logs")
def get_crawl_logs():
    from database import get_db

    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM crawl_logs ORDER BY COALESCE(completed_at, started_at) DESC LIMIT 50"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

class TranslateRequest(BaseModel):
    text: str
    target_lang: str = "zh-TW"

@app.post("/api/translate")
def translate_text(payload: TranslateRequest):
    from deep_translator import GoogleTranslator
    try:
        if not payload.text or not payload.text.strip():
            return {"translatedText": ""}
            
        translated = GoogleTranslator(source='auto', target=payload.target_lang).translate(payload.text)
        return {"translatedText": translated}
    except Exception as e:
        logger.error(f"Translation failed: {e}")
        return {"translatedText": payload.text}  # 退回原文


@app.get("/api/announcement")
def get_announcement():
    from database import get_db
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT value FROM system_settings WHERE key = 'announcement'"
        ).fetchone()
        return {"content": row["value"] if row else ""}
    finally:
        conn.close()


class AnnouncementRequest(BaseModel):
    content: str

@app.put("/api/announcement")
def save_announcement(payload: AnnouncementRequest):
    from database import get_db
    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO system_settings (key, value, updated_at)
            VALUES ('announcement', ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (payload.content,)
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.get("/api/settings/gemini-api-key")
def get_gemini_api_key():
    from database import get_db
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT value FROM system_settings WHERE key = 'gemini_api_key'"
        ).fetchone()
        value = row["value"] if row else ""
        masked = ""
        if value:
            masked = ("*" * max(len(value) - 4, 0)) + value[-4:]
        return {"has_key": bool(value), "masked": masked}
    finally:
        conn.close()


class GeminiApiKeyRequest(BaseModel):
    api_key: str

@app.put("/api/settings/gemini-api-key")
def save_gemini_api_key(payload: GeminiApiKeyRequest):
    from database import get_db
    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO system_settings (key, value, updated_at)
            VALUES ('gemini_api_key', ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (payload.api_key.strip(),)
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.get("/api/settings/google-search-config")
def get_google_search_config():
    from database import get_db
    conn = get_db()
    try:
        api_key_row = conn.execute(
            "SELECT value FROM system_settings WHERE key = 'google_search_api_key'"
        ).fetchone()
        cx_row = conn.execute(
            "SELECT value FROM system_settings WHERE key = 'google_search_cx'"
        ).fetchone()
        api_key = api_key_row["value"] if api_key_row else ""
        cx = cx_row["value"] if cx_row else ""
        masked = ""
        if api_key:
            masked = ("*" * max(len(api_key) - 4, 0)) + api_key[-4:]
        return {"has_key": bool(api_key), "masked": masked, "cx": cx}
    finally:
        conn.close()


class GoogleSearchConfigRequest(BaseModel):
    api_key: Optional[str] = None
    cx: Optional[str] = None

@app.put("/api/settings/google-search-config")
def save_google_search_config(payload: GoogleSearchConfigRequest):
    from database import get_db
    conn = get_db()
    try:
        if payload.api_key is not None and payload.api_key.strip():
            conn.execute(
                """
                INSERT INTO system_settings (key, value, updated_at)
                VALUES ('google_search_api_key', ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (payload.api_key.strip(),)
            )
        if payload.cx is not None and payload.cx.strip():
            conn.execute(
                """
                INSERT INTO system_settings (key, value, updated_at)
                VALUES ('google_search_cx', ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (payload.cx.strip(),)
            )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()
