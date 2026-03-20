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
