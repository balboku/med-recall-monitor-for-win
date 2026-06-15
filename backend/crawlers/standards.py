"""IEC/ISO 標準版本追蹤爬蟲"""
import re
import logging
from datetime import datetime
from crawlers.base import BaseCrawler
from crawlers.html_parser import parse_html
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
        soup = parse_html(html)
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
        soup = parse_html(html)
        info = {}

        # ISO 頁面結構
        # 找標題 (含年份)
        title_el = soup.find("h1") or soup.select_one(".std-title")
        base_number = ""
        if title_el:
            title_text = title_el.get_text(strip=True)
            match = re.search(r":(\d{4})", title_text)
            if match:
                info["version_year"] = match.group(1)
            info["full_title"] = title_text
            base_number = title_text.split(':')[0].strip()

        # 找 Amendment (例如 ISO 8601-1:2019/Amd 1:2022)
        html_text = soup.get_text()
        if base_number:
            import re
            escaped_base = re.escape(base_number)
            # 支援如 2019/Amd 1:2022 或是含多個 Amd/Cor 的寫法
            amd_pattern = rf'{escaped_base}:(\d{{4}}[/\+](?:(?:Amd|Cor)\s*\w+:\d{{4}}[/\+]*)+)'
            amd_matches = re.findall(amd_pattern, html_text, re.IGNORECASE)
            if amd_matches:
                info["version_year"] = amd_matches[-1].strip('+').strip('/')
                info["full_title"] = f"{base_number}:{info['version_year']}"

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
        else:
            # 部分 ISO 頁面僅以獨立文字節點顯示 "Withdrawn" / "Published"，沒有 "Status:" 前綴
            badge_el = soup.find(string=re.compile(r"^\s*(Withdrawn|Published)\s*$"))
            if badge_el:
                info["status"] = badge_el.strip()

        # 找「New version available」/「Revised by」區塊，偵測標準是否已有新版本取代
        # 例如 Withdrawn 的 ISO 2859-1:1999 頁面會顯示
        # "New version available: ISO 2859-1:2026"，連結指向新版頁面
        new_ver_node = soup.find(string=re.compile(r"(New version available|Revised by)", re.IGNORECASE))
        if new_ver_node:
            container = new_ver_node.parent
            link = container.find("a") if container else None
            if not link and container and container.parent:
                link = container.parent.find("a")
            if link and link.get("href"):
                new_title = link.get_text(strip=True)
                year_match = re.search(r":(\d{4})", new_title)
                if year_match:
                    info["new_edition_title"] = new_title
                    info["new_edition_url"] = link.get("href", "")
                    info["new_edition_year"] = year_match.group(1)

        return info

    def _extract_base_number(self, title: str) -> str:
        """從標準標題擷取基本編號（去除年份/修正案資訊），例如：
        'ISO 2859-1:1999' -> 'ISO 2859-1'
        'ISO 15223-1 2021 Amd 1 2025' -> 'ISO 15223-1'
        'IEC/TR 80002-1:2009' -> 'IEC/TR 80002-1'
        """
        if not title:
            return ""
        match = re.match(r"\s*((?:ISO|IEC)(?:/TR|/TS)?\s*[\d]+(?:[-/]\d+)*)", title, re.IGNORECASE)
        if match:
            return re.sub(r"\s+", " ", match.group(1).strip())
        return title.split(':')[0].strip()

    async def _check_standard(self, standard_number: str, source_url: str, expected_title: str = "") -> dict:
        """檢查單一標準的最新版本"""
        try:
            response = await self.get(source_url)
            html = response.text

            if "iec.ch" in source_url:
                info = self._parse_iec_page(html)
            elif "iso.org" in source_url:
                info = self._parse_iso_page(html)
            else:
                info = {}

            # 驗證抓回的標準編號是否與預期一致，避免 source_url 指向錯誤文件
            # (例如資料庫記錄為 ISO 2859-1，但 source_url 卻指向 ISO 11661 的頁面)
            expected_base = self._extract_base_number(expected_title)
            found_base = self._extract_base_number(info.get("full_title", ""))
            if (
                expected_base
                and found_base
                and self._normalize_base_number(expected_base) != self._normalize_base_number(found_base)
            ):
                logger.warning(
                    f"[{self.name}] {standard_number} 來源網址不符: "
                    f"預期「{expected_base}」，實際取得「{found_base}」 ({source_url})"
                )
                return {
                    "title_mismatch": True,
                    "expected_title": expected_title,
                    "found_title": info.get("full_title", ""),
                }

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
                "new_edition_title": info.get("new_edition_title", ""),
                "new_edition_url": info.get("new_edition_url", ""),
                "new_edition_year": info.get("new_edition_year", ""),
            }

        except Exception as e:
            logger.error(f"[{self.name}] 檢查 {standard_number} 失敗: {e}")
            return {}

    def _normalize_version(self, version: str) -> str:
        """標準化版本字串以利比對（移除空白、統一大小寫）"""
        return version.strip().lower().replace(" ", "") if version else ""

    def _normalize_base_number(self, base: str) -> str:
        """標準化標準基本編號以利比對，移除所有非英數字元
        （避免 'IEC/TR 80002-1' 與 'IEC TR 80002-1' 等格式差異造成誤判）"""
        return re.sub(r"[^a-z0-9]", "", base.lower()) if base else ""

    def _is_under_revision(self, status_str: str) -> bool:
        """P2-4: 判斷標準是否進入修訂中狀態"""
        if not status_str:
            return False
        return any(kw in status_str.lower() for kw in ["under revision", "revision", "preliminary", "draft"])

    def _update_standard(self, standard_id: int, latest_info: dict) -> bool:
        """P2-4: 更新標準版本資訊，回傳是否有更新（強化副版本比對）"""
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT * FROM standards WHERE id = ?", (standard_id,)
            ).fetchone()

            if not row:
                return False

            # 來源網址查到的標準與資料庫記錄不符（指向錯誤文件）
            # 不更新版本資訊，避免產生誤導的「有更新」提示，僅記錄查核失敗並建立警示
            if latest_info.get("title_mismatch"):
                mismatch_note = "⚠️ 來源網址查核失敗，請確認 source_url"
                notes = row["notes"] or ""
                if mismatch_note not in notes:
                    notes = f"{notes} {mismatch_note}".strip()

                conn.execute("""
                    UPDATE standards SET
                        notes = ?,
                        last_checked = ?,
                        updated_at = ?
                    WHERE id = ?
                """, (
                    notes,
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                    standard_id,
                ))
                conn.commit()

                self.create_alert(
                    alert_type="standard_url_mismatch",
                    title=f"⚠️ 標準來源網址不符: {row['standard_number']}",
                    message=(
                        f"預期文件「{latest_info.get('expected_title', row['title'])}」，"
                        f"但 source_url 查到的是「{latest_info.get('found_title', '')}」，"
                        f"目前網址: {row['source_url']}，請至追蹤設定修正來源網址。"
                    ),
                    source="IEC/ISO",
                    reference_id=standard_id,
                    reference_table="standards",
                )
                return False

            current_version = self._normalize_version(row["latest_version"] or row["current_version"] or "")
            new_version = self._normalize_version(latest_info.get("version", ""))
            status_str = latest_info.get("status", "")

            # 偵測「已有新版本發布」(例如目前追蹤頁面顯示 Withdrawn，
            # 且頁面上標示 New version available: ISO 2859-1:2026)
            new_edition_year = latest_info.get("new_edition_year", "")
            is_new_edition = bool(
                new_edition_year
                and self._normalize_version(new_edition_year) != current_version
            )
            if is_new_edition:
                new_version = self._normalize_version(new_edition_year)

            # has_update 枚舉: 0=無變化, 1=版本更新, 2=進入修訂中
            has_update = 0
            if self._is_under_revision(status_str):
                has_update = 2  # 標準進入修訂中，預告即將更版，需提前關注
            elif new_version and current_version and new_version != current_version:
                has_update = 1  # 版本號有實質變化（含已發布新版本的情況）

            latest_version_value = latest_info.get("version") or row["latest_version"] or row["current_version"]
            if is_new_edition:
                latest_version_value = new_edition_year

            conn.execute("""
                UPDATE standards SET
                    latest_version = ?,
                    status = COALESCE(?, status),
                    has_update = ?,
                    last_checked = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                latest_version_value,
                status_str or None,
                has_update,
                datetime.now().isoformat(),
                datetime.now().isoformat(),
                standard_id,
            ))
            conn.commit()

            if is_new_edition and has_update:
                self.create_alert(
                    alert_type="standard_new_edition",
                    title=f"📢 標準已有新版本: {row['standard_number']}",
                    message=(
                        f"{latest_info.get('new_edition_title', '')} 已發布，"
                        f"取代目前追蹤的 {row['title']}。"
                        f"新版頁面: {latest_info.get('new_edition_url', '')}"
                    ),
                    source="IEC/ISO",
                    reference_id=standard_id,
                    reference_table="standards",
                )
                latest_info["_new_edition_alert_created"] = True

            return has_update > 0  # 版本更新或進入修訂中都算有更新
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

    async def run(self, historical: bool = False, product_ids: list = None, **kwargs):
        """執行標準版本檢查"""
        started_at = datetime.now().isoformat()
        log_id = self.start_crawl_log(started_at)
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
            self.finish_crawl_log(log_id, "success", 0, 0)
            return {"checked": 0, "updated": 0}

        logger.info(f"[{self.name}] 開始檢查 {len(standards)} 個標準")

        try:
            from collections import defaultdict
            from urllib.parse import urlparse
            import asyncio
            
            domain_groups = defaultdict(list)
            for std in standards:
                source_url = std.get("source_url", "")
                if source_url:
                    domain = urlparse(source_url).netloc
                    domain_groups[domain].append(std)

            async def process_group(domain, stds):
                grp_checked = 0
                grp_updated = 0
                for std in stds:
                    latest_info = await self._check_standard(
                        std["standard_number"], std["source_url"], std.get("title", "")
                    )
                    grp_checked += 1

                    if latest_info:
                        updated = self._update_standard(std["id"], latest_info)
                        if updated:
                            grp_updated += 1
                            has_update_val = self._is_under_revision(latest_info.get("status", ""))
                            # 「已有新版本發布」的提醒已在 _update_standard 內建立，這裡不重複建立
                            if not latest_info.get("_new_edition_alert_created"):
                                alert_msg = (
                                    f"標準 {std['standard_number']} 進入修訂中狀態，請關注後續版本發布"
                                    if has_update_val
                                    else f"最新版本: {latest_info.get('version', 'N/A')}"
                                )
                                alert_title = (
                                    f"⚠️ 標準修訂中: {std['standard_number']}"
                                    if has_update_val
                                    else f"📋 標準更新: {std['standard_number']}"
                                )
                                self.create_alert(
                                    alert_type="standard_update",
                                    title=alert_title,
                                    message=alert_msg,
                                    source="IEC/ISO",
                                    reference_id=std["id"],
                                    reference_table="standards",
                                )
                return grp_checked, grp_updated

            logger.info(f"[{self.name}] 正在並行處理 {len(domain_groups)} 個網站來源...")
            tasks = [process_group(domain, stds) for domain, stds in domain_groups.items()]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for res in results:
                if isinstance(res, tuple):
                    total_checked += res[0]
                    total_updated += res[1]
                elif isinstance(res, Exception):
                    logger.error(f"[{self.name}] 站點群組處理時發生錯誤: {res}")

            self.finish_crawl_log(log_id, "success", total_checked, total_updated)
            logger.info(f"[{self.name}] 完成: 檢查 {total_checked} 個，更新 {total_updated} 個")
            return {"checked": total_checked, "updated": total_updated}
        except Exception as e:
            self.finish_crawl_log(log_id, "error", total_checked, total_updated, str(e))
            raise
