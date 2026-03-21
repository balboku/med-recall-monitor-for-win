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
    raw_data: str
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
               r.approved_at, r.data_truncated, r.total_records_analyzed, r.created_at
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
    report = cursor.execute(
        "SELECT * FROM reports WHERE id = ?", (report_id,)
    ).fetchone()
    conn.close()

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    row = dict(report)
    if row.get("stats_json"):
        try:
            row["stats_json"] = json.loads(row["stats_json"])
        except Exception:
            pass

    return row


@router.post("/generate/{product_id}")
def generate_report(product_id: int, req: GenerateReportRequest, request: Request):
    conn = get_db()
    product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if not product:
        conn.close()
        raise HTTPException(status_code=404, detail="Product not found")

    product_dict = dict(product)

    # Format dates to YYYYMMDD for openFDA
    start_fmt = req.start_date.replace("-", "")
    end_fmt = req.end_date.replace("-", "")

    recall_crawler = FDARecallCrawler()
    maude_crawler = FDAMaudeCrawler()

    try:
        # P1-3: 追蹤是否發生資料截斷
        import asyncio
        recalls_data = asyncio.run(recall_crawler.run_history(product_dict, start_fmt, end_fmt))
        events_data = asyncio.run(maude_crawler.run_history(product_dict, start_fmt, end_fmt))
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Failed to fetch history: {str(e)}")

    total_records = recalls_data + events_data

    # 從資料庫取出這個產品在日期範圍內的紀錄
    recalls_rows = conn.execute("""
        SELECT product_description, firm_name, reason, classification, recall_date FROM recalls
        WHERE product_id = ? AND recall_date >= ? AND recall_date <= ?
    """, (product_id, req.start_date, req.end_date)).fetchall()

    events_rows = conn.execute("""
        SELECT event_type, brand_name, manufacturer, event_description, patient_outcome FROM adverse_events
        WHERE product_id = ? AND date_received >= ? AND date_received <= ?
    """, (product_id, req.start_date, req.end_date)).fetchall()

    # --- 大數據分批處理邏輯 (Batch Analysis / Map-Reduce) ---
    all_events = [dict(e) for e in events_rows]
    all_recalls = [dict(r) for r in recalls_rows]
    
    # 1. 準備統計大項 (為 Reduce 階段提供真實基準)
    total_stats = {
        "total_events": len(all_events),
        "total_recalls": len(all_recalls),
        "death_count": len([e for e in all_events if e.get("event_type") == "Death" or (e.get("patient_outcome") and "DEATH" in str(e.get("patient_outcome")).upper())]),
        "injury_count": len([e for e in all_events if e.get("event_type") == "Injury" or (e.get("patient_outcome") and "INJURY" in str(e.get("patient_outcome")).upper())]),
        "malfunction_count": len([e for e in all_events if e.get("event_type") == "Malfunction"])
    }

    # 2. 分批進行 Map 分析 (每 500 筆一組)
    batch_size = 500
    batch_summaries = []
    
    # 處理召回 (通常數量較少，視為一個單獨批次)
    if all_recalls:
        recall_batch_json = json.dumps(all_recalls, ensure_ascii=False)
        batch_summaries.append(ai_service.analyze_batch(f"產品召回資料: {recall_batch_json}"))

    # 處理不良事件 (分批)
    for i in range(0, len(all_events), batch_size):
        batch = all_events[i:i + batch_size]
        batch_json = json.dumps(batch, ensure_ascii=False)
        # 呼叫 AI 進行該批次摘要
        batch_summaries.append(ai_service.analyze_batch(f"不良事件批次 {i//batch_size + 1}: {batch_json}"))

    # 3. Reduce 階段：產出最終摘要報告
    html_report, stats_json = ai_service.generate_product_report(
        product_dict["name"], req.start_date, req.end_date, batch_summaries, total_stats
    )

    data_truncated = 0 # 已經分批處理，理論上不再有截斷問題
    total_records = len(all_events) + len(all_recalls)


    operator = req.operator or "system"
    ip = request.client.host if request.client else None

    # P1-3: 報告初始狀態為 draft
    from services.ai_service import MODEL_NAME
    cursor = conn.execute("""
        INSERT INTO reports (product_id, start_date, end_date, report_html, stats_json,
                             model_used, report_status, generated_by,
                             data_truncated, total_records_analyzed)
        VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)
    """, (product_id, req.start_date, req.end_date, html_report, stats_json,
          MODEL_NAME, operator, data_truncated, total_records))
    conn.commit()
    new_id = cursor.lastrowid

    # P1-2: 寫入稽核日誌
    write_audit_log(conn, operator, "CREATE_REPORT", "reports",
                    target_id=new_id, ip_address=ip)
    conn.commit()
    conn.close()

    stats_dict = {}
    try:
        stats_dict = json.loads(stats_json)
    except Exception:
        pass

    return {
        "id": new_id,
        "product_id": product_id,
        "start_date": req.start_date,
        "end_date": req.end_date,
        "report_html": html_report,
        "stats_json": stats_dict,
        "report_status": "draft",
        "generated_by": operator,
        "data_truncated": data_truncated,
        "total_records_analyzed": total_records,
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
    html_insight = ai_service.analyze_single_record(req.record_type, req.raw_data)

    if req.record_id:
        table_name = "recalls" if req.record_type == "recall" else "adverse_events"
        conn = get_db()
        try:
            conn.execute(f"UPDATE {table_name} SET ai_analysis = ? WHERE id = ?",
                         (html_insight, req.record_id))
            conn.commit()
        except Exception:
            pass  # ai_analysis 欄位可能尚未存在，忽略
        finally:
            conn.close()

    return {"html": html_insight}
