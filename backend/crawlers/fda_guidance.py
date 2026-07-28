"""FDA 指引與 CFR 法規更新追蹤爬蟲（排程入口）。

查詢與判定邏輯統一收在 crawlers/fda_docs.py，本檔僅負責排程執行與資料回寫，
避免此排程爬蟲與法規標準掃描(StandardsCrawler)出現兩套會漸行漸遠的實作。

原本此檔以 api.fda.gov/other/historicaldocument.json 查詢指引，實測該端點回傳
404「No matches found」（openFDA 並無指引資料）；現改用 FDA 官方指引資料集
search-for-guidance.json。eCFR 部分（21 CFR）原本即可運作，一併移入 fda_docs。
"""
import logging
from datetime import datetime

from crawlers.base import BaseCrawler
from database import get_db

logger = logging.getLogger(__name__)


class FdaGuidanceCrawler(BaseCrawler):
    """FDA 指引 / CFR 法規更新追蹤爬蟲"""

    def __init__(self):
        super().__init__("fda_guidance")
        self._min_interval = 1.0

    async def run(self, historical: bool = False, product_ids: list = None, **kwargs):
        """執行 FDA 指引與 CFR 更新檢查（R401 / R402）。"""
        from crawlers import fda_docs

        started_at = datetime.now().isoformat()
        log_id = self.start_crawl_log(started_at)
        total_checked = 0
        total_updated = 0

        try:
            conn = get_db()
            try:
                rows = conn.execute(
                    "SELECT id, standard_number, title, current_version FROM standards "
                    "WHERE standard_number LIKE 'R401%' OR standard_number LIKE 'R402%'"
                ).fetchall()
            finally:
                conn.close()

            logger.info(f"[{self.name}] 開始檢查 {len(rows)} 筆 FDA 文件")

            std_by_key = {str(r["id"]): r for r in rows}
            items = [{
                "key": str(r["id"]),
                "standard_name": r["title"] or "",
                "current_version": r["current_version"] or "",
            } for r in rows]

            counters = {"checked": 0, "updated": 0}
            pending_alerts = []

            def on_item(key, item, result):
                row = std_by_key.get(key)
                if row is None:
                    return
                counters["checked"] += 1
                now_iso = datetime.now().isoformat()
                if not result.get("ok"):
                    logger.warning(f"[{self.name}] {row['standard_number']} 查詢失敗: "
                                   f"{result.get('error')}")
                    label, latest, has_update = "查找失敗", None, 0
                else:
                    label = result.get("judge_label") or ""
                    latest = result.get("now_year") or None
                    has_update = 1 if result.get("has_update") else 0

                conn2 = get_db()
                try:
                    conn2.execute(
                        """UPDATE standards SET
                               latest_version = COALESCE(?, latest_version),
                               has_update = ?, judge_label = ?,
                               source_url = COALESCE(NULLIF(?, ''), source_url),
                               last_checked = ?, updated_at = ?
                           WHERE id = ?""",
                        (latest, has_update, label, result.get("source_url", ""),
                         now_iso, now_iso, row["id"]),
                    )
                    conn2.commit()
                finally:
                    conn2.close()

                if has_update:
                    counters["updated"] += 1
                    pending_alerts.append((row, result))

            await fda_docs.resolve_many(items, on_item)

            # 提醒須待回寫連線關閉後再建立，避免 SQLite "database is locked"
            for row, result in pending_alerts:
                self.create_alert(
                    alert_type="standard_update",
                    title=f"{result['judge_label']}: {row['standard_number']} {row['title']}",
                    message=result.get("judge_message", ""),
                    source="FDA",
                    reference_id=row["id"],
                    reference_table="standards",
                )

            total_checked, total_updated = counters["checked"], counters["updated"]
            self.finish_crawl_log(log_id, "success", total_checked, total_updated)
            logger.info(f"[{self.name}] 完成: 檢查 {total_checked} 個，更新 {total_updated} 個")
            return {"checked": total_checked, "updated": total_updated}

        except Exception as e:
            self.finish_crawl_log(log_id, "error", total_checked, total_updated, str(e))
            logger.error(f"[{self.name}] 執行失敗: {e}")
            raise
