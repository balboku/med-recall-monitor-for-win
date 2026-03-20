"""Dashboard 總覽 API"""
from fastapi import APIRouter, Query
from typing import Optional
from database import get_db

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def get_dashboard():
    """取得 Dashboard 總覽統計"""
    conn = get_db()
    try:
        stats = {}

        # 監控產品數
        row = conn.execute(
            "SELECT COUNT(*) as count FROM products WHERE is_active = 1"
        ).fetchone()
        stats["active_products"] = row["count"]

        # 召回總數
        row = conn.execute("SELECT COUNT(*) as count FROM recalls").fetchone()
        stats["total_recalls"] = row["count"]

        # 最近 7 天新增召回
        row = conn.execute("""
            SELECT COUNT(*) as count FROM recalls
            WHERE created_at >= datetime('now', '-7 days')
        """).fetchone()
        stats["new_recalls_7d"] = row["count"]

        # 不良事件總數
        row = conn.execute("SELECT COUNT(*) as count FROM adverse_events").fetchone()
        stats["total_events"] = row["count"]

        # 最近 7 天新增事件
        row = conn.execute("""
            SELECT COUNT(*) as count FROM adverse_events
            WHERE created_at >= datetime('now', '-7 days')
        """).fetchone()
        stats["new_events_7d"] = row["count"]

        # 標準追蹤數
        row = conn.execute("SELECT COUNT(*) as count FROM standards").fetchone()
        stats["total_standards"] = row["count"]

        # 有更新的標準數
        row = conn.execute(
            "SELECT COUNT(*) as count FROM standards WHERE has_update = 1"
        ).fetchone()
        stats["standards_with_updates"] = row["count"]

        # 未讀提醒數
        row = conn.execute(
            "SELECT COUNT(*) as count FROM alerts WHERE is_read = 0"
        ).fetchone()
        stats["unread_alerts"] = row["count"]

        # 最新 5 筆召回
        rows = conn.execute("""
            SELECT r.*, p.name as product_name FROM recalls r
            LEFT JOIN products p ON r.product_id = p.id
            ORDER BY r.created_at DESC LIMIT 5
        """).fetchall()
        stats["latest_recalls"] = [dict(row) for row in rows]

        # 最近爬蟲日誌
        rows = conn.execute("""
            SELECT * FROM crawl_logs
            ORDER BY completed_at DESC LIMIT 5
        """).fetchall()
        stats["latest_crawl_logs"] = [dict(row) for row in rows]

        return stats
    finally:
        conn.close()


@router.get("/alerts")
def list_alerts(
    is_read: Optional[int] = None,
    alert_type: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """取得提醒列表"""
    conn = get_db()
    try:
        conditions = []
        params = []

        if is_read is not None:
            conditions.append("is_read = ?")
            params.append(is_read)
        if alert_type:
            conditions.append("alert_type = ?")
            params.append(alert_type)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        offset = (page - 1) * page_size

        count_row = conn.execute(
            f"SELECT COUNT(*) as total FROM alerts {where}", params
        ).fetchone()
        total = count_row["total"]

        rows = conn.execute(f"""
            SELECT * FROM alerts {where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, params + [page_size, offset]).fetchall()

        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    finally:
        conn.close()


@router.put("/alerts/{alert_id}/read")
def mark_alert_read(alert_id: int):
    """標記提醒已讀"""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE alerts SET is_read = 1 WHERE id = ?", (alert_id,)
        )
        conn.commit()
        return {"message": "已標記為已讀"}
    finally:
        conn.close()


@router.put("/alerts/read-all")
def mark_all_alerts_read():
    """標記所有提醒已讀"""
    conn = get_db()
    try:
        conn.execute("UPDATE alerts SET is_read = 1 WHERE is_read = 0")
        conn.commit()
        return {"message": "所有提醒已標記為已讀"}
    finally:
        conn.close()
