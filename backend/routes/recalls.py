"""召回記錄查詢 API"""
from fastapi import APIRouter, Query
from typing import Optional
from database import get_db

router = APIRouter(prefix="/api/recalls", tags=["recalls"])


@router.get("")
def list_recalls(
    source: Optional[str] = None,
    product_id: Optional[int] = None,
    classification: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """查詢召回記錄"""
    conn = get_db()
    try:
        conditions = []
        params = []

        if source:
            conditions.append("r.source = ?")
            params.append(source)
        if product_id:
            conditions.append("r.product_id = ?")
            params.append(product_id)
        if classification:
            conditions.append("r.classification = ?")
            params.append(classification)
        if search:
            conditions.append(
                "(r.product_description LIKE ? OR r.reason LIKE ? OR r.firm_name LIKE ?)"
            )
            params.extend([f"%{search}%"] * 3)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        offset = (page - 1) * page_size

        # 取得總數
        count_row = conn.execute(
            f"SELECT COUNT(*) as total FROM recalls r {where}", params
        ).fetchone()
        total = count_row["total"]

        # 取得資料
        rows = conn.execute(f"""
            SELECT r.*, p.name as product_name
            FROM recalls r
            LEFT JOIN products p ON r.product_id = p.id
            {where}
            ORDER BY r.recall_date DESC, r.created_at DESC
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
def recall_stats():
    """召回統計資料"""
    conn = get_db()
    try:
        stats = {}

        # 各來源統計
        rows = conn.execute("""
            SELECT source, COUNT(*) as count FROM recalls GROUP BY source
        """).fetchall()
        stats["by_source"] = {row["source"]: row["count"] for row in rows}

        # 各等級統計
        rows = conn.execute("""
            SELECT classification, COUNT(*) as count FROM recalls
            WHERE classification != '' GROUP BY classification
        """).fetchall()
        stats["by_classification"] = {row["classification"]: row["count"] for row in rows}

        # 總數
        row = conn.execute("SELECT COUNT(*) as total FROM recalls").fetchone()
        stats["total"] = row["total"]

        # 最近 30 天新增
        row = conn.execute("""
            SELECT COUNT(*) as count FROM recalls
            WHERE created_at >= datetime('now', '-30 days')
        """).fetchone()
        stats["recent_30d"] = row["count"]

        return stats
    finally:
        conn.close()
