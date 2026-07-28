"""
MDCG / EU MDR 指引文件更新追蹤爬蟲

涵蓋：
- MDCG 指引 (R302) -> EU Commission 官方文件清單頁面

解析與判定邏輯統一收在 crawlers/mdcg_guidance.py，本檔僅負責排程執行與資料回寫，
避免此排程爬蟲與法規標準掃描(StandardsCrawler)出現兩套會漸行漸遠的實作。

註：R301（EU 法規／指引）已改由 crawlers/eu_regulation.py 處理，本檔不再涵蓋。
"""
import logging
from datetime import datetime
from crawlers.base import BaseCrawler
from database import get_db

logger = logging.getLogger(__name__)

# MDCG 文件總覽頁面（靜態 HTML 包含文件清單）
# 註：舊網址 health.ec.europa.eu/medical-devices-dialogue-between-interested-parties/...
# 已失效（HTTP 404），執委會改版後移至 medical-devices-sector/new-regulations/ 之下。
MDCG_LIST_URL = (
    "https://health.ec.europa.eu/medical-devices-sector/new-regulations/"
    "guidance-mdcg-endorsed-documents-and-other-guidance_en"
)


class MdcgCrawler(BaseCrawler):
    """MDCG / EU 法規指引更新追蹤爬蟲"""

    def __init__(self):
        super().__init__("mdcg")
        self._min_interval = 5.0  # EU 機構網站放慢速率

    def _parse_mdcg_list(self, html: str) -> dict:
        """解析 MDCG 文件清單頁，回傳 {文件編號: {revision, title, variants, has_main}}。

        解析與判定邏輯統一收在 crawlers/mdcg_guidance.py，避免此排程爬蟲與
        法規標準掃描(StandardsCrawler)出現兩套會漸行漸遠的實作。
        """
        from crawlers import mdcg_guidance
        return mdcg_guidance.parse_listing(html)

    def _update_mdcg_records(self, mdcg_docs: dict) -> int:
        """依清單比對結果更新 R302 標準紀錄，回傳有更新的筆數。"""
        from crawlers import mdcg_guidance

        conn = get_db()
        pending_alerts = []
        try:
            rows = conn.execute(
                "SELECT id, standard_number, title, current_version "
                "FROM standards WHERE standard_number LIKE 'R302%'"
            ).fetchall()

            now_iso = datetime.now().isoformat()
            for row in rows:
                verdict = mdcg_guidance.judge_mdcg(
                    row["title"] or "", row["current_version"] or "", mdcg_docs
                )
                has_update = 1 if verdict.get("has_update") else 0
                conn.execute(
                    """UPDATE standards SET
                           latest_version = ?, has_update = ?, judge_label = ?,
                           last_checked = ?, updated_at = ?
                       WHERE id = ?""",
                    (verdict.get("now_year") or "", has_update,
                     verdict.get("judge_label") or "", now_iso, now_iso, row["id"]),
                )
                if has_update:
                    pending_alerts.append((row, verdict))
            conn.commit()
        finally:
            conn.close()

        # 提醒必須等上面的連線提交並關閉後才建立：create_alert 會另開一個連線，
        # 若在寫入交易仍開啟時呼叫，SQLite 會丟出 "database is locked"。
        for row, verdict in pending_alerts:
            self.create_alert(
                alert_type="standard_update",
                title=f"{verdict['judge_label']}: {row['standard_number']} {row['title']}",
                message=verdict.get("judge_message", ""),
                source="MDCG",
                reference_id=row["id"],
                reference_table="standards",
            )
        return len(pending_alerts)

    async def run(self, historical: bool = False, product_ids: list = None, **kwargs):
        """執行 MDCG 指引更新檢查"""
        started_at = datetime.now().isoformat()
        log_id = self.start_crawl_log(started_at)
        total_checked = 0
        total_updated = 0

        try:
            # 1. 抓取 MDCG 文件清單頁
            logger.info(f"[{self.name}] 抓取 MDCG 文件清單: {MDCG_LIST_URL}")
            try:
                response = await self.get(MDCG_LIST_URL)
                if response.status_code == 200:
                    mdcg_docs = self._parse_mdcg_list(response.text)
                    logger.info(f"[{self.name}] 解析到 {len(mdcg_docs)} 份 MDCG 文件")
                    if mdcg_docs:
                        total_updated += self._update_mdcg_records(mdcg_docs)
                    total_checked += 1
                else:
                    logger.warning(f"[{self.name}] MDCG 清單頁回傳 HTTP {response.status_code}")
                    total_checked += 1
            except Exception as e:
                logger.error(f"[{self.name}] MDCG 清單抓取失敗: {e}")

            # 註：R301（EU 法規／指引）原本也由此爬蟲以硬編碼的 EUR-Lex 合併版網址檢查，
            # 但那些網址會把合併版日期寫死（例如 CELEX:02011L0065-20230101），
            # 一旦法規再次合併就會失效並持續回報 404。該類別現已改由
            # crawlers/eu_regulation.py 以 CELEX 動態查詢現行合併版處理，故此處不再重複檢查。

            self.finish_crawl_log(log_id, "success", total_checked, total_updated)
            logger.info(f"[{self.name}] 完成: 檢查 {total_checked} 個，更新 {total_updated} 個")
            return {"checked": total_checked, "updated": total_updated}

        except Exception as e:
            self.finish_crawl_log(log_id, "error", total_checked, total_updated, str(e))
            logger.error(f"[{self.name}] 執行失敗: {e}")
            raise
