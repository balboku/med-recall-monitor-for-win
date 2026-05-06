import os
import asyncio
import logging
from celery import Celery
from env_loader import load_environment

load_environment()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "medwatch_tasks",
    broker=REDIS_URL,
    backend=REDIS_URL
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Taipei",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
)

logger = logging.getLogger(__name__)

def _create_failure_alert(crawler_name: str, error: str):
    """P2-1: 爬蟲失敗時在 alerts 表寫入高嚴重性系統告警（SQLite/PostgreSQL 相容）"""
    from database import get_db
    conn = get_db()
    try:
        existing = conn.execute("""
            SELECT id FROM alerts
            WHERE alert_type='crawler_failure' AND source=?
              AND created_at >= datetime('now', '-1 hour')
        """, (crawler_name,)).fetchone()

        if not existing:
            conn.execute("""
                INSERT INTO alerts (alert_type, title, message, source, severity)
                VALUES (?, ?, ?, ?, ?)
            """, (
                "crawler_failure",
                f"⚠️ 爬蟲失敗告警: {crawler_name}",
                f"爬蟲 {crawler_name} 執行失敗，請確認資料可能已停止更新。錯誤: {str(error)[:200]}",
                crawler_name,
                "high",
            ))
            conn.commit()
            logger.warning(f"P2-1 告警已寫入: {crawler_name} 爬蟲失敗")
    except Exception as e:
        logger.error(f"寫入失敗告警時發生錯誤: {e}")
    finally:
        conn.close()


@celery_app.task
def run_crawler_task(crawler_name: str, historical: bool = False, product_ids: list = None):
    from crawlers.fda_recall import FDARecallCrawler
    from crawlers.fda_maude import FDAMaudeCrawler
    from crawlers.tfda import TFDACrawler
    from crawlers.standards import StandardsCrawler

    crawlers_map = {
        "fda_recall": FDARecallCrawler,
        "fda_maude": FDAMaudeCrawler,
        "tfda": TFDACrawler,
        "standards": StandardsCrawler,
    }

    if crawler_name not in crawlers_map:
        return f"Unknown crawler: {crawler_name}"

    cls = crawlers_map[crawler_name]

    async def _run():
        try:
            logger.info(f"開始執行 Celery 爬蟲任務: {crawler_name} (historical={historical}, product_ids={product_ids})")
            crawler = cls()
            await crawler.run(historical=historical, product_ids=product_ids)
            await crawler.close()
            logger.info(f"Celery 爬蟲任務完成: {crawler_name}")
        except Exception as e:
            logger.error(f"Celery 爬蟲任務失敗: {crawler_name}, 錯誤: {e}")
            _create_failure_alert(crawler_name, str(e))

    asyncio.run(_run())
    return f"Crawler {crawler_name} finished."


@celery_app.task
def generate_report_task(report_id: int, product_id: int, start_date: str, end_date: str, operator: str, request_ip: str):
    """P8: 在背景執行耗時的 AI 報告生成任務（拆分短連線避免長期佔用）"""
    import json
    from datetime import datetime
    from database import get_db, write_audit_log
    from services.ai_service import ai_service, MODEL_NAME
    from crawlers.fda_recall import FDARecallCrawler
    from crawlers.fda_maude import FDAMaudeCrawler

    # 1. 取得產品資訊（短連線 #1）
    conn = get_db()
    try:
        product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if not product:
            conn.execute("UPDATE reports SET report_status='failed' WHERE id=?", (report_id,))
            conn.commit()
            return f"Product {product_id} not found"
        product_dict = dict(product)
    finally:
        conn.close()

    start_fmt = start_date.replace("-", "")
    end_fmt = end_date.replace("-", "")

    try:
        # 2. 爬取最新歷史數據（不佔用 DB 連線）
        recall_crawler = FDARecallCrawler()
        maude_crawler = FDAMaudeCrawler()
        
        async def _fetch_all():
            r = await recall_crawler.run_history(product_dict, start_fmt, end_fmt)
            e = await maude_crawler.run_history(product_dict, start_fmt, end_fmt)
            await recall_crawler.close()
            await maude_crawler.close()
            return r, e

        asyncio.run(_fetch_all())

        # 3. 從資料庫取出紀錄（短連線 #2）
        conn2 = get_db()
        try:
            recalls_rows = conn2.execute("""
                SELECT product_description, firm_name, reason, classification, recall_date FROM recalls
                WHERE product_id = ? AND recall_date >= ? AND recall_date <= ?
            """, (product_id, start_date, end_date)).fetchall()

            events_rows = conn2.execute("""
                SELECT event_type, brand_name, manufacturer, event_description, patient_outcome, device_problem FROM adverse_events
                WHERE product_id = ? AND date_received >= ? AND date_received <= ?
            """, (product_id, start_date, end_date)).fetchall()

            all_events = [dict(e) for e in events_rows]
            all_recalls = [dict(r) for r in recalls_rows]
        finally:
            conn2.close()

        # 4. 計算統計大項（純記憶體運算，不需 DB）
        total_stats = {
            "total_events": len(all_events),
            "total_recalls": len(all_recalls),
            "death_count": len([e for e in all_events if e.get("event_type") == "Death" or (e.get("patient_outcome") and "DEATH" in str(e.get("patient_outcome")).upper())]),
            "injury_count": len([e for e in all_events if e.get("event_type") == "Injury" or (e.get("patient_outcome") and "INJURY" in str(e.get("patient_outcome")).upper())]),
            "malfunction_count": len([e for e in all_events if e.get("event_type") == "Malfunction"]),
            "brand_distribution": {},
            "failure_modes": {}
        }

        brands = {}
        for e in all_events:
            b = e.get("brand_name") or "Unknown"
            brands[b] = brands.get(b, 0) + 1
        for r in all_recalls:
            b = r.get("firm_name") or "Unknown"
            brands[b] = brands.get(b, 0) + 1
        total_stats["brand_distribution"] = dict(sorted(brands.items(), key=lambda x: x[1], reverse=True)[:10])

        fm = {}
        for e in all_events:
            p = e.get("device_problem") or "Unknown Problem"
            p = p.split(' (')[0]
            fm[p] = fm.get(p, 0) + 1
        for r in all_recalls:
            re = r.get("reason") or "Unknown Reason"
            re = (re[:40] + '..') if len(re) > 40 else re
            fm[re] = fm.get(re, 0) + 1
        total_stats["failure_modes"] = dict(sorted(fm.items(), key=lambda x: x[1], reverse=True)[:10])

        # 5. 分批 AI 分析（不需 DB，純 API 呼叫）
        batch_size = 500
        batch_summaries = []
        
        if all_recalls:
            recall_batch_json = json.dumps(all_recalls, ensure_ascii=False)
            batch_summaries.append(ai_service.analyze_batch(f"產品召回資料: {recall_batch_json}"))

        for i in range(0, len(all_events), batch_size):
            batch = all_events[i:i + batch_size]
            batch_json = json.dumps(batch, ensure_ascii=False)
            batch_summaries.append(ai_service.analyze_batch(f"不良事件批次 {i//batch_size + 1}: {batch_json}"))

        # 6. 生成最終報告（不需 DB，純 API 呼叫）
        html_report, stats_json = ai_service.generate_product_report(
            product_dict["name"], start_date, end_date, batch_summaries, total_stats
        )

        # 7. 更新資料庫（短連線 #3）
        total_records = len(all_events) + len(all_recalls)
        conn3 = get_db()
        try:
            conn3.execute("""
                UPDATE reports 
                SET report_html=?, stats_json=?, report_status='draft', 
                    total_records_analyzed=?, model_used=?
                WHERE id=?
            """, (html_report, stats_json, total_records, MODEL_NAME, report_id))
            
            write_audit_log(conn3, operator, "GENERATE_REPORT_COMPLETE", "reports",
                            target_id=report_id, ip_address=request_ip)
            conn3.commit()
        finally:
            conn3.close()
        logger.info(f"報告 {report_id} 生成完成")

    except Exception as e:
        logger.error(f"報告 {report_id} 生成失敗: {e}")
        conn_err = get_db()
        try:
            conn_err.execute("UPDATE reports SET report_status='failed' WHERE id=?", (report_id,))
            conn_err.commit()
        finally:
            conn_err.close()

    return f"Report {report_id} generated."

# Translation state is managed in translation_state.py (singleton across all threads)

def _run_translate_events_loop():
    """The actual translation loop — runs as a plain function so it works both
    in a daemon thread and as a Celery task body."""
    import time
    import random
    import translation_state
    from database import get_db

    if not translation_state.start_translation():
        logger.info("翻譯任務已在背景執行中，略過重複啟動")
        return

    logger.info("開始背景事件描述翻譯任務")

    try:
        while not translation_state.is_stopped():
            conn = get_db()
            try:
                rows = conn.execute(
                    "SELECT id, event_description FROM adverse_events "
                    "WHERE event_description_zh IS NULL "
                    "AND event_description IS NOT NULL AND event_description != '' "
                    "LIMIT 10"
                ).fetchall()
            finally:
                conn.close()

            if not rows:
                logger.info("已完成全庫事件描述翻譯")
                break

            for row in rows:
                if translation_state.is_stopped():
                    logger.info("背景事件翻譯被指示停止")
                    return

                record_id = row["id"]
                en_text = row["event_description"]
                try:
                    from deep_translator import GoogleTranslator
                    translated = GoogleTranslator(source='auto', target='zh-TW').translate(en_text)
                    upd_conn = get_db()
                    try:
                        upd_conn.execute(
                            "UPDATE adverse_events SET event_description_zh = ? WHERE id = ?",
                            (translated, record_id)
                        )
                        upd_conn.commit()
                    finally:
                        upd_conn.close()
                    logger.debug(f"已翻譯事件描述 ID: {record_id}")
                except Exception as e:
                    logger.warning(f"事件描述 ID: {record_id} 翻譯失敗: {e}")

                time.sleep(random.uniform(2, 4))

    except Exception as e:
        logger.error(f"全庫翻譯任務發生錯誤: {e}", exc_info=True)
    finally:
        translation_state.mark_done()
        logger.info("背景翻譯任務已結束")


@celery_app.task
def run_translate_events_task():
    _run_translate_events_loop()
    return "Translation task completed."
