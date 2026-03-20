"""APScheduler 排程器 — 定時執行爬蟲任務"""
import logging
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


def run_fda_recall():
    """執行 FDA 召回爬蟲"""
    try:
        crawler = FDARecallCrawler()
        result = crawler.run()
        logger.info(f"FDA 召回爬蟲完成: {result}")
    except Exception as e:
        logger.error(f"FDA 召回爬蟲失敗: {e}")


def run_fda_maude():
    """執行 FDA MAUDE 爬蟲"""
    try:
        crawler = FDAMaudeCrawler()
        result = crawler.run()
        logger.info(f"FDA MAUDE 爬蟲完成: {result}")
    except Exception as e:
        logger.error(f"FDA MAUDE 爬蟲失敗: {e}")


def run_tfda():
    """執行 TFDA 爬蟲"""
    try:
        crawler = TFDACrawler()
        result = crawler.run()
        logger.info(f"TFDA 爬蟲完成: {result}")
    except Exception as e:
        logger.error(f"TFDA 爬蟲失敗: {e}")


def run_standards():
    """執行標準版本檢查"""
    try:
        crawler = StandardsCrawler()
        result = crawler.run()
        logger.info(f"標準版本檢查完成: {result}")
    except Exception as e:
        logger.error(f"標準版本檢查失敗: {e}")


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
    logger.info("✅ 排程器啟動完成")
    logger.info(f"  - FDA Recall: 每 {CRAWL_INTERVAL_FDA_RECALL} 小時")
    logger.info(f"  - FDA MAUDE: 每 {CRAWL_INTERVAL_FDA_MAUDE} 小時")
    logger.info(f"  - TFDA: 每 {CRAWL_INTERVAL_TFDA} 小時")
    logger.info(f"  - Standards: 每 {CRAWL_INTERVAL_STANDARDS} 小時")


def shutdown_scheduler():
    """關閉排程器"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("排程器已關閉")
