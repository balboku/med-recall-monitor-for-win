"""IEC/ISO 標準版本追蹤爬蟲"""
import re
import logging
from datetime import datetime
from crawlers.base import BaseCrawler
from crawlers.html_parser import parse_html
from database import get_db
import standards_progress

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
        """檢查單一標準的最新版本。

        注意：iso.org 與 iec.ch 來源都已改走與『虛擬瀏覽器搜尋』模式相同的判定管線
        （ISO → _resolve_iso_lifecycle()；IEC → iec_api 的 edition 判定），
        process_group 不會再對這兩個網域呼叫本函式；這裡保留 iso.org 分支僅作為
        虛擬瀏覽器不可用時的 HTTP 直接嘗試 fallback（雖多半會被 Cloudflare 擋下，
        但至少行為與過去一致），iec.ch 分支則保留給未預先查得結果的例外情況。
        """
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

    def _resolve_iso_lifecycle(self, standard_number: str, source_url: str, expected_title: str,
                               current_version: str, html: str) -> dict:
        """例行模式的 ISO 標準專用管線：直接使用（批次）預先取得的 Life cycle 頁面 HTML，
        走與『虛擬瀏覽器搜尋』模式完全相同的判定邏輯（parse_lifecycle + judge_update），
        回傳格式與 iso_browser._build_result() 一致，可直接交給 _apply_browser_result() 回寫。

        這是必要的：舊版 _check_standard()/_update_standard() 只比對版本號差異，
        完全不會判斷「缺少主標準／缺少 AMD、COR、ADD 等附屬文件」，
        而例行模式（'routine'）是預設的例行執行模式，若沿用舊管線，
        缺件判定就永遠不會在日常掃描中出現。
        """
        from crawlers.iso_browser import parse_lifecycle
        from crawlers.standards_common import (
            judge_update, collect_db_docs, detect_doc_type, compose_now_version,
        )

        if not html:
            logger.warning(
                f"[{self.name}] {standard_number} 批次預先擷取 HTML 失敗"
                f"（可能被 Cloudflare 擋下或逾時），略過本次檢查: {source_url}"
            )
            return {"ok": False, "error": "批次預先擷取 HTML 失敗"}

        parsed = self._parse_iso_page(html)

        # 驗證抓回的標準編號是否與預期一致，避免 source_url 指向錯誤文件（與 _check_standard 相同邏輯）
        expected_base = self._extract_base_number(expected_title)
        found_base = self._extract_base_number(parsed.get("full_title", ""))
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
                "ok": False,
                "title_mismatch": True,
                "expected_title": expected_title,
                "found_title": parsed.get("full_title", ""),
            }

        lc = parse_lifecycle(html)
        db_docs = collect_db_docs(expected_title or standard_number)
        verdict = judge_update(expected_title or standard_number, current_version, lc, db_docs)

        now_title = lc["now_title"] or parsed.get("full_title", "")
        # 「最新同步版本」顯示現行家族的完整版本（主標準＋現行附屬文件），例如 '2019+Amd 1:2022'
        doc_type = detect_doc_type(
            f"{expected_title}:{current_version}" if current_version else expected_title
        )
        # 「最新同步版本」須與該筆文件同類型比對：主標準對主標準、附屬文件對附屬文件
        now_year = compose_now_version(lc, doc_type)
        if not now_year:
            now_year_m = re.search(r":(\d{4})", now_title)
            now_year = now_year_m.group(1) if now_year_m else parsed.get("version_year", "")

        return {
            "ok": True,
            "source_url": source_url,
            "found_title": parsed.get("full_title", ""),
            "now_status": lc["now_status"] or parsed.get("status", ""),
            "now_title": now_title,
            "now_year": now_year,
            "doc_type": doc_type,
            "judge_statuses": verdict["judge_statuses"],
            "judge_categories": verdict["judge_categories"],
            "judge_status": verdict["judge_status"],
            "judge_label": verdict["judge_label"],
            "judge_message": verdict["judge_message"],
            "now_main": verdict["now_main"],
            "missing_types": verdict.get("missing_types", []),
            "missing_supplements": verdict.get("missing_supplements", []),
            "has_update": verdict["has_update"],
        }

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
                    judge_label = ?,
                    last_checked = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                title_for_db,
                current_version_for_db,
                latest_version_value,
                status_str or None,
                has_update,
                "🟢 無更新" if has_update == 0 else ("⚠️ 修訂中" if has_update == 2 else "📢 有更新"),
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

    def _cleanup_polluted_categories(self):
        """自我修復：移除任何被舊機制污染到「分類(notes)」的『來源網址查核失敗』訊息，
        確保 ISO/IEC 分類維持乾淨（即使先前由舊版程式或殘留資料造成）。每次掃描開始時呼叫。"""
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT id, title, notes FROM standards WHERE notes LIKE '%查核失敗%'"
            ).fetchall()
            n = 0
            for row in rows:
                notes = row["notes"] or ""
                cleaned = re.sub(r"\s*⚠.*source_url\s*$", "", notes).strip()
                if not cleaned:
                    t = (row["title"] or "").strip().upper()
                    cleaned = "ISO" if t.startswith("ISO") else ("IEC" if t.startswith("IEC") else "")
                if cleaned != notes:
                    conn.execute("UPDATE standards SET notes = ? WHERE id = ?", (cleaned, row["id"]))
                    n += 1
            if n:
                conn.commit()
                logger.info(f"[{self.name}] 已清理 {n} 筆被污染的分類(notes)，還原為 ISO/IEC")
        finally:
            conn.close()

    def _is_iso_standard(self, std: dict) -> bool:
        """判斷標準是否屬於 ISO 類別。
        以「類別」欄位(category)為主，相容舊資料的分類(notes)，並輔以法規名稱(title)是否以 ISO 開頭。"""
        return self._standard_source(std) == "ISO"

    def _standard_source(self, std: dict):
        """判斷此標準應以哪個官網來源查找：'ISO'、'IEC'、'EN'、'EU'、'MDCG'、'TW'、'FDA'、'ASTM'、'OTHER' 或 None。

        ISO 走 iso_browser（官網受 Cloudflare 防護，需虛擬瀏覽器）；
        IEC 走 iec_api（webstore 搜尋 API，純 HTTP 即可，速度快很多）；
        EN / BS EN 走 en_harmonised（歐盟協調標準官方公報清單）。
        以「類別」欄位(category)為主，相容舊資料的分類(notes)，並輔以法規名稱(title)前綴。
        """
        category = (std.get("category") or "").strip().upper()
        notes = (std.get("notes") or "").strip().upper()
        title = (std.get("title") or "").strip().upper()

        # EU 法規／指引：僅以「類別」判斷，不以名稱推斷 ——
        # 指引文件標題常引用法規編號，靠名稱猜會與其他類別互相誤判。
        if category.startswith("TAIWAN TFDA") or notes.startswith("TAIWAN TFDA"):
            return "TW"
        if category.startswith("FDA") or notes.startswith("FDA"):
            return "FDA"
        if "ASTM" in category or "AAMI" in category or title.startswith(("ASTM", "AAMI", "ANSI/AAMI")):
            return "ASTM"
        if "INTERNATIONAL / OTHER" in (category, notes):
            return "OTHER"
        if "MDCG GUIDANCE" in (category, notes):
            return "MDCG"
        if "EU REGULATION" in (category, notes):
            return "EU"
        # EN 需優先於 ISO 判斷：'EN ISO 13485' 同時含 EN 與 ISO，但應走協調標準清單
        if title.startswith(("EN ", "BS EN ")) or "EN" in (category, notes) or \
                category in ("EN ISO / EN", "BS EN"):
            return "EN"
        for src in ("ISO", "IEC"):
            if category == src or notes == src or title.startswith(src):
                return src
        return None

    def _apply_browser_result(self, std: dict, result: dict) -> bool:
        """將虛擬瀏覽器搜尋結果回寫資料庫（官方網址、最新查找版本/日期、是否有更新），
        並於判定有更新時建立提醒。回傳是否有更新。"""
        now_iso = datetime.now().isoformat()
        # 「查無結果」不是「有更新」：官網根本沒查到這個標準，沒有任何新版本可言。
        # has_update 會被 Dashboard／Analytics 以 has_update > 0 統計為「有更新的標準數」，
        # 若把查無結果也算進去，等於謊報查到了新版本。改以 judge_categories 區分，
        # 但仍然要建立提醒（可能已作廢需人工確認），故提醒條件另外納入 is_not_found。
        is_not_found = "not_found" in (result.get("judge_categories") or [])
        has_update = 0 if is_not_found else (1 if result.get("has_update") else 0)
        # 查無結果(情境一)時官網無現行版本資訊，保留原有 latest_version 不覆蓋為空
        latest_version = (
            result.get("now_year") or result.get("now_title") or std.get("latest_version") or ""
        )

        conn = get_db()
        try:
            conn.execute("""
                UPDATE standards SET
                    source_url = ?,
                    latest_version = ?,
                    last_checked = ?,
                    has_update = ?,
                    judge_label = ?,
                    judge_categories = ?,
                    status = COALESCE(?, status),
                    updated_at = ?
                WHERE id = ?
            """, (
                result.get("source_url") or std.get("source_url") or "",
                latest_version,
                now_iso,
                has_update,
                result.get("judge_label") or "",
                ",".join(result.get("judge_categories") or []),
                result.get("now_status") or None,
                now_iso,
                std["id"],
            ))
            conn.commit()
        finally:
            conn.close()

        if has_update or is_not_found:
            # 依「ISO 法規版本更新判定邏輯規則」的判定結果建立提醒。
            # 查無結果雖然不計入 has_update，仍需提醒文管人員人工確認是否已作廢。
            label = result.get("judge_label", "📢 有更新")
            judge_msg = result.get("judge_message") or (
                f"目前版本 {std.get('current_version') or '未註記'} 與官網現行版 "
                f"{result.get('now_status')} {result.get('now_title')} 不同")
            self.create_alert(
                alert_type="standard_not_found" if is_not_found else "standard_new_edition",
                title=f"{label}: {std['standard_number']} {std.get('title')}",
                message=f"{judge_msg}（文件類型: {result.get('doc_type', '?')}；來源: {result.get('source_url')}）",
                source="IEC/ISO",
                reference_id=std["id"],
                reference_table="standards",
            )
        return bool(has_update)

    async def _browser_search_batch(self, standards: list):
        """批量到官網搜尋整批標準的生命週期並回寫判定結果。
        回傳 (checked, updated, skipped)。

        依類別分派來源：
          ISO → iso_browser（官網受 Cloudflare 防護，整批共用『單一瀏覽器視窗』）
          IEC → iec_api（webstore 搜尋 API，純 HTTP，共用單一連線）
          EN  → en_harmonised（歐盟協調標準官方公報清單，整批只下載一次）
          EU  → eu_regulation（EUR-Lex 合併版 + 執委會指引清單）
          MDCG→ mdcg_guidance（執委會 MDCG 指引清單，比對修訂版次）
          TW  → tw_regulation（全國法規資料庫，比對最後修正日期）
          FDA → fda_docs（FDA 指引資料集 + eCFR）
          ASTM→ astm_aami（astm.org 短代號轉址取現行版；AAMI 受 Cloudflare 阻擋）
          OTHER→ other_docs（知識型分類，非爬蟲；來源皆無公開版本清單）
        其餘類別目前尚未支援，略過。
        """
        import asyncio as _asyncio
        from crawlers import (iso_browser, iec_api, en_harmonised,
                              eu_regulation, mdcg_guidance, tw_regulation,
                              fda_docs, astm_aami, other_docs)

        # 依來源分組，其餘略過
        iso_items, iec_items, en_items = [], [], []
        eu_items, mdcg_items, tw_items = [], [], []
        fda_items, astm_items, other_items = [], [], []
        std_by_key = {}
        skipped = 0
        for std in standards:
            source = self._standard_source(std)
            if source is None:
                skipped += 1
                standards_progress.advance(skipped=True)
                logger.info(f"[{self.name}] 略過（官網搜尋目前僅支援 ISO / IEC / EN / EU / MDCG / 台灣法規 / FDA / ASTM）: {std.get('standard_number')}")
                continue
            key = str(std["id"])
            std_by_key[key] = std
            item = {
                "key": key,
                "standard_name": std.get("title") or "",
                "current_version": std.get("current_version") or "",
            }
            {"ISO": iso_items, "IEC": iec_items, "EN": en_items, "EU": eu_items,
             "MDCG": mdcg_items, "TW": tw_items, "FDA": fda_items,
             "ASTM": astm_items, "OTHER": other_items}[source].append(item)

        if not any((iso_items, iec_items, en_items, eu_items, mdcg_items,
                    tw_items, fda_items, astm_items, other_items)):
            return 0, 0, skipped
        if iso_items and not iso_browser.BROWSER_AVAILABLE:
            logger.warning(f"[{self.name}] 未安裝虛擬瀏覽器(nodriver)，ISO 無法執行搜尋，略過 {len(iso_items)} 筆")
            for _ in iso_items:
                standards_progress.advance(skipped=True)
            skipped += len(iso_items)
            iso_items = []

        # 每處理完一筆即回寫資料庫並更新進度
        counters = {"checked": 0, "updated": 0}

        def on_item(key, item, result):
            std = std_by_key.get(key)
            if std is None:
                return
            standards_progress.set_current_title(std.get("title") or "")
            counters["checked"] += 1
            updated = False
            if result.get("ok"):
                updated = self._apply_browser_result(std, result)
            else:
                # ok=False：技術性錯誤（如 Cloudflare 擋下）。
                # 回寫「查找失敗」標籤至資料庫並更新 last_checked，
                # 避免出現「查找失敗: ...」訊息卻未寫回的情況。
                err_msg = result.get("error", "無回傳")
                logger.warning(
                    f"[{self.name}] {std.get('standard_number')} 搜尋發生技術錯誤: "
                    f"{err_msg}"
                )
                _now = datetime.now().isoformat()
                _conn = get_db()
                try:
                    _conn.execute("""
                        UPDATE standards SET
                            last_checked = ?,
                            judge_label = ?,
                            updated_at = ?
                        WHERE id = ?
                    """, (_now, "查找失敗", _now, std["id"]))
                    _conn.commit()
                finally:
                    _conn.close()
            if updated:
                counters["updated"] += 1
            standards_progress.advance(updated=updated)

        # IEC 為純 HTTP，可直接在目前事件迴圈執行；
        # ISO 需啟動 Chrome 子程序，必須在獨立工作執行緒以全新事件迴圈執行（見 iso_browser 說明）。
        if iec_items:
            logger.info(f"[{self.name}] IEC webstore 搜尋 {len(iec_items)} 筆")
            await iec_api.resolve_many(iec_items, on_item)
        if en_items:
            logger.info(f"[{self.name}] EN 歐盟協調標準清單比對 {len(en_items)} 筆")
            await en_harmonised.resolve_many(en_items, on_item)
        if eu_items:
            logger.info(f"[{self.name}] EU 法規／指引查詢 {len(eu_items)} 筆")
            await eu_regulation.resolve_many(eu_items, on_item)
        if mdcg_items:
            logger.info(f"[{self.name}] MDCG 指引清單比對 {len(mdcg_items)} 筆")
            await mdcg_guidance.resolve_many(mdcg_items, on_item)
        if fda_items:
            logger.info(f"[{self.name}] FDA 指引／CFR 查詢 {len(fda_items)} 筆")
            await fda_docs.resolve_many(fda_items, on_item)
        if astm_items:
            logger.info(f"[{self.name}] ASTM／AAMI 查詢 {len(astm_items)} 筆")
            await astm_aami.resolve_many(astm_items, on_item)
        if other_items:
            logger.info(f"[{self.name}] 其他國際文件分類 {len(other_items)} 筆")
            await other_docs.resolve_many(other_items, on_item)
        if tw_items:
            logger.info(f"[{self.name}] 台灣法規查詢 {len(tw_items)} 筆（政府網站需放慢請求）")
            await tw_regulation.resolve_many(tw_items, on_item)
        if iso_items:
            logger.info(f"[{self.name}] ISO 虛擬瀏覽器搜尋 {len(iso_items)} 筆")
            await _asyncio.to_thread(iso_browser.resolve_many_sync, iso_items, on_item)
        return counters["checked"], counters["updated"], skipped

    async def run(self, historical: bool = False, product_ids: list = None, standard_id: int = None,
                  categories: list = None, mode: str = "routine", **kwargs):
        """執行標準版本檢查。

        categories: 法規分類(category 類別欄位)過濾清單；None / 空 / 含 'all' 表示全部。
        mode: 'routine' 例行執行（讀取已設定的 source_url 判讀）；
              'browser' 啟動虛擬瀏覽器到官網搜尋（目前僅支援 ISO 類別）。
        """
        started_at = datetime.now().isoformat()
        log_id = self.start_crawl_log(started_at)
        total_checked = 0
        total_updated = 0

        # 自我修復：每次掃描開始先清理任何被污染的分類（避免殘留或舊程式造成的假類別）
        self._cleanup_polluted_categories()

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
                    f"SELECT * FROM standards WHERE category IN ({placeholders})", tuple(cat_filter)
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

        # 啟動即時進度：browser 模式每筆都會推進；routine 僅處理有 source_url 者
        if mode == "browser":
            progress_total = len(standards)
        else:
            progress_total = sum(1 for s in standards if s.get("source_url"))
        standards_progress.start(progress_total, mode)

        # 虛擬瀏覽器搜尋模式：整批共用『單一瀏覽器視窗』，全部完成後才關閉
        if mode == "browser":
            try:
                total_checked, total_updated, skipped = await self._browser_search_batch(standards)
                self.finish_crawl_log(log_id, "success", total_checked, total_updated)
                standards_progress.finish("success",
                    f"完成：檢查 {total_checked}，更新 {total_updated}，略過 {skipped}")
                logger.info(f"[{self.name}] 虛擬瀏覽器搜尋完成: 檢查 {total_checked}，更新 {total_updated}，略過 {skipped}")
                return {"checked": total_checked, "updated": total_updated, "skipped": skipped}
            except Exception as e:
                self.finish_crawl_log(log_id, "error", total_checked, total_updated, str(e))
                standards_progress.finish("error", str(e))
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

            # ISO 官網（iso.org）受 Cloudflare 防護，須以虛擬瀏覽器逐頁開啟。
            # 為避免例行模式對整批 ISO 標準各自開關一次瀏覽器視窗（大量掃描時視窗會不斷
            # 跳出干擾操作），這裡先以『單一瀏覽器視窗』一次取得整批 HTML，
            # process_group 內解析 ISO 標準時一律使用預先擷取的結果，不再另行開啟瀏覽器。
            iso_html_by_id = {}
            iso_domains = [d for d in domain_groups if "iso.org" in d]
            # 僅在虛擬瀏覽器可用且確實跑過批次預先擷取時，process_group 才改用預先擷取結果；
            # 若未安裝 nodriver，維持原本逐筆 fallback（走 HTTP 嘗試）的行為，不受此次調整影響。
            iso_batch_ready = False
            if iso_domains:
                from crawlers import iso_browser
                if iso_browser.BROWSER_AVAILABLE:
                    iso_batch_ready = True
                    iso_stds = [s for d in iso_domains for s in domain_groups[d]]
                    id_by_url = defaultdict(list)
                    for s in iso_stds:
                        id_by_url[s["source_url"]].append(s["id"])
                    logger.info(f"[{self.name}] 以單一瀏覽器視窗批次取得 {len(id_by_url)} 個 ISO 官網頁面")
                    html_by_url = await asyncio.to_thread(
                        iso_browser.fetch_many_sync, list(id_by_url.keys())
                    )
                    for url, html in html_by_url.items():
                        for sid in id_by_url.get(url, []):
                            iso_html_by_id[sid] = html

            # IEC（webstore.iec.ch）同樣必須走與『虛擬瀏覽器搜尋』模式相同的判定管線
            # （iec_api 的 edition 版本判定 + judge_update_iec），否則例行模式會沿用舊的
            # _check_standard()/_update_standard()：只比對版本號、不寫入 judge_label／
            # judge_categories，「缺少附屬文件／修訂中」等判定在日常掃描中永遠不會出現，
            # 且畫面上的狀態會停留在舊管線寫下的過時字串。
            # IEC 為純 HTTP 搜尋 API，整批共用同一個連線先行查完，再逐筆回寫。
            iec_result_by_id = {}
            iec_domains = [d for d in domain_groups if "iec.ch" in d]
            if iec_domains:
                from crawlers import iec_api
                iec_stds = [s for d in iec_domains for s in domain_groups[d]]
                logger.info(f"[{self.name}] 以 IEC webstore 搜尋 API 查詢 {len(iec_stds)} 筆 IEC 標準")
                iec_result_by_id = await iec_api.resolve_many([
                    {
                        "key": s["id"],
                        "standard_name": s.get("title") or s["standard_number"],
                        "current_version": s.get("current_version") or "",
                    }
                    for s in iec_stds
                ])

            def touch_last_checked(std_id):
                """僅記錄本次檢查時間，不覆蓋既有判定結果（抓取失敗或網址不符時使用）。"""
                now_iso2 = datetime.now().isoformat()
                _conn = get_db()
                try:
                    _conn.execute(
                        "UPDATE standards SET last_checked = ?, updated_at = ? WHERE id = ?",
                        (now_iso2, now_iso2, std_id),
                    )
                    _conn.commit()
                finally:
                    _conn.close()

            async def process_group(domain, stds):
                grp_checked = 0
                grp_updated = 0
                is_iso_domain = "iso.org" in domain and iso_batch_ready
                is_iec_domain = "iec.ch" in domain and bool(iec_result_by_id)
                for std in stds:
                    standards_progress.set_current_title(std.get("title") or std.get("standard_number") or "")
                    grp_checked += 1
                    updated = False

                    if is_iso_domain:
                        # ISO：走與『虛擬瀏覽器搜尋』模式相同的 Life cycle 判定管線
                        # （parse_lifecycle + judge_update），才能正確判定「缺少主標準／
                        # 附屬文件」；直接沿用 _apply_browser_result() 回寫，與 browser 模式一致。
                        result = self._resolve_iso_lifecycle(
                            std["standard_number"], std["source_url"], std.get("title", ""),
                            std.get("current_version") or "", iso_html_by_id.get(std["id"]),
                        )
                        if result.get("title_mismatch"):
                            touch_last_checked(std["id"])
                            self.create_alert(
                                alert_type="standard_url_mismatch",
                                title=f"⚠️ 標準來源網址不符: {std['standard_number']}",
                                message=(
                                    f"預期文件「{result.get('expected_title', std.get('title'))}」，"
                                    f"但 source_url 查到的是「{result.get('found_title', '')}」，"
                                    f"目前網址: {std['source_url']}，請至追蹤設定修正來源網址。"
                                ),
                                source="IEC/ISO",
                                reference_id=std["id"],
                                reference_table="standards",
                            )
                        elif result.get("ok"):
                            updated = self._apply_browser_result(std, result)
                        else:
                            # 批次預先擷取失敗：僅記錄檢查時間，不覆蓋既有判定結果
                            touch_last_checked(std["id"])
                    elif is_iec_domain:
                        # IEC：走與『虛擬瀏覽器搜尋』模式相同的 edition 判定管線
                        # （iec_api.judge_update_iec），並沿用 _apply_browser_result() 回寫，
                        # 才會一併寫入 judge_label / judge_categories（通用規則第 6 節）。
                        result = iec_result_by_id.get(std["id"]) or {}
                        if result.get("ok"):
                            updated = self._apply_browser_result(std, result)
                        else:
                            logger.warning(
                                f"[{self.name}] {std['standard_number']} IEC 官網查找失敗，"
                                f"略過本次判定: {result.get('error') or '無回傳結果'}"
                            )
                            touch_last_checked(std["id"])
                    else:
                        latest_info = await self._check_standard(
                            std["standard_number"], std["source_url"], std.get("title", "")
                        )
                        if latest_info:
                            updated = self._update_standard(std["id"], latest_info)
                            if updated:
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

                    if updated:
                        grp_updated += 1
                    standards_progress.advance(updated=updated)
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
            standards_progress.finish("success", f"完成：檢查 {total_checked}，更新 {total_updated}")
            logger.info(f"[{self.name}] 完成: 檢查 {total_checked} 個，更新 {total_updated} 個")
            return {"checked": total_checked, "updated": total_updated}
        except Exception as e:
            self.finish_crawl_log(log_id, "error", total_checked, total_updated, str(e))
            standards_progress.finish("error", str(e))
            raise
