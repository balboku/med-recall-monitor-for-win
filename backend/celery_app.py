import os
import asyncio
import logging
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "medwatch_tasks",
    broker=REDIS_URL,
    backend=REDIS_URL
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Taipei",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
)

logger = logging.getLogger(__name__)

def _create_failure_alert(crawler_name: str, error: str):
    """P2-1: 爬蟲失敗時在 alerts 表寫入高嚴重性系統告警"""
    from database import get_db
    conn = get_db()
    try:
        existing = conn.execute("""
            SELECT id FROM alerts
            WHERE alert_type='crawler_failure' AND source=%s
              AND created_at >= NOW() - INTERVAL '1 hour'
        """, (crawler_name,)).fetchone()

        if not existing:
            conn.execute("""
                INSERT INTO alerts (alert_type, title, message, source, severity)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                "crawler_failure",
                f"⚠️ 爬蟲失敗告警: {crawler_name}",
                f"爬蟲 {crawler_name} 執行失敗，請確認資料可能已停止更新。錯誤: {str(error)[:200]}",
                crawler_name,
                "high",
            ))
            conn.commit()
            logger.warning(f"P2-1 告警已寫入: {crawler_name} 爬蟲失敗")
    except Exception as e:
        logger.error(f"寫入失敗告警時發生錯誤: {e}")
    finally:
        conn.close()


@celery_app.task
def run_crawler_task(crawler_name: str, historical: bool = False):
    from crawlers.fda_recall import FDARecallCrawler
    from crawlers.fda_maude import FDAMaudeCrawler
    from crawlers.tfda import TFDACrawler
    from crawlers.standards import StandardsCrawler

    crawlers_map = {
        "fda_recall": FDARecallCrawler,
        "fda_maude": FDAMaudeCrawler,
        "tfda": TFDACrawler,
        "standards": StandardsCrawler,
    }

    if crawler_name not in crawlers_map:
        return f"Unknown crawler: {crawler_name}"

    cls = crawlers_map[crawler_name]

    async def _run():
        try:
            logger.info(f"開始執行 Celery 爬蟲任務: {crawler_name} (historical={historical})")
            crawler = cls()
            await crawler.run(historical=historical)
            await crawler.close()
            logger.info(f"Celery 爬蟲任務完成: {crawler_name}")
        except Exception as e:
            logger.error(f"Celery 爬蟲任務失敗: {crawler_name}, 錯誤: {e}")
            _create_failure_alert(crawler_name, str(e))

    asyncio.run(_run())
    return f"Crawler {crawler_name} finished."
