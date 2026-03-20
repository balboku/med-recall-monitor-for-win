import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from database import get_db

from services.ai_service import ai_service
from crawlers.fda_recall import FDARecallCrawler
from crawlers.fda_maude import FDAMaudeCrawler

router = APIRouter(prefix="/api/reports", tags=["reports"])

class GenerateReportRequest(BaseModel):
    start_date: str  # YYYY-MM-DD
    end_date: str    # YYYY-MM-DD

class AnalyzeRecordRequest(BaseModel):
    record_type: str # "recall" or "event"
    raw_data: str

@router.get("")
def get_reports():
    conn = get_db()
    cursor = conn.cursor()
    reports = cursor.execute("""
        SELECT r.id, r.product_id, p.name as product_name, r.start_date, r.end_date, r.stats_json, r.created_at
        FROM reports r
        JOIN products p ON r.product_id = p.id
        ORDER BY r.id DESC
    """).fetchall()
    
    result = []
    for r in reports:
        row = dict(r)
        # Parse stats_json string back to dict for API JSON
        if row.get("stats_json"):
            try:
                row["stats_json"] = json.loads(row["stats_json"])
            except:
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
        except:
            pass
            
    return row

@router.post("/generate/{product_id}")
def generate_report(product_id: int, req: GenerateReportRequest):
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
        # 爬取並儲存到本地
        recalls_data = recall_crawler.run_history(product_dict, start_fmt, end_fmt)
        events_data = maude_crawler.run_history(product_dict, start_fmt, end_fmt)
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Failed to fetch history: {str(e)}")

    # 組合給 AI 閱讀的資料 (減少資料量，只保留摘要)
    combined_data = {
        "recalls": [
            {
                "reason": r.get("reason_for_recall"), 
                "classification": r.get("classification"),
                "date": r.get("center_classification_date")
            } for r in recalls_data
        ],
        "events": [
            {
                "type": r.get("event_type", ""), 
                "description": r.get("mdr_text", [{}])[0].get("text", "")[:500], # 取前500字元
                "outcome": r.get("patient", [{}])[0].get("sequence_number_outcome", "")
            } for r in events_data
        ]
    }
    
    html_report, stats_json = ai_service.generate_product_report(
        product_dict["name"], req.start_date, req.end_date, json.dumps(combined_data, ensure_ascii=False)
    )
    
    cursor = conn.execute("""
        INSERT INTO reports (product_id, start_date, end_date, report_html, stats_json, model_used)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (product_id, req.start_date, req.end_date, html_report, stats_json, "gemini-2.5-flash"))
    conn.commit()
    new_id = cursor.lastrowid
    
    conn.close()
    
    stats_dict = {}
    try:
        stats_dict = json.loads(stats_json)
    except:
        pass
        
    return {
        "id": new_id, 
        "product_id": product_id,
        "start_date": req.start_date,
        "end_date": req.end_date,
        "report_html": html_report, 
        "stats_json": stats_dict
    }

@router.post("/analyze-record")
def analyze_record(req: AnalyzeRecordRequest):
    """
    單筆紀錄 AI 解析，存入資料表避免重複耗費額度
    """
    conn = get_db()
    cursor = conn.cursor()
    table_name = "recalls" if req.record_type == "recall" else "adverse_events"
    record = cursor.execute(f"SELECT * FROM {table_name} WHERE id = ?", (req.record_id,)).fetchone()
    if not record:
        conn.close()
        raise HTTPException(status_code=404, detail="Record not found")
        
    row = dict(record)
    if row.get("ai_analysis"):
        conn.close()
        return {"html": row["ai_analysis"]}
        
    # 如果沒解析過就呼叫 AI
    html_insight = ai_service.analyze_single_record(req.record_type, row["raw_data"])
    
    # 回寫結果
    cursor.execute(f"UPDATE {table_name} SET ai_analysis = ? WHERE id = ?", (html_insight, req.record_id))
    conn.commit()
    conn.close()

    return {"html": html_insight}
