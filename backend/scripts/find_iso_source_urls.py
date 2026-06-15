"""
ISO 標準官方網址年度查找腳本
================================

用途：
    針對資料庫 standards 表中「法規名稱」為 ISO/IEC 標準、但缺少（或需要重新核對）
    「官方來源網址」(source_url) 的項目，使用 Google Custom Search JSON API
    搜尋 ISO 官網（www.iso.org）上對應的標準目錄頁面，依下列三條規則判定後回填 source_url：

    1. 搜尋結果中標準編號（法規名稱）與資料庫不符者，直接捨棄。
       例：搜尋「ISO 11737-1」，結果為「ISO 6876:2025」→ 不計。

    2. 搜尋結果版本（含 Amd/Cor 修正案）與資料庫「目前使用版本」(current_version)
       完全相符者 → 判定「無更新」，並將該結果頁面網址回填至 source_url。
       例：「ISO 11737-1:2018/Amd 1:2021」與 current_version「2018+Amd 1:2021」相符
           → 回填 https://www.iso.org/standard/76751.html

    3. 搜尋結果編號相符但版本不同（例如 current_version 為含 Amd 的版本，
       搜尋結果卻是未含 Amd 的基礎版本）→ 不適用，不計入回填，僅列出供人工確認。
       例：「ISO 11737-1:2018」（不含 Amd）與 current_version「2018+Amd 1:2021」
           不符 → 不計。

事前準備：
    1. 到 https://programmablesearchengine.google.com/ 建立一個搜尋引擎，
       「搜尋整個網路」開啟、並可設定僅搜尋 iso.org（建議），取得搜尋引擎 ID（cx）。
    2. 到 Google Cloud Console 啟用「Custom Search API」，取得 API Key。
    3. 於系統設定頁面（系統控制中心）輸入並儲存上述 API Key 與搜尋引擎 ID（cx）。

    Google Custom Search API 免費額度為每天 100 次查詢，足夠「一年一次」使用；
    若待查找項目超過 100 筆，腳本會在額度用盡時自動停止並回報進度，
    隔天額度重置後重新執行即可自動接續處理剩餘項目。

使用方式：
    於 backend 目錄下執行：
        python scripts/find_iso_source_urls.py
    預設只處理「source_url 為空」的 ISO/IEC 標準。
    加上 --all 參數則重新核對所有 ISO/IEC 標準（包含已有 source_url 者）。
    加上 --dry-run 參數則僅顯示結果，不寫入資料庫。

    本腳本為「一年一次、手動執行」工具，不納入排程。執行後仍由現有的
    每月標準版本偵測機制（StandardsCrawler）持續監控已回填網址的版本變化；
    若回填的網址與標準編號不符，該機制會建立「⚠️ 標準來源網址不符」警示，
    可作為本腳本誤判時的安全網。
"""
import asyncio
import argparse
import re
import sys
from pathlib import Path

# 讓腳本可在 backend 目錄外執行：將 backend 目錄加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from database import get_db
from config import REQUEST_HEADERS
from crawlers.standards import StandardsCrawler

GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"

# 每次查詢之間的間隔秒數，避免短時間內過於密集呼叫 API
SEARCH_INTERVAL = 1

# 讀取候選頁面內容時的逾時秒數
RESOLVE_TIMEOUT = 15

ISO_STANDARD_URL_PATTERN = re.compile(r"https://www\.iso\.org/standard/\d+\.html")


def normalize_version_loose(version: str) -> str:
    """版本字串寬鬆正規化：移除所有非英數字元並轉小寫，
    用於比對「2018+Amd 1:2021」與「2018/Amd 1:2021」等格式差異。"""
    return re.sub(r"[^a-z0-9]", "", (version or "").lower())


def get_google_search_config():
    """從系統設定讀取 Google Custom Search API Key 與搜尋引擎 ID (cx)"""
    conn = get_db()
    try:
        api_key_row = conn.execute(
            "SELECT value FROM system_settings WHERE key = 'google_search_api_key'"
        ).fetchone()
        cx_row = conn.execute(
            "SELECT value FROM system_settings WHERE key = 'google_search_cx'"
        ).fetchone()
        api_key = (api_key_row["value"] if api_key_row else "").strip()
        cx = (cx_row["value"] if cx_row else "").strip()
        return api_key, cx
    finally:
        conn.close()


class DailyQuotaExceeded(Exception):
    """Google Custom Search API 每日免費額度已用盡（需等隔天額度重置後再執行）"""


async def google_custom_search(api_key: str, cx: str, query: str) -> list:
    """呼叫 Google Custom Search JSON API，回傳搜尋結果中
    「/standard/數字.html」格式的 iso.org 網址清單"""
    params = {
        "key": api_key,
        "cx": cx,
        "q": f"site:iso.org {query}",
        "num": 10,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(GOOGLE_CSE_URL, params=params)

    if resp.status_code in (403, 429):
        body = resp.text.lower()
        if "quota" in body or "rate limit" in body:
            print(f"     [debug] 額度錯誤回應內容: {resp.text}")
            raise DailyQuotaExceeded(resp.text)

    if resp.status_code >= 400:
        print(f"     [debug] 錯誤回應內容: {resp.text}")
    resp.raise_for_status()
    data = resp.json()

    uris = []
    for item in data.get("items", []) or []:
        link = item.get("link", "") or ""
        cleaned = link.split("?")[0].split("#")[0]
        m = ISO_STANDARD_URL_PATTERN.match(cleaned)
        if m and m.group(0) not in uris:
            uris.append(m.group(0))
    return uris


async def fetch_iso_page(url: str):
    """以一般 HTTP 請求取得 ISO 標準頁面內容"""
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=RESOLVE_TIMEOUT, headers=REQUEST_HEADERS
    ) as client:
        try:
            resp = await client.get(url)
        except httpx.HTTPError as e:
            print(f"     [debug] 讀取失敗: {type(e).__name__}: {e}")
            return None
        final_url = str(resp.url)
        if resp.status_code >= 400:
            print(f"     [debug] 狀態碼錯誤: {final_url} (status={resp.status_code})")
            return None
        return final_url, resp.text


async def process_standard(crawler: StandardsCrawler, api_key: str, cx: str, std: dict, dry_run: bool):
    standard_number = std["standard_number"]
    title = std["title"] or ""
    current_version = (std["current_version"] or "").strip()

    expected_base = crawler._normalize_base_number(crawler._extract_base_number(title))
    query = crawler._extract_base_number(title) or title

    print(f"\n=== {standard_number} | {title} (目前版本: {current_version or '未知'}) ===")
    print(f"     搜尋關鍵字: {query}")

    try:
        uris = await google_custom_search(api_key, cx, query)
    except DailyQuotaExceeded:
        raise
    except Exception as e:
        print(f"  ❌ 搜尋失敗: {type(e).__name__}: {e}")
        return

    if not uris:
        print("  ❌ 無搜尋結果")
        return

    target_version_loose = normalize_version_loose(current_version)

    matched = None
    candidates = []
    seen_urls = set()
    debug_lines = []

    # 平行讀取所有候選網址的頁面內容
    results = await asyncio.gather(
        *(fetch_iso_page(uri) for uri in uris), return_exceptions=True
    )

    for uri, result in zip(uris, results):
        if isinstance(result, Exception):
            debug_lines.append(f"     [debug] 讀取發生例外: {uri} -> {type(result).__name__}: {result}")
            continue
        if not result:
            debug_lines.append(f"     [debug] 無法讀取: {uri}")
            continue
        final_url, html = result
        if final_url in seen_urls:
            continue
        seen_urls.add(final_url)

        info = crawler._parse_iso_page(html)
        full_title = info.get("full_title", "")
        found_base = crawler._normalize_base_number(crawler._extract_base_number(full_title))

        # 規則 1：標準編號不符 → 捨棄
        if not expected_base or not found_base or found_base != expected_base:
            debug_lines.append(
                f"     [debug] {final_url} -> full_title='{full_title}' "
                f"found_base='{found_base}' expected_base='{expected_base}'"
            )
            continue

        version = info.get("version_year", "")
        candidates.append((final_url, full_title, version))

        # 規則 2：版本與目前使用版本完全相符 → 判定無更新，回填網址
        if target_version_loose and normalize_version_loose(version) == target_version_loose:
            matched = (final_url, full_title, version)

    if matched:
        final_url, full_title, version = matched
        print(f"  ✅ 版本相符（{full_title}），判定無更新")
        if std["source_url"] == final_url:
            print(f"     官方來源網址已正確: {final_url}")
        else:
            print(f"     → 回填官方來源網址: {final_url}")
            if not dry_run:
                conn = get_db()
                try:
                    conn.execute(
                        "UPDATE standards SET source_url = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (final_url, std["id"]),
                    )
                    conn.commit()
                finally:
                    conn.close()
    elif candidates:
        # 規則 3：編號相符但版本不同 → 不計入回填，僅列出供人工確認
        print("  ⚠️ 找到相符編號但版本不同的頁面，請人工確認（可能為新版本或舊版本):")
        for url, full_title, version in candidates:
            print(f"     - {full_title}  [{url}]")
    else:
        print(f"  ❌ 找不到編號與「{title}」相符的 ISO 官方頁面")
        print(f"     [debug] 搜尋結果共 {len(uris)} 個網址: {uris}")
        for line in debug_lines:
            print(line)


async def main():
    parser = argparse.ArgumentParser(description="ISO 標準官方網址年度查找腳本")
    parser.add_argument(
        "--all", action="store_true",
        help="重新核對所有 ISO/IEC 標準（預設僅處理 source_url 為空者）"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="僅顯示查找結果，不寫入資料庫"
    )
    args = parser.parse_args()

    api_key, cx = get_google_search_config()
    if not api_key or not cx:
        print("❌ 尚未設定 Google Custom Search API Key 與搜尋引擎 ID (cx)，請至「系統設定 > 系統控制中心」輸入後再執行。")
        return

    conn = get_db()
    try:
        sql = "SELECT * FROM standards WHERE (title LIKE 'ISO%' OR title LIKE 'IEC%')"
        if not args.all:
            sql += " AND (source_url IS NULL OR source_url = '')"
        standards = [dict(row) for row in conn.execute(sql).fetchall()]
    finally:
        conn.close()

    if not standards:
        print("沒有需要處理的 ISO/IEC 標準（皆已設定官方來源網址，可加 --all 重新核對）。")
        return

    print(f"共 {len(standards)} 筆待查找{'（含已有網址者，--all 模式）' if args.all else ''}{'，dry-run 模式不會寫入資料庫' if args.dry_run else ''}")

    crawler = StandardsCrawler()
    quota_hit = False
    processed = 0
    try:
        for i, std in enumerate(standards):
            if i > 0:
                await asyncio.sleep(SEARCH_INTERVAL)
            try:
                await process_standard(crawler, api_key, cx, std, args.dry_run)
                processed += 1
            except DailyQuotaExceeded:
                quota_hit = True
                break
    finally:
        await crawler.close()

    if quota_hit:
        print(f"\n⚠️ Google Custom Search API 每日免費額度已用盡，本次共處理 {processed} 筆（共 {len(standards)} 筆待查找）。")
        print("已處理的項目不會重複查找；請等隔天額度重置（太平洋時間午夜重置）後再次執行本腳本，"
              "會自動接續處理剩餘項目。")
    else:
        print(f"\n完成，共處理 {processed} 筆。")


if __name__ == "__main__":
    asyncio.run(main())
