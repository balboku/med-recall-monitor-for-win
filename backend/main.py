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

@app.post("/api/crawl/{crawler_name}")
async def trigger_crawl(crawler_name: str, payload: Optional[CrawlRequest] = None):
    historical = payload.historical if payload else False
    product_ids = payload.product_ids if payload else None

    valid_crawlers = ["fda_recall", "fda_maude", "tfda", "standards", "all"]
    if crawler_name not in valid_crawlers:
        raise HTTPException(status_code=404, detail=f"Unknown crawler: {crawler_name}")

    if crawler_name == "all":
        mode = None
        for name in ["fda_recall", "fda_maude", "tfda", "standards"]:
            mode = enqueue_crawler(name, historical, product_ids)
            logger.info(
                "Triggered crawler=%s historical=%s product_ids=%s via %s",
                name,
                historical,
                product_ids,
                mode,
            )
        return {
            "message": "All crawlers have been queued.",
            "historical": historical,
            "product_ids": product_ids,
            "dispatch_mode": mode,
        }

    mode = enqueue_crawler(crawler_name, historical, product_ids)
    logger.info(
        "Triggered crawler=%s historical=%s product_ids=%s via %s",
        crawler_name,
        historical,
        product_ids,
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
