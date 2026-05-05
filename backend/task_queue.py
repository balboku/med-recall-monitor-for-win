import logging
import os
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Optional

from env_loader import load_environment


load_environment()

logger = logging.getLogger(__name__)

_VALID_TASK_QUEUE_MODES = {"local", "celery"}


def get_task_queue_mode() -> str:
    mode = os.getenv("TASK_QUEUE_MODE", "local").strip().lower()
    if mode not in _VALID_TASK_QUEUE_MODES:
        logger.warning("Unknown TASK_QUEUE_MODE=%s, falling back to local", mode)
        return "local"
    return mode


def is_local_task_queue() -> bool:
    return get_task_queue_mode() == "local"


def _get_local_executor() -> ThreadPoolExecutor:
    if not hasattr(_get_local_executor, "_executor"):
        try:
            max_workers = max(1, int(os.getenv("LOCAL_TASK_WORKERS", "2")))
        except ValueError:
            logger.warning("Invalid LOCAL_TASK_WORKERS value, falling back to 2")
            max_workers = 2
        _get_local_executor._executor = ThreadPoolExecutor(  # type: ignore[attr-defined]
            max_workers=max_workers,
            thread_name_prefix="medwatch-local",
        )
    return _get_local_executor._executor  # type: ignore[attr-defined]


def _log_future_result(future: Future) -> None:
    try:
        future.result()
    except Exception:
        logger.exception("Local background task failed")


def enqueue_crawler(crawler_name: str, historical: bool = False, product_ids: Optional[list] = None) -> str:
    from celery_app import run_crawler_task

    mode = get_task_queue_mode()
    if mode == "celery":
        run_crawler_task.delay(crawler_name, historical, product_ids)
        return mode

    future = _get_local_executor().submit(run_crawler_task, crawler_name, historical, product_ids)
    future.add_done_callback(_log_future_result)
    return mode


def enqueue_report(
    report_id: int,
    product_id: int,
    start_date: str,
    end_date: str,
    operator: str,
    request_ip: Optional[str],
) -> str:
    from celery_app import generate_report_task

    mode = get_task_queue_mode()
    if mode == "celery":
        generate_report_task.delay(
            report_id, product_id, start_date, end_date, operator, request_ip
        )
        return mode

    future = _get_local_executor().submit(
        generate_report_task,
        report_id,
        product_id,
        start_date,
        end_date,
        operator,
        request_ip,
    )
    future.add_done_callback(_log_future_result)
    return mode


def shutdown_task_queue() -> None:
    executor = getattr(_get_local_executor, "_executor", None)
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=False)
