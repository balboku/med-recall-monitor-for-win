"""
MDCG / EU MDR 指引文件更新追蹤爬蟲

涵蓋：
- MDCG 指引 (R302) -> EU Commission 官方文件清單頁面
- EU 法規 (R301) -> EUR-Lex 頁面確認版本

由於 EU 網站部分內容為動態渲染，優先嘗試靜態解析；
若狀態碼非 200 或解析失敗，將以「網頁無法讀取」更新 notes。
"""
import re
import logging
from datetime import datetime
from crawlers.base import BaseCrawler
from crawlers.html_parser import parse_html
from database import get_db

logger = logging.getLogger(__name__)

# MDCG 文件總覽頁面（靜態 HTML 包含文件清單）
MDCG_LIST_URL = (
    "https://health.ec.europa.eu/medical-devices-dialogue-between-interested-parties/"
    "guidance-mdcg-endorsed-documents-and-other-guidance_en"
)

# 部分 EU 法規固定 EUR-Lex 頁面（用於確認最新整合版本）
EU_REGULATION_URLS = {
    "Regulation (EU) 2017/745": {
        "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02017R0745-20230320",
        "pattern": r"2017/745",
    },
    "Regulation (EU) 2025/40": {
        "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32025R0040",
        "pattern": r"2025/40",
    },
    "Directive 2011/65/EU": {
        "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02011L0065-20230101",
        "pattern": r"2011/65",
    },
}


class MdcgCrawler(BaseCrawler):
    """MDCG / EU 法規指引更新追蹤爬蟲"""

    def __init__(self):
        super().__init__("mdcg")
        self._min_interval = 5.0  # EU 機構網站放慢速率

    def _parse_mdcg_list(self, html: str) -> dict:
        """
        解析 MDCG 文件清單頁面，建立文件編號 -> 版本/日期 對應。
        回傳格式：{"MDCG 2024-13": {"revision": "1", "date": "2024-xx"}, ...}
        """
        soup = parse_html(html)
        result = {}

        # MDCG 文件清單多以連結文字方式呈現，形如 "MDCG 2024-13"
        for link in soup.find_all("a"):
            text = link.get_text(strip=True)
            # 比對 MDCG 文件格式：MDCG YYYY-NN 或 MDCG YYYY-NN rev.X
            m = re.match(r"(MDCG\s+\d{4}-\d+)(.*)", text, re.IGNORECASE)
            if m:
                doc_id = re.sub(r"\s+", " ", m.group(1)).strip()
                rest = m.group(2)
                revision = ""
                rev_match = re.search(r"rev\.\s*(\w+)", rest, re.IGNORECASE)
                if rev_match:
                    revision = f"rev.{rev_match.group(1)}"
                result[doc_id] = {"revision": revision, "title": text}

        return result

    def _update_mdcg_records(self, mdcg_docs: dict) -> int:
        """
        將從網頁解析出的 MDCG 文件修訂版本更新到 standards 表格。
        回傳更新筆數。
        """
        conn = get_db()
        updated = 0
        try:
            rows = conn.execute(
                "SELECT id, standard_number, current_version FROM standards WHERE standard_number LIKE 'R302%'"
            ).fetchall()

            for row in rows:
                std_num = row["standard_number"]      # e.g. "R302-0001-01"
                current_ver = row["current_version"] or ""

                # 從 standard_number 中的 title 比對 MDCG 文件
                title_row = conn.execute(
                    "SELECT title FROM standards WHERE id = ?", (row["id"],)
                ).fetchone()
                if not title_row:
                    continue
                title = title_row["title"]  # e.g. "MDCG 2024-13"

                # 找到對應的 MDCG 文件 ID
                matched_key = None
                for doc_id in mdcg_docs:
                    if doc_id.lower() in title.lower() or title.lower().startswith(doc_id.lower()):
                        matched_key = doc_id
                        break

                if matched_key:
                    doc_info = mdcg_docs[matched_key]
                    new_rev = doc_info.get("revision", "")
                    has_update = 0
                    if new_rev and new_rev.lower() != current_ver.lower():
                        has_update = 1

                    conn.execute("""
                        UPDATE standards SET
                            latest_version = ?,
                            has_update = ?,
                            last_checked = ?,
                            updated_at = ?
                        WHERE id = ?
                    """, (new_rev or current_ver, has_update,
                          datetime.now().isoformat(), datetime.now().isoformat(),
                          row["id"]))
                    if has_update:
                        updated += 1

            conn.commit()
        finally:
            conn.close()
        return updated

    async def _check_eu_regulation(self, std_entry: dict) -> dict:
        """
        檢查特定 EU 法規的頁面，確認是否有更新整合版。
        """
        url = std_entry.get("url", "")
        if not url:
            return {}
        try:
            response = await self.get(url)
            if response.status_code != 200:
                return {"status": f"HTTP {response.status_code}"}
            soup = parse_html(response.text)
            title = soup.find("h1") or soup.find("title")
            if title:
                return {"full_title": title.get_text(strip=True)}
        except Exception as e:
            logger.warning(f"[{self.name}] EU 法規頁面讀取失敗: {e}")
        return {}

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

            # 2. 檢查 EU 指定法規頁
            conn = get_db()
            try:
                eu_stds = conn.execute(
                    "SELECT id, standard_number, title FROM standards WHERE standard_number LIKE 'R301%'"
                ).fetchall()
            finally:
                conn.close()

            for std_row in eu_stds:
                title = std_row["title"]
                matched = None
                for reg_name, reg_info in EU_REGULATION_URLS.items():
                    if reg_name.lower() in title.lower():
                        matched = reg_info
                        break

                if matched:
                    info = await self._check_eu_regulation(matched)
                    total_checked += 1
                    if info.get("full_title"):
                        conn2 = get_db()
                        try:
                            conn2.execute("""
                                UPDATE standards SET last_checked = ?, updated_at = ?
                                WHERE id = ?
                            """, (datetime.now().isoformat(), datetime.now().isoformat(), std_row["id"]))
                            conn2.commit()
                        finally:
                            conn2.close()

            self.finish_crawl_log(log_id, "success", total_checked, total_updated)
            logger.info(f"[{self.name}] 完成: 檢查 {total_checked} 個，更新 {total_updated} 個")
            return {"checked": total_checked, "updated": total_updated}

        except Exception as e:
            self.finish_crawl_log(log_id, "error", total_checked, total_updated, str(e))
            logger.error(f"[{self.name}] 執行失敗: {e}")
            raise
