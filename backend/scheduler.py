import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import (
    CRAWL_INTERVAL_FDA_MAUDE,
    CRAWL_INTERVAL_FDA_RECALL,
    CRAWL_INTERVAL_STANDARDS,
    CRAWL_INTERVAL_TFDA,
    CRAWL_INTERVAL_MDCG,
    CRAWL_INTERVAL_FDA_GUIDANCE,
    CRAWL_INTERVAL_TFDA_REGULATIONS,
)
from task_queue import enqueue_crawler, get_task_queue_mode


logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def run_fda_recall() -> None:
    mode = enqueue_crawler("fda_recall", False)
    logger.info("Scheduled FDA recall crawl dispatched via %s", mode)


def run_fda_maude() -> None:
    mode = enqueue_crawler("fda_maude", False)
    logger.info("Scheduled FDA MAUDE crawl dispatched via %s", mode)


def run_tfda() -> None:
    mode = enqueue_crawler("tfda", False)
    logger.info("Scheduled TFDA crawl dispatched via %s", mode)


def run_standards() -> None:
    mode = enqueue_crawler("standards", False)
    logger.info("Scheduled standards crawl dispatched via %s", mode)


def run_mdcg() -> None:
    mode = enqueue_crawler("mdcg", False)
    logger.info("Scheduled MDCG crawl dispatched via %s", mode)


def run_fda_guidance() -> None:
    mode = enqueue_crawler("fda_guidance", False)
    logger.info("Scheduled FDA Guidance crawl dispatched via %s", mode)


def run_tfda_regulations() -> None:
    mode = enqueue_crawler("tfda_regulations", False)
    logger.info("Scheduled TFDA Regulations crawl dispatched via %s", mode)


def init_scheduler() -> None:
    scheduler.add_job(
        run_fda_recall,
        trigger=IntervalTrigger(hours=CRAWL_INTERVAL_FDA_RECALL),
        id="fda_recall",
        name="FDA recall crawl",
        replace_existing=True,
    )
    scheduler.add_job(
        run_fda_maude,
        trigger=IntervalTrigger(hours=CRAWL_INTERVAL_FDA_MAUDE),
        id="fda_maude",
        name="FDA MAUDE crawl",
        replace_existing=True,
    )
    scheduler.add_job(
        run_tfda,
        trigger=IntervalTrigger(hours=CRAWL_INTERVAL_TFDA),
        id="tfda",
        name="TFDA crawl",
        replace_existing=True,
    )
    scheduler.add_job(
        run_standards,
        trigger=IntervalTrigger(hours=CRAWL_INTERVAL_STANDARDS),
        id="standards",
        name="Standards crawl",
        replace_existing=True,
    )
    scheduler.add_job(
        run_mdcg,
        trigger=IntervalTrigger(hours=CRAWL_INTERVAL_MDCG),
        id="mdcg",
        name="MDCG guidance crawl",
        replace_existing=True,
    )
    scheduler.add_job(
        run_fda_guidance,
        trigger=IntervalTrigger(hours=CRAWL_INTERVAL_FDA_GUIDANCE),
        id="fda_guidance",
        name="FDA Guidance crawl",
        replace_existing=True,
    )
    scheduler.add_job(
        run_tfda_regulations,
        trigger=IntervalTrigger(hours=CRAWL_INTERVAL_TFDA_REGULATIONS),
        id="tfda_regulations",
        name="TFDA Regulations crawl",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started with task queue mode=%s", get_task_queue_mode())
    logger.info("  - FDA Recall: every %s hours", CRAWL_INTERVAL_FDA_RECALL)
    logger.info("  - FDA MAUDE: every %s hours", CRAWL_INTERVAL_FDA_MAUDE)
    logger.info("  - TFDA: every %s hours", CRAWL_INTERVAL_TFDA)
    logger.info("  - Standards (IEC/ISO): every %s hours", CRAWL_INTERVAL_STANDARDS)
    logger.info("  - MDCG: every %s hours", CRAWL_INTERVAL_MDCG)
    logger.info("  - FDA Guidance: every %s hours", CRAWL_INTERVAL_FDA_GUIDANCE)
    logger.info("  - TFDA Regulations: every %s hours", CRAWL_INTERVAL_TFDA_REGULATIONS)


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")
