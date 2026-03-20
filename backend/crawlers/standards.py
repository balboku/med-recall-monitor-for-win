"""IEC/ISO 標準版本追蹤爬蟲"""
import re
import logging
from datetime import datetime
from bs4 import BeautifulSoup
from crawlers.base import BaseCrawler
from database import get_db

logger = logging.getLogger(__name__)

# 預設追蹤的標準及其查詢 URL
STANDARD_SOURCES = {
    "IEC 60601-1": {
        "url": "https://webstore.iec.ch/en/publication/2606",
        "title": "Medical electrical equipment - Part 1: General requirements for basic safety and essential performance",
    },
    "IEC 60601-2-5": {
        "url": "https://webstore.iec.ch/en/publication/2632",
        "title": "Medical electrical equipment - Part 2-5: Particular requirements for the basic safety and essential performance of ultrasonic physiotherapy equipment",
    },
    "IEC 60601-2-37": {
        "url": "https://webstore.iec.ch/en/publication/2647",
        "title": "Medical electrical equipment - Part 2-37: Particular requirements for the basic safety and essential performance of ultrasonic medical diagnostic and monitoring equipment",
    },
    "ISO 13485": {
        "url": "https://www.iso.org/standard/59752.html",
        "title": "Medical devices - Quality management systems - Requirements for regulatory purposes",
    },
    "ISO 14971": {
        "url": "https://www.iso.org/standard/72704.html",
        "title": "Medical devices - Application of risk management to medical devices",
    },
    "IEC 62304": {
        "url": "https://webstore.iec.ch/en/publication/6793",
        "title": "Medical device software - Software life cycle processes",
    },
    "IEC 62366-1": {
        "url": "https://webstore.iec.ch/en/publication/21863",
        "title": "Medical devices - Part 1: Application of usability engineering to medical devices",
    },
}


class StandardsCrawler(BaseCrawler):
    """IEC/ISO 標準版本追蹤爬蟲"""

    def __init__(self):
        super().__init__("standards")
        self._min_interval = 3.0  # 對標準機構網站放慢速率

    def _parse_iec_page(self, html: str) -> dict:
        """解析 IEC 標準頁面，擷取版本資訊"""
        soup = BeautifulSoup(html, "lxml")
        info = {}

        # 嘗試找到版本/版次資訊
        # IEC 頁面結構可能變動，使用多種選擇器
        edition_el = soup.find(string=re.compile(r"Edition\s*\d", re.IGNORECASE))
        if edition_el:
            match = re.search(r"Edition\s*(\d+\.?\d*)", str(edition_el), re.IGNORECASE)
            if match:
                info["edition"] = match.group(1)

        # 尋找出版日期
        date_el = soup.find(string=re.compile(r"\d{4}-\d{2}-\d{2}"))
        if date_el:
            match = re.search(r"(\d{4}-\d{2}-\d{2})", str(date_el))
            if match:
                info["publication_date"] = match.group(1)

        # 嘗試從標題找版本年份
        title = soup.find("h1") or soup.find("title")
        if title:
            title_text = title.get_text()
            match = re.search(r":(\d{4})", title_text)
            if match:
                info["version_year"] = match.group(1)
            info["full_title"] = title_text.strip()

        # 尋找狀態
        status_el = soup.find(string=re.compile(r"(Published|Withdrawn|Under revision|Preliminary)", re.IGNORECASE))
        if status_el:
            info["status"] = status_el.strip()

        return info

    def _parse_iso_page(self, html: str) -> dict:
        """解析 ISO 標準頁面，擷取版本資訊"""
        soup = BeautifulSoup(html, "lxml")
        info = {}

        # ISO 頁面結構
        # 找標題 (含年份)
        title_el = soup.find("h1") or soup.select_one(".std-title")
        if title_el:
            title_text = title_el.get_text(strip=True)
            match = re.search(r":(\d{4})", title_text)
            if match:
                info["version_year"] = match.group(1)
            info["full_title"] = title_text

        # 找 Edition
        edition_el = soup.find(string=re.compile(r"Edition\s*:\s*\d", re.IGNORECASE))
        if edition_el:
            match = re.search(r"Edition\s*:\s*(\d+)", str(edition_el), re.IGNORECASE)
            if match:
                info["edition"] = match.group(1)

        # 找出版日期
        date_patterns = [
            r"Publication date\s*:\s*(\d{4}-\d{2})",
            r"Published\s*:\s*(\d{4}-\d{2})",
        ]
        for pattern in date_patterns:
            date_el = soup.find(string=re.compile(pattern, re.IGNORECASE))
            if date_el:
                match = re.search(pattern, str(date_el), re.IGNORECASE)
                if match:
                    info["publication_date"] = match.group(1)
                    break

        # 找狀態
        status_el = soup.select_one(".stage-code") or soup.find(string=re.compile(r"Status\s*:", re.IGNORECASE))
        if status_el:
            info["status"] = status_el.get_text(strip=True) if hasattr(status_el, 'get_text') else str(status_el).strip()

        return info

    def _check_standard(self, standard_number: str, source_url: str) -> dict:
        """檢查單一標準的最新版本"""
        try:
            response = self.get(source_url)
            html = response.text

            if "iec.ch" in source_url:
                info = self._parse_iec_page(html)
            elif "iso.org" in source_url:
                info = self._parse_iso_page(html)
            else:
                info = {}

            # 組合版本字串
            version = ""
            if info.get("version_year"):
                version = info["version_year"]
            elif info.get("edition"):
                version = f"Ed.{info['edition']}"

            return {
                "version": version,
                "publication_date": info.get("publication_date", ""),
                "status": info.get("status", ""),
                "title": info.get("full_title", ""),
            }

        except Exception as e:
            logger.error(f"[{self.name}] 檢查 {standard_number} 失敗: {e}")
            return {}

    def _update_standard(self, standard_id: int, latest_info: dict) -> bool:
        """更新標準版本資訊，回傳是否有更新"""
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT * FROM standards WHERE id = ?", (standard_id,)
            ).fetchone()

            if not row:
                return False

            current_version = row["latest_version"] or row["current_version"] or ""
            new_version = latest_info.get("version", "")

            has_update = False
            if new_version and new_version != current_version and current_version:
                has_update = True

            conn.execute("""
                UPDATE standards SET
                    latest_version = ?,
                    status = COALESCE(?, status),
                    has_update = ?,
                    last_checked = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                new_version or current_version,
                latest_info.get("status"),
                1 if has_update else 0,
                datetime.now().isoformat(),
                datetime.now().isoformat(),
                standard_id,
            ))
            conn.commit()
            return has_update
        finally:
            conn.close()

    def init_default_standards(self):
        """初始化預設追蹤的標準"""
        conn = get_db()
        try:
            for std_num, info in STANDARD_SOURCES.items():
                existing = conn.execute(
                    "SELECT id FROM standards WHERE standard_number = ?",
                    (std_num,)
                ).fetchone()

                if not existing:
                    conn.execute("""
                        INSERT INTO standards (standard_number, title, source_url)
                        VALUES (?, ?, ?)
                    """, (std_num, info["title"], info["url"]))

            conn.commit()
            logger.info(f"[{self.name}] 預設標準初始化完成")
        finally:
            conn.close()

    def run(self):
        """執行標準版本檢查"""
        started_at = datetime.now().isoformat()
        total_checked = 0
        total_updated = 0

        conn = get_db()
        try:
            standards = conn.execute("SELECT * FROM standards").fetchall()
            standards = [dict(row) for row in standards]
        finally:
            conn.close()

        if not standards:
            logger.info(f"[{self.name}] 無追蹤的標準，初始化預設清單")
            self.init_default_standards()
            return {"checked": 0, "updated": 0}

        logger.info(f"[{self.name}] 開始檢查 {len(standards)} 個標準")

        for std in standards:
            source_url = std.get("source_url", "")
            if not source_url:
                continue

            latest_info = self._check_standard(std["standard_number"], source_url)
            total_checked += 1

            if latest_info:
                if self._update_standard(std["id"], latest_info):
                    total_updated += 1
                    self.create_alert(
                        alert_type="standard_update",
                        title=f"標準更新: {std['standard_number']}",
                        message=f"最新版本: {latest_info.get('version', 'N/A')}",
                        source="IEC/ISO",
                        reference_id=std["id"],
                        reference_table="standards",
                    )

        self.log_crawl("success", total_checked, total_updated, started_at=started_at)
        logger.info(f"[{self.name}] 完成: 檢查 {total_checked} 個，更新 {total_updated} 個")
        return {"checked": total_checked, "updated": total_updated}
