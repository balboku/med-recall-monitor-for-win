"""P3-2: 跨產品趨勢分析 API + 稽核日誌查詢"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Query
from typing import Optional
from database import get_db

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/trend")
def get_recall_trend(period: str = Query("3months", description="期間: 1month / 3months / 6months / 1year / all")):
    """
    P3-2: 召回與不良事件月度趨勢（供管理審查 MRM 儀表板使用）
    """
    period_map = {
        "1month": 30,
        "3months": 90,
        "6months": 180,
        "1year": 365,
    }
    
    if period == "all":
        since = "1900-01-01"
    else:
        days = period_map.get(period, 90)
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    conn = get_db()
    try:
        # 月度召回趨勢
        recall_trend = conn.execute("""
            SELECT
                strftime('%Y-%m', recall_date) as month,
                classification,
                COUNT(*) as count
            FROM recalls
            WHERE recall_date >= ?
            GROUP BY month, classification
            ORDER BY month ASC
        """, (since,)).fetchall()

        # 月度不良事件趨勢
        event_trend = conn.execute("""
            SELECT
                strftime('%Y-%m', date_received) as month,
                event_type,
                COUNT(*) as count
            FROM adverse_events
            WHERE date_received >= ?
            GROUP BY month, event_type
            ORDER BY month ASC
        """, (since,)).fetchall()

        # Class I 召回月度數（最高風險，需重點追蹤）
        class1_trend = conn.execute("""
            SELECT
                strftime('%Y-%m', recall_date) as month,
                COUNT(*) as count
            FROM recalls
            WHERE recall_date >= ? AND classification LIKE '%Class I%'
            GROUP BY month
            ORDER BY month ASC
        """, (since,)).fetchall()

        # 各產品召回統計排名
        product_ranking = conn.execute("""
            SELECT
                p.name as product_name,
                COUNT(r.id) as recall_count,
                SUM(CASE WHEN r.classification LIKE '%Class I%' THEN 1 ELSE 0 END) as class1_count
            FROM recalls r
            LEFT JOIN products p ON r.product_id = p.id
            WHERE r.recall_date >= ?
            GROUP BY p.id, p.name
            ORDER BY recall_count DESC
        """, (since,)).fetchall()

        return {
            "period": period,
            "since": since,
            "recall_monthly_trend": [dict(r) for r in recall_trend],
            "event_monthly_trend": [dict(r) for r in event_trend],
            "class1_monthly_trend": [dict(r) for r in class1_trend],
            "product_ranking": [dict(r) for r in product_ranking],
        }
    finally:
        conn.close()


@router.get("/competitor")
def get_competitor_analysis(fda_code: str = Query(..., description="FDA Product Code，例如 KZE")):
    """
    P3-2: 同 FDA 產品代碼的競品召回分析
    """
    conn = get_db()
    try:
        # 從 recalls 表中篩選同 product code 的競品（不同廠商）
        competitor_recalls = conn.execute("""
            SELECT
                firm_name,
                classification,
                recall_date,
                reason,
                status,
                url
            FROM recalls
            WHERE product_description LIKE ? OR reason LIKE ?
            ORDER BY recall_date DESC
            LIMIT 100
        """, (f"%{fda_code}%", f"%{fda_code}%")).fetchall()

        # 廠商統計
        firm_stats = conn.execute("""
            SELECT firm_name, COUNT(*) as count
            FROM recalls
            WHERE product_description LIKE ? OR reason LIKE ?
            GROUP BY firm_name
            ORDER BY count DESC
            LIMIT 10
        """, (f"%{fda_code}%", f"%{fda_code}%")).fetchall()

        return {
            "fda_code": fda_code,
            "total_found": len(competitor_recalls),
            "competitor_recalls": [dict(r) for r in competitor_recalls],
            "firm_statistics": [dict(r) for r in firm_stats],
        }
    finally:
        conn.close()


@router.get("/mrm-summary")
def get_mrm_summary():
    """
    P3-2: 管理審查月報摘要（Management Review Meeting Summary）
    供每月 MRM 會議使用，提供跨產品的品質指標一覽
    """
    conn = get_db()
    try:
        now = datetime.now()
        this_month = now.strftime("%Y-%m")
        last_month = (now - timedelta(days=30)).strftime("%Y-%m")
        
        # 計算本季的所屬月份列表 (例如 Q1 = 01, 02, 03)
        this_quarter = (now.month - 1) // 3 + 1
        quarter_months = [f"{now.year}-{str(m).zfill(2)}" for m in range(this_quarter * 3 - 2, this_quarter * 3 + 1)]

        # 本月新增召回 (以 FDA 公布/召回發生日為準)
        monthly_recalls = conn.execute("""
            SELECT COUNT(*) as cnt FROM recalls
            WHERE strftime('%Y-%m', recall_date) = ?
        """, (this_month,)).fetchone()["cnt"]

        # 本月新增事件 (以 FDA 收件/發生日為準)
        monthly_events = conn.execute("""
            SELECT COUNT(*) as cnt FROM adverse_events
            WHERE strftime('%Y-%m', date_received) = ?
        """, (this_month,)).fetchone()["cnt"]

        # 本季 Class I 召回總數
        placeholders = ','.join(['?'] * len(quarter_months))
        class1_total = conn.execute(f"""
            SELECT COUNT(*) as cnt FROM recalls
            WHERE classification LIKE '%Class I%'
            AND strftime('%Y-%m', recall_date) IN ({placeholders})
        """, tuple(quarter_months)).fetchone()["cnt"]

        # 未讀告警數
        unread_alerts = conn.execute("""
            SELECT COUNT(*) as cnt FROM alerts WHERE is_read = 0
        """).fetchone()["cnt"]

        # 有更新的標準數
        updated_standards = conn.execute("""
            SELECT COUNT(*) as cnt FROM standards WHERE has_update > 0
        """).fetchone()["cnt"]

        # 未簽核報告數
        pending_reports = conn.execute("""
            SELECT COUNT(*) as cnt FROM reports WHERE report_status = 'draft'
        """).fetchone()["cnt"]

        # 最近 CAPA 狀態（有 capa_ref 的召回）
        capa_linked = conn.execute("""
            SELECT COUNT(*) as cnt FROM recalls WHERE capa_ref IS NOT NULL AND capa_ref != ''
        """).fetchone()["cnt"]

        return {
            "generated_at": now.isoformat(),
            "reporting_month": this_month,
            "kpi": {
                "new_recalls_this_month": monthly_recalls,
                "new_events_this_month": monthly_events,
                "class1_recalls_total": class1_total,  # Frontend accesses this key for '本季'
                "unread_alerts": unread_alerts,
                "standards_needing_update": updated_standards,
                "reports_pending_approval": pending_reports,
                "recalls_with_capa": capa_linked,
            }
        }
    finally:
        conn.close()


@router.get("/audit-log")
def get_audit_log(
    target_table: Optional[str] = None,
    operator: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200)
):
    """P1-2: 稽核追蹤日誌查詢"""
    conn = get_db()
    try:
        conditions = []
        params = []
        if target_table:
            conditions.append("target_table = ?")
            params.append(target_table)
        if operator:
            conditions.append("operator = ?")
            params.append(operator)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = conn.execute(
            f"SELECT * FROM audit_log {where} ORDER BY created_at DESC LIMIT ?",
            params + [limit]
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
