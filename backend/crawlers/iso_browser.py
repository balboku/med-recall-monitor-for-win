"""ISO 官網 Life cycle 虛擬瀏覽器存取（通過 Cloudflare）。

背景：
    www.iso.org 受 Cloudflare 防護，純 HTTP（含一般 headless 瀏覽器、CDP 自動化）皆會被
    擋下（回傳「Just a moment…」挑戰頁）。本模組改用 nodriver（規避 CDP 偵測）+ 本機真實
    Chrome 通過挑戰後取得頁面 HTML，再以 StandardsCrawler 的解析方法擷取版本／狀態／新版資訊。

對外（同步）介面：
    resolve_source_url_sync(standard_name, current_version="")
        → 模擬「ISO 官網搜尋法規名稱 → 進入該標準頁 → 讀 Life cycle」流程，
          回傳該標準的官方來源網址與版本判讀結果。
    fetch_html_sync(url)
        → 以虛擬瀏覽器直接取得指定網址（例如已設定好的 source_url）的 HTML。

執行緒/事件迴圈注意事項：
    nodriver 需啟動 Chrome 子程序，Windows 上必須在具備 ProactorEventLoop 的執行緒中執行，
    且不可與正在運行的事件迴圈巢狀。因此本模組所有對外函式皆為「同步」並在「呼叫端執行緒」
    建立全新事件迴圈執行；呼叫端（FastAPI 端點、爬蟲）務必透過 asyncio.to_thread() 在
    獨立工作執行緒呼叫，避免巢狀迴圈。以 threading.Lock 序列化，避免同時開啟多個瀏覽器。
"""
import os
import re
import sys
import asyncio
import logging
import threading
from urllib.parse import urljoin, quote

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
    std_re = re.compile(r"^(?:ISO|IEC)(?:/(?:IEC|TR|TS|PAS))?\s*[\d\-]+", re.IGNORECASE)
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

    優先：友善網址 /standard/<編號> > 版本年份最新者。回傳 (url, text) 或 None。
    """
    want = crawler._normalize_base_number(base_query)
    matches = []
    for url, text in results:
        cand_base = crawler._extract_base_number(text)
        if cand_base and crawler._normalize_base_number(cand_base) == want:
            year_m = re.search(r":(\d{4})", text)
            year = int(year_m.group(1)) if year_m else 0
            friendly = bool(re.search(r"/standard/[^/]*\D", url))  # 含非純數字（友善網址）
            matches.append((friendly, year, url, text))
    if not matches:
        return None
    matches.sort(key=lambda m: (m[0], m[1]), reverse=True)
    _, _, url, text = matches[0]
    return url, text


# ---------------------------------------------------------------------------
# ISO 法規版本更新判定（依「ISO 法規版本更新判定邏輯規則.md」）
# ---------------------------------------------------------------------------
def detect_doc_type(doc_str: str) -> str:
    """第一步：文件類型字串判定。回傳 'AMD'|'COR'|'ADD'|'TS'|'TR'|'PAS'|'Main'。

    依規則順序：先判後綴(Amd/Cor/Add)，再判前綴(TS/TR/PAS)，都沒命中才視為主標準(Main)。
    寬鬆比對：資料庫的版本可能寫成 '2018+Amd 1:2021'（用 +），故以是否含 'amd/cor/add' 字樣判定。
    """
    s = (doc_str or "")
    low = s.lower()
    if re.search(r"\bamd\b|/amd|\+amd", low):
        return "AMD"
    if re.search(r"\bcor\b|/cor|\+cor", low):
        return "COR"
    if re.search(r"\badd\b|/add|\+add", low):
        return "ADD"
    if re.search(r"iso\s*/\s*ts", low):
        return "TS"
    if re.search(r"iso\s*/\s*tr", low):
        return "TR"
    if re.search(r"iso\s*/\s*pas", low):
        return "PAS"
    return "Main"


def _norm_doc(s: str) -> str:
    """文件字串正規化（移除所有非英數字、轉小寫）以利跨格式比對，
    例如 'ISO 11737-1:2018/Amd 1:2021' 與 'ISO 11737-1:2018+Amd 1:2021' 視為相同。"""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _entry_is_amd_or_cor(title: str) -> bool:
    return detect_doc_type(title) in ("AMD", "COR", "ADD")


def judge_update(user_title: str, user_version: str, lc: dict) -> dict:
    """第二、三步：依文件落在 NOW / Previously 區塊與文件類型，判定更新狀態。

    回傳：
        judge_status: 'valid' | 'valid_with_updates' | 'obsolete' | 'integrated' | 'unknown'
        judge_label:  中文狀態標籤（含燈號）
        judge_message: 給使用者的提示
        has_update:   是否需提醒（valid=False，其餘視情況 True）
        now_main:     NOW 區塊的主標準字串（供提示用）
    """
    # 組出使用者持有的完整文件字串（法規名稱 + 版本）
    uv = (user_version or "").strip()
    if uv:
        user_doc = f"{user_title}:{uv}" if not re.match(r"^\s*[:：]", uv) else f"{user_title}{uv}"
    else:
        user_doc = user_title or ""
    doc_type = detect_doc_type(user_doc)

    now_list = lc.get("now_list") or ([(lc.get("now_status", ""), lc.get("now_title", ""))]
                                      if lc.get("now_title") else [])
    prev_list = lc.get("previously") or []

    # NOW 區塊的主標準（第一筆非 Amd/Cor）
    now_main = ""
    now_has_amdcor = False
    for _st, t in now_list:
        if _entry_is_amd_or_cor(t):
            now_has_amdcor = True
        elif not now_main:
            now_main = t
    if not now_main and now_list:
        now_main = now_list[0][1]

    un = _norm_doc(user_doc)
    now_norm = {_norm_doc(t): t for _st, t in now_list}
    prev_norm = {_norm_doc(t): t for _st, t in prev_list}

    # 進階防呆：使用者持有 NOW 主標準，且 NOW 區塊另含新發布的 Amd/Cor 附屬文件
    now_amdcor_titles = [t for _st, t in now_list if _entry_is_amd_or_cor(t)]

    # 情境一：落於 NOW
    if un in now_norm:
        if doc_type == "Main" and now_amdcor_titles:
            return {
                "judge_status": "valid_with_updates",
                "judge_label": "🟢 最新版（有新增補充文件）",
                "judge_message": (
                    f"您的主標準為最新版，但官方已發布最新的補充文件 "
                    f"{', '.join(now_amdcor_titles)}，請確認是否需要一併取得。"),
                "has_update": True,
                "now_main": now_main,
            }
        return {
            "judge_status": "valid",
            "judge_label": "🟢 無更新",
            "judge_message": "文件為最新有效版本，無需動作。",
            "has_update": False,
            "now_main": now_main,
        }

    # 情境二：落於 Previously
    if un in prev_norm:
        if doc_type in ("AMD", "ADD"):
            return {
                "judge_status": "integrated",
                "judge_label": "🟡 已整合作廢",
                "judge_message": (
                    f"您持有的舊版修正案已失效，相關技術變更已整合至最新版主標準 "
                    f"{now_main or '（最新版）'}，請直接取得新版主標準。"),
                "has_update": True,
                "now_main": now_main,
            }
        if doc_type == "COR":
            return {
                "judge_status": "integrated",
                "judge_label": "🟡 已整合作廢",
                "judge_message": (
                    f"您持有的舊版技術勘誤已失效，相關勘誤已於最新版主標準 "
                    f"{now_main or '（最新版）'} 中修正，請直接取得新版主標準。"),
                "has_update": True,
                "now_main": now_main,
            }
        # Main / TS / TR / PAS
        return {
            "judge_status": "obsolete",
            "judge_label": "🔴 已改版作廢",
            "judge_message": f"您持有的舊版文件已作廢，請更新至 {now_main or '（最新版）'} 版。",
            "has_update": True,
            "now_main": now_main,
        }

    # 未在 NOW / Previously 找到：以年份回退判斷（避免漏接），標記為無法精確判定
    now_year_m = re.search(r":(\d{4})", now_main)
    now_year = now_year_m.group(1) if now_year_m else ""
    uv_year_m = re.search(r"(\d{4})", uv)
    uv_year = uv_year_m.group(1) if uv_year_m else ""
    if now_year and uv_year and now_year != uv_year:
        return {
            "judge_status": "obsolete",
            "judge_label": "🔴 已改版作廢",
            "judge_message": (
                f"您持有的版本（{uv_year}）未出現在官網現行清單，且現行版為 {now_main}，"
                f"研判已改版，請確認並更新。"),
            "has_update": True,
            "now_main": now_main,
        }
    return {
        "judge_status": "unknown",
        "judge_label": "⚪ 無法判定",
        "judge_message": (
            f"未能在官網 Life cycle 的 NOW / Previously 區塊比對到您持有的版本"
            f"（{user_doc}），請人工確認。現行版：{now_main or '未知'}。"),
        "has_update": False,
        "now_main": now_main,
    }


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


def _build_result(url: str, text: str, lc: dict, parsed: dict,
                  standard_name: str, current_version: str) -> dict:
    """由 Life cycle 解析結果組裝對外回傳 dict，並依判定規則給出更新狀態。"""
    now_title = lc["now_title"] or parsed.get("full_title", "")
    now_status = lc["now_status"] or parsed.get("status", "")
    newer_title = lc["newer_title"] or parsed.get("new_edition_title", "")
    newer_year = lc["newer_year"] or parsed.get("new_edition_year", "")
    newer_kind = lc["newer_kind"] or ("Revised by" if newer_title else "")
    newer_url = lc["newer_url"] or parsed.get("new_edition_url", "")

    now_year_m = re.search(r":(\d{4})", now_title)
    now_year = now_year_m.group(1) if now_year_m else parsed.get("version_year", "")

    # 依「ISO 法規版本更新判定邏輯規則」進行判定
    doc_type = detect_doc_type(f"{standard_name}:{current_version}" if current_version else standard_name)
    verdict = judge_update(standard_name, current_version, lc)

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
        "judge_status": verdict["judge_status"],
        "judge_label": verdict["judge_label"],
        "judge_message": verdict["judge_message"],
        "now_main": verdict["now_main"],
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
        return {"ok": False, "error": "搜尋無結果（或仍被 Cloudflare 擋下）", "query": query}

    target = pick_target(results, crawler, query)
    if not target:
        return {
            "ok": False,
            "error": f"搜尋結果中找不到與「{query}」編號精確相符的標準頁",
            "query": query,
            "candidates": [t for _, t in results[:8]],
        }
    url, text = target
    _, std_html = await _open_and_wait(browser, url)
    lc = parse_lifecycle(std_html)
    parsed = crawler._parse_iso_page(std_html)
    return _build_result(url, text, lc, parsed, standard_name, current_version)


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


async def _resolve_many(items: list) -> dict:
    """批量查找：『共用同一個瀏覽器視窗』依序處理整批，全部完成後才關閉。

    items: [{"key": <任意鍵>, "standard_name": str, "current_version": str}, ...]
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
                out[key] = await _resolve_with(
                    browser, crawler, it.get("standard_name") or "", it.get("current_version") or ""
                )
            except Exception as e:
                out[key] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
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
    if not BROWSER_AVAILABLE:
        raise RuntimeError(
            f"虛擬瀏覽器套件 nodriver 無法載入（{_IMPORT_ERROR}）。"
            "請確認已安裝 nodriver 與本機 Chrome，詳見 requirements-local.txt 說明。"
        )


def fetch_html_sync(url: str, need_selector=None, max_wait: int = 40) -> str:
    """以虛擬瀏覽器取得指定網址 HTML（通過 Cloudflare）。請以 asyncio.to_thread 呼叫。"""
    _ensure_available()
    with _browser_lock:
        return _run_sync(_fetch_html(url, need_selector, max_wait))


def resolve_source_url_sync(standard_name: str, current_version: str = "") -> dict:
    """搜尋 ISO 官網並解析該標準的 Life cycle，回傳官方網址與版本判讀。請以 asyncio.to_thread 呼叫。"""
    _ensure_available()
    with _browser_lock:
        return _run_sync(_resolve(standard_name, current_version))


def resolve_many_sync(items: list) -> dict:
    """批量查找：共用『同一個瀏覽器視窗』依序處理整批，全部完成後才關閉（不會逐筆開關視窗）。

    items: [{"key": <任意鍵>, "standard_name": str, "current_version": str}, ...]
    回傳 {key: result_dict}。請以 asyncio.to_thread 呼叫。
    """
    _ensure_available()
    if not items:
        return {}
    with _browser_lock:
        return _run_sync(_resolve_many(items))
