"""APScheduler 排程器 — 定時執行爬蟲任務（v2: 含失敗自動告警）"""
import logging
import asyncio
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from crawlers.fda_recall import FDARecallCrawler
from crawlers.fda_maude import FDAMaudeCrawler
from crawlers.tfda import TFDACrawler
from crawlers.standards import StandardsCrawler
from config import (
    CRAWL_INTERVAL_FDA_RECALL,
    CRAWL_INTERVAL_FDA_MAUDE,
    CRAWL_INTERVAL_TFDA,
    CRAWL_INTERVAL_STANDARDS,
)

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def _create_failure_alert(crawler_name: str, error: str):
    """P2-1: 爬蟲失敗時在 alerts 表寫入高嚴重性系統告警"""
    from database import get_db
    conn = get_db()
    try:
        # 避免短時間內重複告警（同一爬蟲 1 小時內只新增一次）
        existing = conn.execute("""
            SELECT id FROM alerts
            WHERE alert_type='crawler_failure' AND source=?
              AND created_at >= datetime('now', '-1 hour')
            LIMIT 1
        """, (crawler_name,)).fetchone()

        if not existing:
            conn.execute("""
                INSERT INTO alerts (alert_type, title, message, source, severity)
                VALUES (?, ?, ?, ?, ?)
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


def run_fda_recall():
    """執行 FDA 召回爬蟲"""
    async def _run():
        try:
            crawler = FDARecallCrawler()
            result = await crawler.run()
            await crawler.close()
            logger.info(f"FDA 召回爬蟲完成: {result}")
        except Exception as e:
            logger.error(f"FDA 召回爬蟲失敗: {e}")
            _create_failure_alert("fda_recall", str(e))
    asyncio.run(_run())


def run_fda_maude():
    """執行 FDA MAUDE 爬蟲"""
    async def _run():
        try:
            crawler = FDAMaudeCrawler()
            result = await crawler.run()
            await crawler.close()
            logger.info(f"FDA MAUDE 爬蟲完成: {result}")
        except Exception as e:
            logger.error(f"FDA MAUDE 爬蟲失敗: {e}")
            _create_failure_alert("fda_maude", str(e))
    asyncio.run(_run())


def run_tfda():
    """執行 TFDA 爬蟲"""
    async def _run():
        try:
            crawler = TFDACrawler()
            result = await crawler.run()
            await crawler.close()
            logger.info(f"TFDA 爬蟲完成: {result}")
        except Exception as e:
            logger.error(f"TFDA 爬蟲失敗: {e}")
            _create_failure_alert("tfda", str(e))
    asyncio.run(_run())


def run_standards():
    """執行標準版本檢查"""
    async def _run():
        try:
            crawler = StandardsCrawler()
            result = await crawler.run()
            await crawler.close()
            logger.info(f"標準版本檢查完成: {result}")
        except Exception as e:
            logger.error(f"標準版本檢查失敗: {e}")
            _create_failure_alert("standards", str(e))
    asyncio.run(_run())


def init_scheduler():
    """初始化排程器"""
    scheduler.add_job(
        run_fda_recall,
        trigger=IntervalTrigger(hours=CRAWL_INTERVAL_FDA_RECALL),
        id="fda_recall",
        name="FDA 召回爬蟲",
        replace_existing=True,
    )

    scheduler.add_job(
        run_fda_maude,
        trigger=IntervalTrigger(hours=CRAWL_INTERVAL_FDA_MAUDE),
        id="fda_maude",
        name="FDA MAUDE 爬蟲",
        replace_existing=True,
    )

    scheduler.add_job(
        run_tfda,
        trigger=IntervalTrigger(hours=CRAWL_INTERVAL_TFDA),
        id="tfda",
        name="TFDA 爬蟲",
        replace_existing=True,
    )

    scheduler.add_job(
        run_standards,
        trigger=IntervalTrigger(hours=CRAWL_INTERVAL_STANDARDS),
        id="standards",
        name="標準版本檢查",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("✅ 排程器啟動完成（v2: 含失敗告警機制）")
    logger.info(f"  - FDA Recall: 每 {CRAWL_INTERVAL_FDA_RECALL} 小時")
    logger.info(f"  - FDA MAUDE: 每 {CRAWL_INTERVAL_FDA_MAUDE} 小時")
    logger.info(f"  - TFDA: 每 {CRAWL_INTERVAL_TFDA} 小時")
    logger.info(f"  - Standards: 每 {CRAWL_INTERVAL_STANDARDS} 小時")


def shutdown_scheduler():
    """關閉排程器"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("排程器已關閉")
