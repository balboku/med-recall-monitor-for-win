"""ISO 官網 Life cycle 存取（純 HTTP 優先，虛擬瀏覽器為後備）。

背景：
    www.iso.org 受 Cloudflare 防護，一般 HTTP 用戶端會被擋下（回傳「Just a moment…」
    挑戰頁）。本模組原先以 nodriver（規避 CDP 偵測）+ 本機真實 Chrome 通過挑戰取得 HTML。

    後來確認該防護是 Managed Challenge，判定依據主要為 TLS／HTTP2 指紋：以 curl_cffi
    模擬 Chrome 指紋即可直接取得 200；而「搜尋」這一步官網本來就是打 Algolia，虛擬瀏覽器
    只是在替它渲染畫面，可直接呼叫同一個搜尋索引。這條純 HTTP 路徑抽離在 crawlers/iso_http.py，
    整批 46 筆實測 24.7 秒（瀏覽器 293.4 秒）且不需要開視窗，因此列為預設路徑；nodriver 保留為後備 ——
    Cloudflare 規則若日後收緊，仍可自動退回（或以 ISO_HTTP_DISABLE=1 強制走瀏覽器）。

    兩條路徑只有「取得 HTML／搜尋結果」的方式不同，挑選（pick_target）與判定
    （parse_lifecycle + judge_update）完全共用同一套管線。

對外（同步）介面：
    resolve_source_url_sync(standard_name, current_version="")
        → 模擬「ISO 官網搜尋法規名稱 → 進入該標準頁 → 讀 Life cycle」流程，
          回傳該標準的官方來源網址與版本判讀結果。
    fetch_html_sync(url)
        → 直接取得指定網址（例如已設定好的 source_url）的 HTML。
    fetch_available()
        → 兩條路徑至少一條可用時為 True（呼叫端據以決定是否略過 ISO 標準）。

執行緒/事件迴圈注意事項：
    nodriver 需啟動 Chrome 子程序，Windows 上必須在具備 ProactorEventLoop 的執行緒中執行，
    且不可與正在運行的事件迴圈巢狀。因此本模組所有對外函式皆為「同步」並在「呼叫端執行緒」
    建立全新事件迴圈執行；呼叫端（FastAPI 端點、爬蟲）務必透過 asyncio.to_thread() 在
    獨立工作執行緒呼叫，避免巢狀迴圈。以 threading.Lock 序列化，避免同時開啟多個瀏覽器。
    純 HTTP 路徑沒有這些限制，但同樣經由這些同步函式呼叫，呼叫端不必分辨走的是哪條路。
"""
import os
import re
import sys
import asyncio
import logging
import threading
from urllib.parse import urljoin, quote

from crawlers import iso_http

logger = logging.getLogger(__name__)

ISO_BASE = "https://www.iso.org"
CHALLENGE_MARKERS = ("just a moment", "請稍候", "attention required", "checking your browser")

try:
    import nodriver as uc
    BROWSER_AVAILABLE = True
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - 視部署環境而定
    uc = None
    BROWSER_AVAILABLE = False
    _IMPORT_ERROR = e

# 序列化瀏覽器存取，避免同時啟動多個 Chrome 互相干擾
_browser_lock = threading.Lock()


def fetch_available() -> bool:
    """ISO 官網是否有任何可用的取得路徑（純 HTTP 或虛擬瀏覽器）。

    呼叫端應以此（而非 BROWSER_AVAILABLE）判斷要不要略過 ISO 標準：只裝了 curl_cffi、
    沒有 nodriver／本機 Chrome 的環境，現在也能正常查找。
    """
    return iso_http.available() or BROWSER_AVAILABLE


def _headless() -> bool:
    """是否以無頭模式執行（預設關閉，因可見視窗通過 Cloudflare 較穩定）。"""
    return os.getenv("ISO_BROWSER_HEADLESS", "0").strip().lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# 解析輔助（純函式，不需瀏覽器）
# ---------------------------------------------------------------------------
def is_challenge(title: str) -> bool:
    t = (title or "").lower()
    return any(m in t for m in CHALLENGE_MARKERS)


def _abs_url(href: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return urljoin(ISO_BASE + "/", href.lstrip("/"))


def extract_search_results(html: str):
    """從搜尋結果頁 HTML 取出 (絕對網址, 顯示文字) 清單（僅 /standard/ 連結）。"""
    from crawlers.html_parser import parse_html
    soup = parse_html(html)
    results = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/standard/" not in href:
            continue
        text = re.sub(r"\s+", " ", a.get_text(strip=True))
        url = _abs_url(href)
        if url in seen:
            continue
        seen.add(url)
        results.append((url, text))
    return results


def parse_lifecycle(html: str) -> dict:
    """從標準頁 HTML 解析 Life cycle 區塊，回傳結構化資訊。

    欄位：now_status / now_title / now_stage、previously [(status, title), ...]、
          newer_title / newer_year / newer_kind / newer_url（若有新版/取代資訊）。
    """
    from crawlers.html_parser import parse_html
    soup = parse_html(html)
    text = re.sub(r"[ \t]+", " ", soup.get_text(separator="\n"))
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    info = {
        "now_status": "", "now_title": "", "now_stage": "",
        "now_list": [], "previously": [], "newer_title": "", "newer_year": "",
        "newer_kind": "", "newer_url": "",
    }

    try:
        start = next(i for i, ln in enumerate(lines) if ln.lower() == "life cycle")
    except StopIteration:
        start = 0
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].lower().startswith(("this standard contributes", "got a question",
                                        "sitemap", "store")):
            end = i
            break
    block = lines[start:end]

    STATUS = ("Published", "Withdrawn", "Under development", "Deleted")
    # 除了正式出版品的前綴（IEC/TR/TS/PAS），也需辨識「開發中草案」的階段前綴
    # （CD 委員會草案、DIS 國際標準草案、FDIS 最終草案、AWI/NP/WD/PRF…）。
    # 否則 'Will be replaced by → ISO/CD 8601-1' 這類預告改版的項目會完全比對不到，
    # newer_title 永遠是空的，使用者也就看不到「官網已在開發下一版」的訊息。
    std_re = re.compile(
        r"^(?:ISO|IEC)(?:\s*/\s*(?:IEC|TR|TS|PAS|CD|DIS|FDIS|AWI|NP|WD|PRF|DTR|DTS))?"
        r"\s*[\d\-]+",
        re.IGNORECASE,
    )
    year_re = re.compile(r":(\d{4})")

    section = None
    pending_status = ""
    pending_kind = ""
    for ln in block:
        low = ln.lower()
        if low == "previously":
            section = "previously"; pending_status = ""; continue
        if low == "now":
            section = "now"; pending_status = ""; continue
        # 'Amendments' / 'Corrigenda' 是獨立於 'Now' 的區塊，但列出的都是現行主標準的
        # 附屬文件，故一律歸入 now_list。必須明確辨識這個標題，否則若頁面上這個區塊
        # 排在 'Will be replaced by' 等『newer』標題之後（版面常見排法），沒有被重新導回
        # 'now'，區塊內的 Amd/Cor 條目就會被誤歸入 newer（或整個遺漏），造成系統誤判
        # 「缺少附屬文件」判定失效，甚至進一步誤判為「缺少主標準」。
        if low in ("amendments", "amendment", "corrigenda", "corrigendum",
                   "technical corrigenda", "technical corrigendum"):
            section = "now"; pending_status = ""; continue
        if low in ("revised by", "will be replaced by", "new version available",
                   "corrected and reprinted", "confirmed"):
            section = "newer"; pending_kind = ln; pending_status = ""; continue
        if ln in STATUS:
            pending_status = ln; continue
        m = re.match(r"Stage\s*:?\s*([\d.]+)", ln, re.IGNORECASE)
        if m:
            if section == "now":
                info["now_stage"] = m.group(1)
            continue
        if std_re.match(ln):
            if section == "previously":
                info["previously"].append((pending_status, ln))
            elif section == "now":
                info["now_list"].append((pending_status, ln))
                if not info["now_title"]:
                    info["now_status"] = pending_status
                    info["now_title"] = ln
            elif section == "newer":
                if not info["newer_title"]:
                    info["newer_title"] = ln
                    info["newer_kind"] = pending_kind
                    ym = year_re.search(ln)
                    if ym:
                        info["newer_year"] = ym.group(1)
            pending_status = ""

    if info["newer_title"]:
        norm = re.sub(r"\s+", " ", info["newer_title"])
        for a in soup.find_all("a", href=True):
            if re.sub(r"\s+", " ", a.get_text(strip=True)) == norm:
                info["newer_url"] = _abs_url(a["href"])
                break
    return info


def pick_target(results, crawler, base_query):
    """從搜尋結果中挑選與查詢編號『精確相符』的標準頁。

    必須優先選「主標準頁」(Main / TS / TR / PAS) 而非其修正案/勘誤(AMD/COR/ADD)：
    ISO 搜尋結果有時會把 AMD（年份較新）排在主標準之前（例：
    'ISO 3601-3:2005/Amd 1:2018' 出現在 'ISO 3601-3:2005' 之後但年份較大），
    若只看年份會誤選 AMD 頁，導致落點與判定失準。應一律進入主標準頁，
    其 Life cycle 的 NOW/Previously 已涵蓋附屬文件，再據以判定。

    排序優先序：主標準(非AMD/COR/ADD) > 友善網址(指向現行版) > 版本年份較新。
    回傳 (url, text) 或 None。
    """
    want = crawler._normalize_base_number(base_query)
    matches = []
    for url, text in results:
        cand_base = crawler._extract_base_number(text)
        if cand_base and crawler._normalize_base_number(cand_base) == want:
            is_main = detect_doc_type(text) not in ("AMD", "COR", "ADD")
            year_m = re.search(r":(\d{4})", text)
            year = int(year_m.group(1)) if year_m else 0
            # 友善網址（如 /standard/3601-3）指向現行版；具體版次網址通常以 .html 結尾
            friendly = not url.rstrip("/").lower().endswith(".html")
            matches.append((is_main, friendly, year, url, text))
    if not matches:
        return None
    matches.sort(key=lambda m: (m[0], m[1], m[2]), reverse=True)
    return matches[0][3], matches[0][4]


# ---------------------------------------------------------------------------
# ISO 法規版本更新判定（依「ISO 法規版本更新判定邏輯規則.md」）
#
# 判定規則本身與來源網站無關，已抽離至 crawlers/standards_common.py 供 ISO 與
# IEC 等來源共用；此處保留原有名稱轉接，維持既有呼叫端（standards.py、scripts/）不變。
# ---------------------------------------------------------------------------
from crawlers.standards_common import (  # noqa: E402
    detect_doc_type,
    norm_doc as _norm_doc,
    judge_update,
    compose_now_version,
)


def _entry_is_amd_or_cor(title: str) -> bool:
    return detect_doc_type(title) in ("AMD", "COR", "ADD")



# ---------------------------------------------------------------------------
# 瀏覽器核心（async；僅供內部，於專屬事件迴圈中執行）
# ---------------------------------------------------------------------------
async def _open_and_wait(browser, url: str, need_selector=None, max_wait: int = 40):
    """開啟 URL 並等待 Cloudflare 挑戰解開（必要時等指定元素出現），回傳 (page, html)。"""
    page = await browser.get(url)
    waited = 0.0
    while waited < max_wait:
        await page.sleep(1.5)
        waited += 1.5
        title = await page.evaluate("document.title") or ""
        if is_challenge(title):
            continue
        if need_selector:
            try:
                n = await page.evaluate(
                    f"document.querySelectorAll({need_selector!r}).length"
                )
                if not n or int(getattr(n, "value", n)) <= 0:
                    continue
            except (TypeError, ValueError):
                pass
        break
    await page.sleep(1.0)
    html = await page.get_content()
    return page, html


async def _fetch_html(url: str, need_selector=None, max_wait: int = 40) -> str:
    browser = await uc.start(headless=_headless())
    try:
        _, html = await _open_and_wait(browser, url, need_selector, max_wait)
        return html
    finally:
        try:
            browser.stop()
        except Exception:
            pass


def _build_not_found_result(search_url: str, standard_name: str, current_version: str) -> dict:
    """情境一：ISO 官網搜尋『完全沒有回傳任何結果』時的判定結果。

    依「ISO 法規版本更新判定邏輯規則」，標準可能已全面撤銷且無後續替代版本，
    狀態欄位寫入「查無結果，可能已作廢」，並提示由文管人員人工確認。

    注意：source_url 回傳空字串，讓回寫端保留原有官方網址（不以搜尋頁網址覆蓋）。
    """
    doc_type = detect_doc_type(
        f"{standard_name}:{current_version}" if current_version else standard_name
    )
    msg = (
        "系統無法在 ISO 官網找到此標準的任何現行或歷史紀錄。"
        "該標準可能已全面撤銷且無後續替代版本，請由文管人員人工確認後續處理方式。"
    )
    return {
        "ok": True,
        "source_url": "",
        "found_title": "",
        "now_status": "", "now_title": "", "now_stage": "", "now_year": "",
        "now_list": [], "previously": [],
        "newer_title": "", "newer_kind": "", "newer_year": "", "newer_url": "",
        "doc_type": doc_type,
        "judge_statuses": ["not_found"],
        "judge_categories": ["not_found"],
        "judge_status": "not_found",
        "judge_label": "查無結果（可能已作廢）",
        "judge_message": msg,
        "now_main": "",
        "missing_types": [], "missing_supplements": [],
        "has_update": True,
        "reasons": [msg],
    }


def _build_result(url: str, text: str, lc: dict, parsed: dict,
                  standard_name: str, current_version: str, db_docs=None) -> dict:
    """由 Life cycle 解析結果組裝對外回傳 dict，並依判定規則給出更新狀態。

    db_docs: 內部資料庫中「同編號」已收錄文件的正規化集合（供 NOW 缺補充件交叉比對）。
    """
    now_title = lc["now_title"] or parsed.get("full_title", "")
    now_status = lc["now_status"] or parsed.get("status", "")
    newer_title = lc["newer_title"] or parsed.get("new_edition_title", "")
    newer_year = lc["newer_year"] or parsed.get("new_edition_year", "")
    newer_kind = lc["newer_kind"] or ("Revised by" if newer_title else "")
    newer_url = lc["newer_url"] or parsed.get("new_edition_url", "")

    # 依「ISO 法規版本更新判定邏輯規則」進行判定
    doc_type = detect_doc_type(f"{standard_name}:{current_version}" if current_version else standard_name)
    verdict = judge_update(standard_name, current_version, lc, db_docs)

    # 「最新同步版本」須與該筆文件同類型比對：主標準對主標準、附屬文件對附屬文件
    now_year = compose_now_version(lc, doc_type)
    if not now_year:
        now_year_m = re.search(r":(\d{4})", now_title)
        now_year = now_year_m.group(1) if now_year_m else parsed.get("version_year", "")

    return {
        "ok": True,
        "source_url": url,
        "found_title": text,
        "now_status": now_status,
        "now_title": now_title,
        "now_stage": lc["now_stage"],
        "now_year": now_year,
        "now_list": [{"status": s, "title": t} for s, t in lc.get("now_list", [])],
        "previously": [{"status": s, "title": t} for s, t in lc["previously"]],
        "newer_title": newer_title,
        "newer_kind": newer_kind,
        "newer_year": newer_year,
        "newer_url": newer_url,
        # 判定結果
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
        "reasons": [verdict["judge_message"]],
    }


async def _resolve_with(browser, crawler, standard_name: str, current_version: str) -> dict:
    """使用『既有』瀏覽器與 crawler 解析單一標準（不負責開關瀏覽器）。

    每次 browser.get(new_tab=False 預設) 會沿用同一分頁導覽，故批量呼叫共用同一視窗、同一分頁。
    """
    query = crawler._extract_base_number(standard_name) or standard_name
    search_url = f"{ISO_BASE}/search.html?q={quote(query)}"
    _, search_html = await _open_and_wait(
        browser, search_url, need_selector='a[href*="/standard/"]'
    )
    results = extract_search_results(search_html)
    if not results:
        # 仍卡在 Cloudflare 挑戰頁 → 視為抓取失敗（不可誤判為作廢）
        if is_challenge(search_html):
            return {"ok": False, "error": "搜尋無結果（仍被 Cloudflare 擋下）", "query": query}
        # 情境一：官網搜尋完全無回傳結果 → 查無結果，可能已作廢（需人工確認）
        return _build_not_found_result(search_url, standard_name, current_version)

    target = pick_target(results, crawler, query)
    if not target:
        # 搜尋有回傳但找不到精確匹配的標準頁（例如已撤銷標準的搜尋結果只有其他標準）。
        # 依「ISO 法規版本更新判定邏輯規則」情境一：視同「查無此標準」，可能已作廢。
        logger.info(
            f"[iso_browser] 搜尋 {query!r} 有結果但無精確匹配"
            f"（候選項目: {[t for _, t in results[:4]]}），視為查無此標準（可能已作廢）。"
        )
        return _build_not_found_result(search_url, standard_name, current_version)
    url, text = target
    _, std_html = await _open_and_wait(browser, url)
    return _resolve_from_html(crawler, standard_name, current_version, url, text, std_html)


def _resolve_from_html(crawler, standard_name: str, current_version: str,
                       url: str, text: str, html: str) -> dict:
    """由標準頁 HTML 走完判定管線並組裝結果。

    虛擬瀏覽器與純 HTTP 兩條路徑共用本函式，確保判定邏輯只有一份
    （見 CLAUDE.md 架構鐵則：兩種掃描模式必須走同一套判定管線）。
    """
    lc = parse_lifecycle(html)
    parsed = crawler._parse_iso_page(html)
    db_docs = _collect_db_docs(crawler, standard_name)
    return _build_result(url, text, lc, parsed, standard_name, current_version, db_docs)


def _resolve_http_one(crawler, standard_name: str, current_version: str) -> dict:
    """純 HTTP 路徑的單筆查找：Algolia 搜尋 → 取標準頁 → 共用判定管線。

    與瀏覽器路徑 _resolve_with() 使用完全相同的挑選（pick_target）與判定
    （_resolve_from_html）邏輯，差別僅在取得資料的方式。

    「官網確實查無此標準」回傳 _build_not_found_result()（正常結果，不是失敗）；
    取得層失敗則丟出例外，由呼叫端決定是否退回虛擬瀏覽器。
    """
    query = crawler._extract_base_number(standard_name) or standard_name
    results = iso_http.search(query)
    if not results:
        # 情境一：官網搜尋完全無回傳結果 → 查無結果，可能已作廢（需人工確認）
        return _build_not_found_result("", standard_name, current_version)

    target = pick_target(results, crawler, query)
    if not target:
        logger.info(
            f"[iso_http] 搜尋 {query!r} 有結果但無精確匹配"
            f"（候選項目: {[t for _, t in results[:4]]}），視為查無此標準（可能已作廢）。"
        )
        return _build_not_found_result("", standard_name, current_version)

    url, text = target
    html = iso_http.fetch_html(url)
    return _resolve_from_html(crawler, standard_name, current_version, url, text, html)


def _collect_db_docs(crawler, standard_name: str) -> set:
    """蒐集內部資料庫中「同編號」已收錄文件的正規化字串集合（含其修正案/勘誤版本），
    供 NOW 主標準的「缺補充件」交叉比對。例如資料庫某筆 current_version 為
    '2019+Amd 1:2023'，會被視為已收錄附屬文件 'ISO 11607-1:2019/Amd 1:2023'。"""
    from database import get_db
    docs = set()
    base = crawler._normalize_base_number(crawler._extract_base_number(standard_name))
    if not base:
        return docs
    try:
        conn = get_db()
        try:
            rows = conn.execute("SELECT title, current_version FROM standards").fetchall()
        finally:
            conn.close()
    except Exception:
        return docs
    for r in rows:
        rtitle = r["title"] or ""
        rbase = crawler._normalize_base_number(crawler._extract_base_number(rtitle))
        if rbase and rbase == base:
            cv = (r["current_version"] or "").strip()
            docs.add(_norm_doc(f"{rtitle}:{cv}" if cv else rtitle))
    return docs


async def _resolve(standard_name: str, current_version: str) -> dict:
    """單筆查找：開啟一個瀏覽器、解析、關閉。"""
    from crawlers.standards import StandardsCrawler
    crawler = StandardsCrawler()
    browser = await uc.start(headless=_headless())
    try:
        return await _resolve_with(browser, crawler, standard_name, current_version)
    finally:
        try:
            browser.stop()
        except Exception:
            pass
        await crawler.close()


async def _resolve_many(items: list, on_item=None) -> dict:
    """批量查找：『共用同一個瀏覽器視窗』依序處理整批，全部完成後才關閉。

    items: [{"key": <任意鍵>, "standard_name": str, "current_version": str}, ...]
    on_item: 選填回呼 on_item(key, item, result)，每處理完一筆即呼叫（供即時進度/寫回）。
    回傳 {key: result_dict}。單筆失敗不影響其餘項目。
    """
    from crawlers.standards import StandardsCrawler
    crawler = StandardsCrawler()
    browser = await uc.start(headless=_headless())
    out = {}
    try:
        for it in items:
            key = it["key"]
            try:
                result = await _resolve_with(
                    browser, crawler, it.get("standard_name") or "", it.get("current_version") or ""
                )
            except Exception as e:
                result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            out[key] = result
            if on_item is not None:
                try:
                    on_item(key, it, result)
                except Exception as cb_err:  # 回呼錯誤不應中斷整批
                    logger.warning(f"on_item 回呼錯誤（{key}）: {cb_err}")
    finally:
        try:
            browser.stop()
        except Exception:
            pass
        await crawler.close()
    return out


# ---------------------------------------------------------------------------
# 對外同步介面（於呼叫端執行緒建立全新事件迴圈；請以 asyncio.to_thread 呼叫）
# ---------------------------------------------------------------------------
def _run_sync(coro):
    """在「目前執行緒」建立全新事件迴圈執行 coroutine。

    呼叫端必須處於『沒有正在運行事件迴圈』的執行緒（例如 asyncio.to_thread 的工作執行緒），
    否則會與既有迴圈巢狀而報錯。

    Windows 上「必須」使用 ProactorEventLoop 才能啟動 Chrome 子程序；SelectorEventLoop 會丟
    NotImplementedError。注意 uvicorn --reload 會把全域事件迴圈政策設為 Selector，使
    asyncio.new_event_loop() 取得 SelectorEventLoop 而失敗，故此處直接指定 ProactorEventLoop，
    不依賴全域政策。
    """
    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        try:
            loop.run_until_complete(asyncio.sleep(0.2))  # 讓 nodriver 收尾
        except Exception:
            pass
        loop.close()
        asyncio.set_event_loop(None)


def _ensure_available():
    if not fetch_available():
        raise RuntimeError(
            "ISO 官網的兩條取得路徑皆無法使用："
            f"curl_cffi（{iso_http.import_error()}）、nodriver（{_IMPORT_ERROR}）。"
            "請至少安裝其中之一，詳見 requirements-local.txt 說明。"
        )


def _new_crawler():
    """建立供解析使用的 StandardsCrawler（純 HTTP 路徑為同步情境，需自行收尾）。"""
    from crawlers.standards import StandardsCrawler
    return StandardsCrawler()


def _close_crawler(crawler) -> None:
    """關閉 StandardsCrawler 內部的 httpx client（同步情境下的收尾）。"""
    try:
        asyncio.run(crawler.close())
    except Exception:  # 收尾失敗不應影響已取得的結果
        pass


def _notify(on_item, *args) -> None:
    """呼叫進度回呼；回呼自身的錯誤不得中斷整批處理。"""
    if on_item is None:
        return
    try:
        on_item(*args)
    except Exception as cb_err:
        logger.warning(f"on_item 回呼錯誤（{args[0] if args else ''}）: {cb_err}")


def fetch_html_sync(url: str, need_selector=None, max_wait: int = 40) -> str:
    """取得指定網址 HTML（優先純 HTTP，失敗退回虛擬瀏覽器）。請以 asyncio.to_thread 呼叫。"""
    _ensure_available()
    if iso_http.available():
        try:
            return iso_http.fetch_html(url)
        except Exception as e:
            if not BROWSER_AVAILABLE:
                raise
            logger.warning(f"[iso_browser] 純 HTTP 取得失敗（{e}），改用虛擬瀏覽器: {url}")
    with _browser_lock:
        return _run_sync(_fetch_html(url, need_selector, max_wait))


def resolve_source_url_sync(standard_name: str, current_version: str = "") -> dict:
    """搜尋 ISO 官網並解析該標準的 Life cycle，回傳官方網址與版本判讀。

    優先走純 HTTP 路徑，取得失敗才退回虛擬瀏覽器。請以 asyncio.to_thread 呼叫。
    """
    _ensure_available()
    if iso_http.available():
        crawler = _new_crawler()
        try:
            return _resolve_http_one(crawler, standard_name, current_version)
        except Exception as e:
            if not BROWSER_AVAILABLE:
                raise
            logger.warning(f"[iso_browser] 純 HTTP 查找失敗（{e}），改用虛擬瀏覽器: {standard_name}")
        finally:
            _close_crawler(crawler)
    with _browser_lock:
        return _run_sync(_resolve(standard_name, current_version))


async def _fetch_many(urls: list, on_item=None) -> dict:
    """批量取得多個網址的 HTML：『共用同一個瀏覽器視窗』依序處理，全部完成後才關閉。

    urls: 網址字串列表（可含重複，重複者僅實際擷取一次）。
    on_item: 選填回呼 on_item(url, html_or_None)，每處理完一筆即呼叫。
    回傳 {url: html}；單筆失敗則該 url 對應 None，不影響其餘網址。
    """
    browser = await uc.start(headless=_headless())
    out = {}
    try:
        for url in dict.fromkeys(urls):  # 保序去重
            try:
                _, html = await _open_and_wait(browser, url)
                out[url] = html
            except Exception as e:
                logger.warning(f"[iso_browser] 批次取得 HTML 失敗（{url}）: {e}")
                out[url] = None
            if on_item is not None:
                try:
                    on_item(url, out[url])
                except Exception as cb_err:  # 回呼錯誤不應中斷整批
                    logger.warning(f"on_item 回呼錯誤（{url}）: {cb_err}")
    finally:
        try:
            browser.stop()
        except Exception:
            pass
    return out


def fetch_many_sync(urls: list, on_item=None) -> dict:
    """批量取得多個網址的 HTML。用於例行掃描模式：標準已設定 source_url，僅需重新讀取頁面。

    先以純 HTTP 掃過整批（共用連線）；取得失敗者才集中交給虛擬瀏覽器重試，
    整批共用『同一個瀏覽器視窗』，不會逐筆開關視窗。

    urls: 網址字串列表。
    on_item: 選填回呼 on_item(url, html_or_None)，每處理完一筆即呼叫（每個網址只會呼叫一次）。
    回傳 {url: html_or_None}。請以 asyncio.to_thread 呼叫。
    """
    _ensure_available()
    if not urls:
        return {}

    out = {}
    pending = list(dict.fromkeys(urls))  # 保序去重
    if iso_http.available():
        pending = []
        for url in dict.fromkeys(urls):
            try:
                html = iso_http.fetch_html(url)
            except Exception as e:
                logger.warning(f"[iso_browser] 純 HTTP 取得失敗（{url}）: {e}")
                pending.append(url)
                continue
            out[url] = html
            _notify(on_item, url, html)

        if not pending:
            return out
        if not BROWSER_AVAILABLE:
            for url in pending:
                out[url] = None
                _notify(on_item, url, None)
            return out
        logger.info(f"[iso_browser] {len(pending)} 個網址改以虛擬瀏覽器重試")

    with _browser_lock:
        out.update(_run_sync(_fetch_many(pending, on_item)))
    return out


def resolve_many_sync(items: list, on_item=None) -> dict:
    """批量查找整批標準的 Life cycle 與版本判讀。

    先以純 HTTP 掃過整批（共用連線）；取得失敗者才集中交給虛擬瀏覽器重試，
    整批共用『同一個瀏覽器視窗』，不會逐筆開關視窗。

    items: [{"key": <任意鍵>, "standard_name": str, "current_version": str}, ...]
    on_item: 選填回呼 on_item(key, item, result)，每處理完一筆即呼叫（供即時進度/寫回）。
        待重試的項目在純 HTTP 階段刻意不呼叫回呼，避免同一筆被回寫兩次。
    回傳 {key: result_dict}。請以 asyncio.to_thread 呼叫。
    """
    _ensure_available()
    if not items:
        return {}

    out = {}
    pending = list(items)
    if iso_http.available():
        pending = []
        crawler = _new_crawler()
        try:
            for it in items:
                try:
                    result = _resolve_http_one(
                        crawler, it.get("standard_name") or "", it.get("current_version") or ""
                    )
                except Exception as e:
                    logger.warning(
                        f"[iso_browser] 純 HTTP 查找失敗（{it.get('standard_name')}）: {e}"
                    )
                    pending.append(it)
                    continue
                out[it["key"]] = result
                _notify(on_item, it["key"], it, result)
        finally:
            _close_crawler(crawler)

        if not pending:
            return out
        if not BROWSER_AVAILABLE:
            for it in pending:
                result = {"ok": False,
                          "error": "ISO 官網純 HTTP 取得失敗，且未安裝虛擬瀏覽器(nodriver)可退回"}
                out[it["key"]] = result
                _notify(on_item, it["key"], it, result)
            return out
        logger.info(f"[iso_browser] {len(pending)} 筆改以虛擬瀏覽器重試")

    with _browser_lock:
        out.update(_run_sync(_resolve_many(pending, on_item)))
    return out
