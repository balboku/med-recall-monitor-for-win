"""APScheduler 排程器 — 定時執行爬蟲任務（v2: 遷移至 Celery Tasks）"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from celery_app import run_crawler_task
from config import (
    CRAWL_INTERVAL_FDA_RECALL,
    CRAWL_INTERVAL_FDA_MAUDE,
    CRAWL_INTERVAL_TFDA,
    CRAWL_INTERVAL_STANDARDS,
)

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

def run_fda_recall():
    logger.info("排程器: 發送 FDA 召回爬蟲 Celery 任務")
    run_crawler_task.delay("fda_recall", False)

def run_fda_maude():
    logger.info("排程器: 發送 FDA MAUDE 爬蟲 Celery 任務")
    run_crawler_task.delay("fda_maude", False)

def run_tfda():
    logger.info("排程器: 發送 TFDA 爬蟲 Celery 任務")
    run_crawler_task.delay("tfda", False)

def run_standards():
    logger.info("排程器: 發送標準版本 Celery 任務")
    run_crawler_task.delay("standards", False)

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
    logger.info("✅ 排程器啟動完成（已整合 Celery 佇列）")
    logger.info(f"  - FDA Recall: 每 {CRAWL_INTERVAL_FDA_RECALL} 小時")
    logger.info(f"  - FDA MAUDE: 每 {CRAWL_INTERVAL_FDA_MAUDE} 小時")
    logger.info(f"  - TFDA: 每 {CRAWL_INTERVAL_TFDA} 小時")
    logger.info(f"  - Standards: 每 {CRAWL_INTERVAL_STANDARDS} 小時")


def shutdown_scheduler():
    """關閉排程器"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("排程器已關閉")
