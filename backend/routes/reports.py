import json
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from database import get_db, write_audit_log

from services.ai_service import ai_service
from crawlers.fda_recall import FDARecallCrawler
from crawlers.fda_maude import FDAMaudeCrawler

router = APIRouter(prefix="/api/reports", tags=["reports"])


class GenerateReportRequest(BaseModel):
    start_date: str  # YYYY-MM-DD
    end_date: str    # YYYY-MM-DD
    operator: Optional[str] = "system"


class AnalyzeRecordRequest(BaseModel):
    record_type: str  # "recall" or "event"
    raw_data: Optional[str] = None
    record_id: Optional[int] = None


class ApproveReportRequest(BaseModel):
    operator: str     # 審核人員姓名/帳號
    action: str       # "approve" 或 "supersede"
    superseded_by: Optional[int] = None  # 若是廢止，填入取代的報告 ID


@router.get("")
def get_reports():
    conn = get_db()
    cursor = conn.cursor()
    reports = cursor.execute("""
        SELECT r.id, r.product_id, p.name as product_name, r.start_date, r.end_date,
               r.stats_json, r.report_status, r.generated_by, r.approved_by,
               r.approved_at, r.data_truncated, r.total_records_analyzed,
               r.created_at, r.superseded_by, r.model_used
        FROM reports r
        JOIN products p ON r.product_id = p.id
        ORDER BY r.id DESC
    """).fetchall()

    result = []
    for r in reports:
        row = dict(r)
        if row.get("stats_json"):
            try:
                row["stats_json"] = json.loads(row["stats_json"])
            except Exception:
                pass
        result.append(row)

    conn.close()
    return result


@router.get("/{report_id}")
def get_report(report_id: int):
    conn = get_db()
    cursor = conn.cursor()
    report = cursor.execute("""
        SELECT r.*, p.name as product_name
        FROM reports r
        JOIN products p ON r.product_id = p.id
        WHERE r.id = ?
    """, (report_id,)).fetchone()
    conn.close()

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    row = dict(report)
    if row.get("stats_json"):
        try:
            row["stats_json"] = json.loads(row["stats_json"])
        except Exception:
            row["stats_json"] = {}
    return row


@router.post("/generate/{product_id}")
def generate_report(product_id: int, req: GenerateReportRequest, request: Request):
    conn = get_db()
    product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if not product:
        conn.close()
        raise HTTPException(status_code=404, detail="Product not found")

    operator = req.operator or "system"
    ip = request.client.host if request.client else None

    # 1. 建立初始報告紀錄，狀態為 'generating'
    cursor = conn.execute("""
        INSERT INTO reports (product_id, start_date, end_date, report_html, report_status, generated_by)
        VALUES (?, ?, ?, '', 'generating', ?)
    """, (product_id, req.start_date, req.end_date, operator))
    conn.commit()
    new_id = cursor.lastrowid

    # 2. 寫入初始稽核日誌
    write_audit_log(conn, operator, "CREATE_REPORT_ASYNC", "reports",
                    target_id=new_id, ip_address=ip)
    conn.commit()
    conn.close()

    # 3. 呼叫 Celery 任務進行背景分析
    from celery_app import generate_report_task
    generate_report_task.delay(
        new_id, product_id, req.start_date, req.end_date, operator, ip
    )

    return {
        "id": new_id,
        "product_id": product_id,
        "start_date": req.start_date,
        "end_date": req.end_date,
        "report_status": "generating",
        "message": "報告生成任務已啟動，請在稍後查看結果。"
    }



@router.put("/{report_id}/approve")
def approve_report(report_id: int, req: ApproveReportRequest, request: Request):
    """P1-4: 報告審核/簽核端點（核准 or 廢止）"""
    conn = get_db()
    report = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    if not report:
        conn.close()
        raise HTTPException(status_code=404, detail="Report not found")

    old_status = report["report_status"]
    ip = request.client.host if request.client else None

    if req.action == "approve":
        if old_status == "approved":
            conn.close()
            raise HTTPException(status_code=400, detail="報告已為核准狀態")
        conn.execute("""
            UPDATE reports SET report_status='approved', approved_by=?, approved_at=? WHERE id=?
        """, (req.operator, datetime.now().isoformat(), report_id))
        new_status = "approved"
    elif req.action == "supersede":
        conn.execute("""
            UPDATE reports SET report_status='superseded', superseded_by=? WHERE id=?
        """, (req.superseded_by, report_id))
        new_status = "superseded"
    else:
        conn.close()
        raise HTTPException(status_code=400, detail="action 必須為 'approve' 或 'supersede'")

    # 寫入稽核日誌
    write_audit_log(conn, req.operator, f"REPORT_{req.action.upper()}", "reports",
                    target_id=report_id,
                    old_value=old_status, new_value=new_status,
                    ip_address=ip)
    conn.commit()
    conn.close()
    return {"id": report_id, "report_status": new_status, "approved_by": req.operator}


@router.get("/audit-log")
def get_audit_log(limit: int = 50):
    """P1-2: 取得稽核日誌"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.post("/analyze-record")
def analyze_record(req: AnalyzeRecordRequest):
    """單筆紀錄 AI 解析，存入資料表避免重複耗費額度"""
    raw_data = req.raw_data
    
    # 若前端沒傳原始資料但有 ID，我們自己從資料庫撈
    if not raw_data and req.record_id:
        conn = get_db()
        try:
            table = "recalls" if req.record_type == "recall" else "adverse_events"
            row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (req.record_id,)).fetchone()
            if row:
                d = dict(row)
                d.pop('ai_analysis', None) # 避免遞迴包含舊分析
                raw_data = json.dumps(d, ensure_ascii=False)
        finally:
            conn.close()

    if not raw_data:
        raise HTTPException(status_code=400, detail="無法獲取分析所需的原始資料")

    html_insight = ai_service.analyze_single_record(req.record_type, raw_data)

    if req.record_id:
        table_name = "recalls" if req.record_type == "recall" else "adverse_events"
        conn = get_db()
        try:
            conn.execute(f"UPDATE {table_name} SET ai_analysis = ? WHERE id = ?",
                         (html_insight, req.record_id))
            conn.commit()
        except Exception as e:
            print(f"⚠️ 更新 ai_analysis 失敗: {e}")
        finally:
            conn.close()

    return {"html": html_insight}


@router.delete("/{report_id}")
def delete_report(report_id: int, request: Request, operator: Optional[str] = "system"):
    """P9: 刪除報告"""
    conn = get_db()
    try:
        report = conn.execute("SELECT id, report_status FROM reports WHERE id = ?", (report_id,)).fetchone()
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        if report["report_status"] == "approved":
            raise HTTPException(status_code=400, detail="已核准的報告不可刪除，請改用廢止流程")

        ip = request.client.host if request.client else None
        
        conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
        write_audit_log(conn, operator, "DELETE_REPORT", "reports",
                        target_id=report_id, ip_address=ip)
        conn.commit()
    finally:
        conn.close()
    return {"id": report_id, "status": "deleted"}
