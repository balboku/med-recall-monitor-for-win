"""不良事件查詢 API"""
from fastapi import APIRouter, Query
from typing import Optional
from database import get_db

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("")
def list_events(
    source: Optional[str] = None,
    product_id: Optional[int] = None,
    event_type: Optional[str] = None,
    search: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """查詢不良事件"""
    conn = get_db()
    try:
        conditions = []
        params = []

        if source:
            conditions.append("e.source = ?")
            params.append(source)
        if product_id:
            conditions.append("e.product_id = ?")
            params.append(product_id)
        if event_type:
            conditions.append("e.event_type LIKE ?")
            params.append(f"%{event_type}%")
        if search:
            conditions.append(
                "(e.event_description LIKE ? OR e.brand_name LIKE ? OR e.manufacturer LIKE ?)"
            )
            params.extend([f"%{search}%"] * 3)
        if start_date:
            conditions.append("e.date_received >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("e.date_received <= ?")
            params.append(end_date)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        offset = (page - 1) * page_size

        count_row = conn.execute(
            f"SELECT COUNT(*) as total FROM adverse_events e {where}", params
        ).fetchone()
        total = count_row["total"]

        rows = conn.execute(f"""
            SELECT e.*, p.name as product_name
            FROM adverse_events e
            LEFT JOIN products p ON e.product_id = p.id
            {where}
            ORDER BY e.date_received DESC, e.created_at DESC
            LIMIT ? OFFSET ?
        """, params + [page_size, offset]).fetchall()

        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size,
        }
    finally:
        conn.close()


@router.get("/stats")
def event_stats():
    """不良事件統計"""
    conn = get_db()
    try:
        stats = {}

        rows = conn.execute("""
            SELECT event_type, COUNT(*) as count FROM adverse_events
            GROUP BY event_type
        """).fetchall()
        stats["by_type"] = {row["event_type"]: row["count"] for row in rows}

        row = conn.execute("SELECT COUNT(*) as total FROM adverse_events").fetchone()
        stats["total"] = row["total"]

        row = conn.execute("""
            SELECT COUNT(*) as count FROM adverse_events
            WHERE created_at >= datetime('now', '-30 days')
        """).fetchone()
        stats["recent_30d"] = row["count"]

        return stats
    finally:
        conn.close()

from pydantic import BaseModel

class TranslationTaskResponse(BaseModel):
    message: str

@router.post("/translate/start", response_model=TranslationTaskResponse)
def start_translation_task():
    import translation_state
    import celery_app
    import threading
    import logging
    from task_queue import get_task_queue_mode

    if translation_state.is_running():
        return {"message": "翻譯任務已在執行中"}

    mode = get_task_queue_mode()
    if mode == "celery":
        celery_app.run_translate_events_task.delay()
    else:
        def _safe_run():
            try:
                celery_app._run_translate_events_loop()
            except Exception as e:
                logging.getLogger(__name__).error(f"Translation thread crashed: {e}", exc_info=True)
        t = threading.Thread(target=_safe_run, daemon=True, name="translation-worker")
        t.start()
        
    return {"message": "背景翻譯任務已啟動"}

@router.get("/translate/debug")
def debug_translation():
    import translation_state
    import threading
    return {
        "is_running": translation_state.is_running(),
        "is_stopped": translation_state.is_stopped(),
        "threads": [t.name for t in threading.enumerate()]
    }

@router.post("/translate/stop", response_model=TranslationTaskResponse)
def stop_translation_task():
    import translation_state
    translation_state.stop_translation()
    return {"message": "已成功送出停止翻譯任務的訊號"}

@router.get("/translate/progress")
def get_translation_progress():
    conn = get_db()
    try:
        import translation_state
        
        row_total = conn.execute("SELECT COUNT(*) as cnt FROM adverse_events WHERE event_description IS NOT NULL AND event_description != ''").fetchone()
        row_pending = conn.execute("SELECT COUNT(*) as cnt FROM adverse_events WHERE event_description_zh IS NULL AND event_description IS NOT NULL AND event_description != ''").fetchone()
        
        total = row_total["cnt"]
        pending = row_pending["cnt"]
        translated = total - pending

        return {
            "total": total,
            "translated": translated,
            "pending": pending,
            "is_running": translation_state.is_running()
        }
    finally:
        conn.close()

