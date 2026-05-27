"""
FDA 指引文件 & CFR 法規更新追蹤爬蟲

涵蓋：
- FDA Guidance Documents (R402) -> 使用 FDA Open Data API
- 21 CFR Part 820 等 CFR 規定 (R401) -> 使用 eCFR API
"""
import re
import logging
from datetime import datetime
from crawlers.base import BaseCrawler
from database import get_db

logger = logging.getLogger(__name__)

# FDA Guidance Documents API (Open Data Portal)
FDA_GUIDANCE_API = "https://api.fda.gov/other/historicaldocument.json?search=openfda.type:guidance&limit=100&skip=0"
# eCFR Part 820 最後修訂日期 API
ECFR_PART_820_API = "https://www.ecfr.gov/api/versioner/v1/versions/title-21.json?part=820"


# 常見 FDA Guidance 關鍵字 -> 資料庫中的 standard_number (R402-XXXX-XX)
FDA_GUIDANCE_KEYWORDS = {
    "R402-0001-01": ["Medical Device Accessories", "Accessories", "Classification Pathways"],
    "R402-0002-01": ["510(k) Program", "Substantial Equivalence", "Premarket Notification"],
    "R402-0003-01": ["Magnetic Resonance", "MR Environment", "MRI"],
    "R402-0004-01": ["Sterility Information", "Sterile", "510(k)"],
    "R402-0005-01": ["Reprocessing Medical Devices", "Validation Methods", "Labeling"],
    "R402-0006-01": ["Electromagnetic Compatibility", "EMC", "Medical Devices"],
    "R402-0007-01": ["Biocompatibility Testing", "ASCA", "Accreditation"],
    "R402-0008-01": ["Non-Clinical Bench Performance", "Premarket Submissions"],
    "R402-0009-01": ["Pyrogen", "Endotoxins Testing"],
    "R402-0010-01": ["ISO 10993-1", "Biological evaluation"],
    "R402-0011-01": ["Software Validation", "Final Guidance"],
    "R402-0012-01": ["Patient Labeling"],
    "R402-0013-01": ["Device Labeling", "Blue Book"],
    "R402-0014-01": ["Animal Studies", "Medical Devices"],
    "R402-0015-01": ["Q-Submission", "Feedback", "Meetings"],
    "R402-0016-01": ["Off-The-Shelf Software"],
    "R402-0017-01": ["Human Factors", "Usability Engineering"],
    "R402-0018-01": ["Software Functions", "Premarket"],
}


class FdaGuidanceCrawler(BaseCrawler):
    """FDA 指引文件與 CFR 法規更新追蹤爬蟲"""

    def __init__(self):
        super().__init__("fda_guidance")
        self._min_interval = 2.0

    async def _check_ecfr_820(self) -> dict:
        """
        透過 eCFR API 取得 21 CFR Part 820 的最後修訂版本資訊。
        """
        try:
            response = await self.get(ECFR_PART_820_API)
            if response.status_code == 200:
                data = response.json()
                versions = data.get("content_versions", [])
                if versions:
                    latest = versions[-1]
                    return {
                        "version": latest.get("date", ""),
                        "status": "active",
                    }
        except Exception as e:
            logger.warning(f"[{self.name}] eCFR API 查詢失敗: {e}")
        return {}

    async def _fetch_fda_guidances(self) -> list:
        """
        使用 FDA API 查詢最近的 FDA Guidance 文件清單。
        """
        guidances = []
        try:
            response = await self.get(FDA_GUIDANCE_API)
            if response.status_code == 200:
                data = response.json()
                for result in data.get("results", []):
                    guidances.append({
                        "title": result.get("title", ""),
                        "date": result.get("date", ""),
                        "url": result.get("url", ""),
                    })
        except Exception as e:
            logger.warning(f"[{self.name}] FDA Guidance API 查詢失敗: {e}")
        return guidances

    def _match_guidance(self, fda_guidances: list, keywords: list) -> dict:
        """
        從 FDA Guidance 清單中，透過關鍵字找到最相符的文件。
        """
        for fda_doc in fda_guidances:
            title = fda_doc.get("title", "")
            if any(kw.lower() in title.lower() for kw in keywords):
                return fda_doc
        return {}

    def _update_standard_row(self, std_id: int, latest_version: str, has_update: int):
        """更新單筆 standards 表格記錄"""
        conn = get_db()
        try:
            conn.execute("""
                UPDATE standards SET
                    latest_version = ?,
                    has_update = ?,
                    last_checked = ?,
                    updated_at = ?
                WHERE id = ?
            """, (latest_version, has_update,
                  datetime.now().isoformat(), datetime.now().isoformat(),
                  std_id))
            conn.commit()
        finally:
            conn.close()

    async def run(self, historical: bool = False, product_ids: list = None, **kwargs):
        """執行 FDA 指引與 CFR 更新檢查"""
        started_at = datetime.now().isoformat()
        log_id = self.start_crawl_log(started_at)
        total_checked = 0
        total_updated = 0

        try:
            conn = get_db()
            r401_stds = conn.execute(
                "SELECT id, standard_number, title, current_version FROM standards WHERE standard_number LIKE 'R401%'"
            ).fetchall()
            r402_stds = conn.execute(
                "SELECT id, standard_number, title, current_version FROM standards WHERE standard_number LIKE 'R402%'"
            ).fetchall()
            conn.close()

            # 1. 21 CFR Part 820 版本檢查
            for std_row in r401_stds:
                if "21 CFR Part 820" in (std_row["title"] or ""):
                    info = await self._check_ecfr_820()
                    total_checked += 1
                    if info.get("version"):
                        new_ver = info["version"]
                        old_ver = std_row["current_version"] or ""
                        has_update = 1 if new_ver != old_ver else 0
                        self._update_standard_row(std_row["id"], new_ver, has_update)
                        if has_update:
                            total_updated += 1
                            self.create_alert(
                                alert_type="standard_update",
                                title=f"CFR 更新: {std_row['standard_number']}",
                                message=f"21 CFR Part 820 最新版本日期: {new_ver}",
                                source="FDA / eCFR",
                                reference_id=std_row["id"],
                                reference_table="standards",
                            )
                    else:
                        self._update_standard_row(std_row["id"], std_row["current_version"] or "", 0)

            # 2. FDA Guidance 文件更新檢查（使用 API 清單比對關鍵字）
            if r402_stds:
                logger.info(f"[{self.name}] 取得 FDA Guidance 文件清單")
                fda_guidances = await self._fetch_fda_guidances()

                for std_row in r402_stds:
                    std_num = std_row["standard_number"]
                    keywords = FDA_GUIDANCE_KEYWORDS.get(std_num, [])
                    total_checked += 1

                    if not keywords:
                        # 無對應關鍵字，僅更新 last_checked
                        self._update_standard_row(std_row["id"], std_row["current_version"] or "", 0)
                        continue

                    matched = self._match_guidance(fda_guidances, keywords)
                    if matched:
                        new_date = matched.get("date", "")
                        old_ver = std_row["current_version"] or ""
                        has_update = 1 if new_date and new_date != old_ver else 0
                        self._update_standard_row(std_row["id"], new_date or old_ver, has_update)
                        if has_update:
                            total_updated += 1
                            self.create_alert(
                                alert_type="standard_update",
                                title=f"FDA Guidance 更新: {std_num}",
                                message=f"偵測到文件更新，最新日期: {new_date}",
                                source="FDA",
                                reference_id=std_row["id"],
                                reference_table="standards",
                            )
                    else:
                        self._update_standard_row(std_row["id"], std_row["current_version"] or "", 0)

            self.finish_crawl_log(log_id, "success", total_checked, total_updated)
            logger.info(f"[{self.name}] 完成: 檢查 {total_checked} 個，更新 {total_updated} 個")
            return {"checked": total_checked, "updated": total_updated}

        except Exception as e:
            self.finish_crawl_log(log_id, "error", total_checked, total_updated, str(e))
            logger.error(f"[{self.name}] 執行失敗: {e}")
            raise
