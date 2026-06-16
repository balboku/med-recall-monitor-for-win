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

        # 找「New version available」/「Revised by」資訊，偵測標準是否已有新版本取代
        # 例如 Withdrawn 的 ISO 10993-1:2018 頁面會顯示
        # "New version available: ISO 10993-1:2025"，
        # 或在 Life cycle 區塊顯示「Revised by」+「Published」+「ISO 10993-1:2025」。
        # ISO/IEC 網站不同頁面的 DOM 巢狀結構不一致，往上層找最近的 <a> 標籤
        # 容易找不到連結，因此改以「整頁文字」比對找出新版編號/年份，
        # 再到整個頁面搜尋文字相符的連結（找不到連結仍可標記新版年份）。
        page_text = soup.get_text(separator=" ")
        new_ed_match = re.search(
            r"(?:New version available|Revised by)\s*:?\s*(?:Published\s*)?"
            r"((?:ISO|IEC)(?:/(?:IEC|TR|TS))?[\w/\-\s]*?:\s*(\d{4}))",
            page_text,
            re.IGNORECASE,
        )
        if new_ed_match:
            new_title = re.sub(r"\s+", " ", new_ed_match.group(1).strip())
            new_year = new_ed_match.group(2)
            info["new_edition_title"] = new_title
            info["new_edition_year"] = new_year

            new_title_base = self._normalize_base_number(self._extract_base_number(new_title))
            for a in soup.find_all("a"):
                href = a.get("href", "")
                if not href:
                    continue
                a_text = re.sub(r"\s+", " ", a.get_text(strip=True))
                if a_text == new_title or (
                    new_year in a_text
                    and new_title_base
                    and self._normalize_base_number(self._extract_base_number(a_text)) == new_title_base
                ):
                    info["new_edition_url"] = href
                    break

        return info

    def _extract_base_number(self, title: str) -> str:
        """從標準標題擷取基本編號（去除年份/修正案資訊），例如：
        'ISO 2859-1:1999' -> 'ISO 2859-1'
        'ISO 15223-1 2021 Amd 1 2025' -> 'ISO 15223-1'
        'IEC/TR 80002-1:2009' -> 'IEC/TR 80002-1'

        若文字中找不到 ISO/IEC 編號格式，回傳空字串（而非整段文字），
        避免將內部文件編號或純文字法規名稱誤判為「基本編號」進而與
        實際網頁標題比對失敗。
        """
        if not title:
            return ""
        match = re.search(r"((?:ISO|IEC)(?:/TR|/TS)?\s*[\d]+(?:[-/]\d+)*)", title, re.IGNORECASE)
        if match:
            return re.sub(r"\s+", " ", match.group(1).strip())
        return ""

    async def _check_standard(self, standard_number: str, source_url: str, expected_title: str = "") -> dict:
        """檢查單一標準的最新版本"""
        try:
            if "iso.org" in source_url:
                # www.iso.org 受 Cloudflare 防護，純 HTTP 會 403，改用虛擬瀏覽器取得頁面。
                # 瀏覽器須在獨立工作執行緒以全新事件迴圈執行（見 iso_browser 說明），
                # 故以 asyncio.to_thread 呼叫，避免與目前事件迴圈巢狀。
                import asyncio as _asyncio
                from crawlers import iso_browser
                if iso_browser.BROWSER_AVAILABLE:
                    html = await _asyncio.to_thread(iso_browser.fetch_html_sync, source_url)
                else:
                    logger.warning(
                        f"[{self.name}] 未安裝虛擬瀏覽器(nodriver)，改用 HTTP 抓取 ISO 頁面"
                        f"（可能被 Cloudflare 擋下）: {source_url}"
                    )
                    response = await self.get(source_url)
                    html = response.text
                info = self._parse_iso_page(html)
            else:
                response = await self.get(source_url)
                html = response.text
                if "iec.ch" in source_url:
                    info = self._parse_iec_page(html)
                else:
                    info = {}

            # 驗證抓回的標準編號是否與預期一致，避免 source_url 指向錯誤文件
            # (例如資料庫記錄為 ISO 2859-1，但 source_url 卻指向 ISO 11661 的頁面)
            # 注意：「公司文件編號」(standard_number) 為公司內部自訂編號，與 ISO/IEC
            # 官方編號無關，不可用於此比對，否則永遠找不到對應結果。
            # expected_base 僅從「法規名稱」(expected_title) 擷取；若其中找不到
            # ISO/IEC 編號格式，視為無法比對，不進行查核（避免誤判為網址錯誤
            # 而封鎖版本更新偵測）。
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

    def _split_title_version(self, title: str):
        """將「法規名稱:版本」格式的字串拆解為 (法規名稱, 版本)。

        ISO/IEC 標準的正式命名方式為「編號:年份」，例如 'ISO10993-1:2018'，
        其中「ISO10993-1」是法規名稱（編號），「2018」是版本。
        過去資料常將整串（含版本）存入「法規名稱」欄位，導致「目前使用版本」
        (current_version) 欄位空白，使新版本比對失效。

        例如：
          'ISO10993-1:2018' -> ('ISO 10993-1', '2018')
          'IEC 60601-1:2020' -> ('IEC 60601-1', '2020')

        若無法解析出「編號:年份」格式，回傳 (title 去除前後空白, '')。

        注意：「公司文件編號」(standard_number，例如 'R101-0004-01') 不適用此格式，
        不會被誤判（regex 要求以 ISO/IEC 開頭）。
        """
        if not title:
            return title, ""
        match = re.match(
            r"^\s*((?:ISO|IEC)(?:/(?:IEC|TR|TS))?\s*[\d]+(?:[-/]\d+)*)\s*[:：]\s*(\d{4}.*)$",
            title.strip(),
            re.IGNORECASE,
        )
        if match:
            base = re.sub(r"\s+", " ", match.group(1).strip())
            # 將「ISO10993-1」正規化為「ISO 10993-1」(編號前加空格)
            base = re.sub(r"^(ISO|IEC)(?=\d)", r"\1 ", base, flags=re.IGNORECASE)
            version = match.group(2).strip()
            return base, version
        return title.strip(), ""

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
            # 不更新版本資訊，避免產生誤導的「有更新」提示，僅記錄查核失敗並建立警示。
            # 注意：「分類」(notes) 不可寫入查核失敗訊息，否則會污染分類（產生
            # 「ISO ⚠️ 來源網址查核失敗…」這類假類別）；查核失敗僅以 alert 呈現。
            if latest_info.get("title_mismatch"):
                conn.execute("""
                    UPDATE standards SET
                        last_checked = ?,
                        updated_at = ?
                    WHERE id = ?
                """, (
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

            # 修正「法規名稱」與「目前使用版本」欄位混用的舊資料：
            # ISO/IEC 標準的「法規名稱」應只包含編號（例如「ISO 10993-4」），
            # 「目前使用版本」則為年份（例如「2017」）。
            # 若「法規名稱」(title) 仍是「ISO10993-4:2017」這類「編號:版本」
            # 格式，一律拆解並將法規名稱正規化為僅含編號；若「目前使用版本」
            # (current_version) 原本為空白，則同時補上拆解出的版本，
            # 避免版本比對因 current_version 空白而失效。
            title_for_db = row["title"] or ""
            current_version_for_db = row["current_version"] or ""
            split_title, split_version = self._split_title_version(title_for_db)
            if split_version:
                title_for_db = split_title
                if not current_version_for_db.strip():
                    current_version_for_db = split_version

            current_version = self._normalize_version(row["latest_version"] or current_version_for_db or "")
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
            elif is_new_edition:
                has_update = 1  # 已公告新版本（即使 current_version 尚為空白也視為有更新）
            elif new_version and current_version and new_version != current_version:
                has_update = 1  # 版本號有實質變化（含已發布新版本的情況）

            latest_version_value = latest_info.get("version") or row["latest_version"] or current_version_for_db
            if is_new_edition:
                latest_version_value = new_edition_year

            conn.execute("""
                UPDATE standards SET
                    title = ?,
                    current_version = ?,
                    latest_version = ?,
                    status = COALESCE(?, status),
                    has_update = ?,
                    last_checked = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                title_for_db,
                current_version_for_db,
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

    def _is_iso_standard(self, std: dict) -> bool:
        """判斷標準是否屬於 ISO 類別（虛擬瀏覽器搜尋目前僅支援 ISO）。
        以分類(notes)為主，並輔以法規名稱(title)是否以 ISO 開頭。"""
        notes = (std.get("notes") or "").strip()
        title = (std.get("title") or "").strip().upper()
        return notes == "ISO" or title.startswith("ISO")

    def _apply_browser_result(self, std: dict, result: dict) -> bool:
        """將虛擬瀏覽器搜尋結果回寫資料庫（官方網址、最新查找版本/日期、是否有更新），
        並於判定有更新時建立提醒。回傳是否有更新。"""
        now_iso = datetime.now().isoformat()
        has_update = 1 if result.get("has_update") else 0
        latest_version = result.get("now_year") or result.get("now_title") or ""

        conn = get_db()
        try:
            conn.execute("""
                UPDATE standards SET
                    source_url = ?,
                    latest_version = ?,
                    last_checked = ?,
                    has_update = ?,
                    status = COALESCE(?, status),
                    updated_at = ?
                WHERE id = ?
            """, (
                result.get("source_url") or std.get("source_url") or "",
                latest_version,
                now_iso,
                has_update,
                result.get("now_status") or None,
                now_iso,
                std["id"],
            ))
            conn.commit()
        finally:
            conn.close()

        if has_update:
            # 依「ISO 法規版本更新判定邏輯規則」的判定結果建立提醒
            label = result.get("judge_label", "📢 有更新")
            judge_msg = result.get("judge_message") or (
                f"目前版本 {std.get('current_version') or '未註記'} 與官網現行版 "
                f"{result.get('now_status')} {result.get('now_title')} 不同")
            self.create_alert(
                alert_type="standard_new_edition",
                title=f"{label}: {std['standard_number']} {std.get('title')}",
                message=f"{judge_msg}（文件類型: {result.get('doc_type', '?')}；來源: {result.get('source_url')}）",
                source="IEC/ISO",
                reference_id=std["id"],
                reference_table="standards",
            )
        return bool(has_update)

    async def _browser_search_batch(self, standards: list):
        """以『單一共用瀏覽器視窗』批量搜尋整批標準的 Life cycle（全程只開一次視窗）。
        回傳 (checked, updated, skipped)。目前僅支援 ISO 類別，其餘類別略過。"""
        import asyncio as _asyncio
        from crawlers import iso_browser

        # 篩出 ISO 標準（其餘略過），並建立批次清單
        iso_items = []
        std_by_key = {}
        skipped = 0
        for std in standards:
            if self._is_iso_standard(std):
                key = str(std["id"])
                std_by_key[key] = std
                iso_items.append({
                    "key": key,
                    "standard_name": std.get("title") or "",
                    "current_version": std.get("current_version") or "",
                })
            else:
                skipped += 1
                logger.info(f"[{self.name}] 略過（虛擬瀏覽器搜尋目前僅支援 ISO）: {std.get('standard_number')}")

        if not iso_items:
            return 0, 0, skipped
        if not iso_browser.BROWSER_AVAILABLE:
            logger.warning(f"[{self.name}] 未安裝虛擬瀏覽器(nodriver)，無法執行搜尋，略過 {len(iso_items)} 筆")
            return 0, 0, skipped + len(iso_items)

        # 共用單一瀏覽器視窗依序處理整批（全部完成後才關閉視窗）
        results = await _asyncio.to_thread(iso_browser.resolve_many_sync, iso_items)

        checked = 0
        updated = 0
        for key, std in std_by_key.items():
            result = results.get(key)
            checked += 1
            if not result or not result.get("ok"):
                logger.warning(
                    f"[{self.name}] {std.get('standard_number')} 搜尋無相符結果: "
                    f"{(result or {}).get('error', '無回傳')}"
                )
                continue
            if self._apply_browser_result(std, result):
                updated += 1
        return checked, updated, skipped

    async def run(self, historical: bool = False, product_ids: list = None, standard_id: int = None,
                  categories: list = None, mode: str = "routine", **kwargs):
        """執行標準版本檢查。

        categories: 法規分類(notes)過濾清單；None / 空 / 含 'all' 表示全部。
        mode: 'routine' 例行執行（讀取已設定的 source_url 判讀）；
              'browser' 啟動虛擬瀏覽器到官網搜尋（目前僅支援 ISO 類別）。
        """
        started_at = datetime.now().isoformat()
        log_id = self.start_crawl_log(started_at)
        total_checked = 0
        total_updated = 0

        # 正規化分類過濾：None / 空 / 含 'all' → 全部（cat_filter=None）
        cat_filter = None
        if categories:
            cats = [c for c in categories if c and c != "all"]
            if cats and "all" not in categories:
                cat_filter = cats

        conn = get_db()
        try:
            if standard_id:
                rows = conn.execute("SELECT * FROM standards WHERE id = ?", (standard_id,)).fetchall()
            elif cat_filter:
                placeholders = ",".join("?" * len(cat_filter))
                rows = conn.execute(
                    f"SELECT * FROM standards WHERE notes IN ({placeholders})", tuple(cat_filter)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM standards").fetchall()
            standards = [dict(row) for row in rows]
        finally:
            conn.close()

        if not standards:
            # 僅在「全庫」為空時初始化預設清單；分類過濾後為空則直接結束
            if not standard_id and not cat_filter:
                logger.info(f"[{self.name}] 無追蹤的標準，初始化預設清單")
                self.init_default_standards()
            self.finish_crawl_log(log_id, "success", 0, 0)
            return {"checked": 0, "updated": 0}

        logger.info(f"[{self.name}] 開始檢查 {len(standards)} 個標準 (mode={mode}, 分類={cat_filter or '全部'})")

        # 虛擬瀏覽器搜尋模式：整批共用『單一瀏覽器視窗』，全部完成後才關閉
        if mode == "browser":
            try:
                total_checked, total_updated, skipped = await self._browser_search_batch(standards)
                self.finish_crawl_log(log_id, "success", total_checked, total_updated)
                logger.info(f"[{self.name}] 虛擬瀏覽器搜尋完成: 檢查 {total_checked}，更新 {total_updated}，略過 {skipped}")
                return {"checked": total_checked, "updated": total_updated, "skipped": skipped}
            except Exception as e:
                self.finish_crawl_log(log_id, "error", total_checked, total_updated, str(e))
                raise

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
