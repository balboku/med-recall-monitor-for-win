import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from database import get_db, write_audit_log
from services.ai_service import ai_service
from task_queue import enqueue_report


router = APIRouter(prefix="/api/reports", tags=["reports"])


class GenerateReportRequest(BaseModel):
    start_date: str
    end_date: str
    operator: Optional[str] = "system"


class AnalyzeRecordRequest(BaseModel):
    record_type: str
    raw_data: Optional[str] = None
    record_id: Optional[int] = None


class ApproveReportRequest(BaseModel):
    operator: str
    action: str
    superseded_by: Optional[int] = None


@router.get("")
def get_reports():
    conn = get_db()
    try:
        reports = conn.execute(
            """
            SELECT r.id, r.product_id, p.name as product_name, r.start_date, r.end_date,
                   r.stats_json, r.report_status, r.generated_by, r.approved_by,
                   r.approved_at, r.data_truncated, r.total_records_analyzed,
                   r.created_at, r.superseded_by, r.model_used
            FROM reports r
            JOIN products p ON r.product_id = p.id
            ORDER BY r.id DESC
            """
        ).fetchall()

        result = []
        for report in reports:
            row = dict(report)
            if row.get("stats_json"):
                try:
                    row["stats_json"] = json.loads(row["stats_json"])
                except Exception:
                    pass
            result.append(row)
        return result
    finally:
        conn.close()


@router.get("/{report_id}")
def get_report(report_id: int):
    conn = get_db()
    try:
        report = conn.execute(
            """
            SELECT r.*, p.name as product_name
            FROM reports r
            JOIN products p ON r.product_id = p.id
            WHERE r.id = ?
            """,
            (report_id,),
        ).fetchone()
    finally:
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
    try:
        product = conn.execute(
            "SELECT * FROM products WHERE id = ?",
            (product_id,),
        ).fetchone()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        operator = req.operator or "system"
        ip = request.client.host if request.client else None

        cursor = conn.execute(
            """
            INSERT INTO reports (product_id, start_date, end_date, report_html, report_status, generated_by)
            VALUES (?, ?, ?, '', 'generating', ?)
            """,
            (product_id, req.start_date, req.end_date, operator),
        )
        conn.commit()
        report_id = cursor.lastrowid

        write_audit_log(
            conn,
            operator,
            "CREATE_REPORT_ASYNC",
            "reports",
            target_id=report_id,
            ip_address=ip,
        )
        conn.commit()
    finally:
        conn.close()

    dispatch_mode = enqueue_report(
        report_id,
        product_id,
        req.start_date,
        req.end_date,
        operator,
        ip,
    )

    return {
        "id": report_id,
        "product_id": product_id,
        "start_date": req.start_date,
        "end_date": req.end_date,
        "report_status": "generating",
        "dispatch_mode": dispatch_mode,
        "message": "Report generation started. Refresh later to see the result.",
    }


@router.put("/{report_id}/approve")
def approve_report(report_id: int, req: ApproveReportRequest, request: Request):
    conn = get_db()
    try:
        report = conn.execute(
            "SELECT * FROM reports WHERE id = ?",
            (report_id,),
        ).fetchone()
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")

        old_status = report["report_status"]
        ip = request.client.host if request.client else None

        if req.action == "approve":
            if old_status == "approved":
                raise HTTPException(status_code=400, detail="Report is already approved")
            conn.execute(
                """
                UPDATE reports
                SET report_status='approved', approved_by=?, approved_at=?
                WHERE id=?
                """,
                (req.operator, datetime.now().isoformat(), report_id),
            )
            new_status = "approved"
        elif req.action == "supersede":
            conn.execute(
                """
                UPDATE reports
                SET report_status='superseded', superseded_by=?
                WHERE id=?
                """,
                (req.superseded_by, report_id),
            )
            new_status = "superseded"
        else:
            raise HTTPException(
                status_code=400,
                detail="action must be 'approve' or 'supersede'",
            )

        write_audit_log(
            conn,
            req.operator,
            f"REPORT_{req.action.upper()}",
            "reports",
            target_id=report_id,
            old_value=old_status,
            new_value=new_status,
            ip_address=ip,
        )
        conn.commit()
        return {
            "id": report_id,
            "report_status": new_status,
            "approved_by": req.operator,
        }
    finally:
        conn.close()


@router.get("/audit-log")
def get_audit_log(limit: int = 50):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@router.post("/analyze-record")
def analyze_record(req: AnalyzeRecordRequest):
    raw_data = req.raw_data

    if not raw_data and req.record_id:
        conn = get_db()
        try:
            table_name = "recalls" if req.record_type == "recall" else "adverse_events"
            row = conn.execute(
                f"SELECT * FROM {table_name} WHERE id = ?",
                (req.record_id,),
            ).fetchone()
            if row:
                record = dict(row)
                record.pop("ai_analysis", None)
                raw_data = json.dumps(record, ensure_ascii=False)
        finally:
            conn.close()

    if not raw_data:
        raise HTTPException(status_code=400, detail="raw_data or record_id is required")

    html_insight = ai_service.analyze_single_record(req.record_type, raw_data)

    if req.record_id:
        table_name = "recalls" if req.record_type == "recall" else "adverse_events"
        conn = get_db()
        try:
            conn.execute(
                f"UPDATE {table_name} SET ai_analysis = ? WHERE id = ?",
                (html_insight, req.record_id),
            )
            conn.commit()
        finally:
            conn.close()

    return {"html": html_insight}


@router.delete("/{report_id}")
def delete_report(report_id: int, request: Request, operator: Optional[str] = "system"):
    conn = get_db()
    try:
        report = conn.execute(
            "SELECT id, report_status FROM reports WHERE id = ?",
            (report_id,),
        ).fetchone()
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        if report["report_status"] == "approved":
            raise HTTPException(
                status_code=400,
                detail="Approved reports cannot be deleted. Supersede them instead.",
            )

        ip = request.client.host if request.client else None
        conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
        write_audit_log(
            conn,
            operator or "system",
            "DELETE_REPORT",
            "reports",
            target_id=report_id,
            ip_address=ip,
        )
        conn.commit()
        return {"id": report_id, "status": "deleted"}
    finally:
        conn.close()
