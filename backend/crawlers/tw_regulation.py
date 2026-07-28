"""台灣法規版本追蹤（R601 / R602）：全國法規資料庫。

判定基準：
    台灣法規的「版本」是**最後修正／發布日期**。法規名稱不變，歷次修正只換日期，
    故以全國法規資料庫（law.moj.gov.tw）該法規沿革頁的日期作為版本。

為什麼改用「依名稱搜尋」而非寫死 pcode：
    原 tfda_regulations.py 以硬編碼的 pcode 對照表查詢，實測 22 筆中**只有 3 筆正確**，
    其餘 19 筆指向完全不同的法規（例如「醫療器材品質管理系統準則」對到的其實是
    「醫療器材管理事項委託及受託機構認證作業辦法」）。且其使用的
    GetLaw.ashx API 已回傳 404。
    改為每次以法規名稱搜尋取得 pcode，對照表不會隨官網編號調整而失效。

存取注意事項：
    law.moj.gov.tw 對密集請求會直接斷線（RemoteProtocolError），且憑證需略過驗證。
    故務必：共用單一連線、請求間留間隔、失敗時退避重試。
"""
import re
import asyncio
import logging
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

SEARCH_URL = "https://law.moj.gov.tw/Law/LawSearchResult.aspx?ty=ONEBAR&kw={kw}"
HISTORY_URL = "https://law.moj.gov.tw/LawClass/LawHistory.aspx?pcode={pcode}"
LAW_PAGE_URL = "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={pcode}"

REQUEST_TIMEOUT = 40.0
REQUEST_INTERVAL = 1.2          # 對政府網站放慢，避免被斷線
MAX_RETRIES = 3

# 版本日期的優先序：修正過的取修正日期，否則取公布（法律）／發布（命令）日期
DATE_LABELS = ("修正日期", "公布日期", "發布日期")

# 名稱結尾的法規類型字樣，做「詞幹比對」時移除
NAME_SUFFIXES = ("辦法", "細則", "準則", "標準", "規定", "規範", "要點", "條例", "法")


def normalize_name(name: str) -> str:
    """比對用正規化：去除空白與常見異體字差異（例：標簽／標籤）。"""
    s = re.sub(r"\s+", "", name or "")
    return s.replace("簽", "籤")


def name_stem(name: str) -> str:
    """移除結尾的法規類型字樣，用於容忍「…核發法」與「…核發辦法」這類漏字。"""
    s = normalize_name(name)
    for suffix in NAME_SUFFIXES:      # NAME_SUFFIXES 已由長到短排列
        if s.endswith(suffix) and len(s) > len(suffix):
            return s[: -len(suffix)]
    return s


def normalize_date(value: str) -> str:
    """將日期字串正規化為僅含數字，供比對（'民國 110 年 04 月 26 日' → '1100426'）。"""
    return re.sub(r"\D", "", value or "")


def search_keyword(name: str) -> str:
    """組出可安全放進查詢字串的搜尋關鍵字。

    law.moj.gov.tw 會擋掉查詢字串中的 %2F（ASP.NET 請求驗證），使
    '醫療器材人因/可用性工程評估指引' 這類含斜線的名稱直接回 404。
    改以空白取代斜線等分隔符號；比對時仍以原始名稱為準。
    """
    return quote(re.sub(r"[/\\]+", " ", name or "").strip(), safe="")


# ---------------------------------------------------------------------------
# 網頁存取
# ---------------------------------------------------------------------------
async def _get(client: httpx.AsyncClient, url: str) -> httpx.Response:
    """取得頁面，含退避重試（政府網站對密集請求會直接斷線）。"""
    last = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last = e
            await asyncio.sleep(2 * (attempt + 1))
    raise last


def parse_search_results(html: str) -> list:
    """從搜尋結果頁取出 [(法規名稱, pcode), ...]。"""
    from crawlers.html_parser import parse_html

    soup = parse_html(html)
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        m = re.search(r"[Pp]code=([A-Z0-9]+)", a["href"])
        if not m:
            continue
        text = re.sub(r"\s+", "", a.get_text(strip=True))
        if not text or text == "EN":
            continue
        key = (m.group(1), text)
        if key in seen:
            continue
        seen.add(key)
        out.append((text, m.group(1)))
    return out


def parse_history(html: str) -> dict:
    """解析沿革頁的資訊表，回傳 {欄位名稱: 值}。"""
    from crawlers.html_parser import parse_html

    soup = parse_html(html)
    info = {}
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        label = re.sub(r"\s+", "", cells[0].get_text(strip=True)).rstrip("：:")
        if label and label not in info:
            info[label] = re.sub(r"\s+", " ", cells[1].get_text(strip=True))
    return info


def pick_law(candidates: list, name: str):
    """從搜尋結果挑出與法規名稱相符者，回傳 (官網名稱, pcode) 或 None。

    先精確比對；比不到時退而以「詞幹」比對，以容忍公司紀錄的漏字
    （例：'…製造許可核發法' 官方為 '…製造許可核發辦法'）。
    """
    want = normalize_name(name)
    for text, pcode in candidates:
        if normalize_name(text) == want:
            return text, pcode

    want_stem = name_stem(name)
    if len(want_stem) >= 6:  # 詞幹太短容易誤配
        for text, pcode in candidates:
            if name_stem(text) == want_stem:
                return text, pcode
    return None


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------
def _result(status, label, message, has_update, shown,
            source_url="", found_title="", now_status=""):
    return {
        "ok": True,
        "source_url": source_url,
        "found_title": found_title,
        "now_status": now_status,
        "now_title": found_title,
        "now_stage": "",
        "now_year": shown,
        "now_list": ([{"status": now_status, "title": found_title}] if found_title else []),
        "previously": [],
        "newer_title": "", "newer_kind": "", "newer_year": "", "newer_url": "",
        "doc_type": "Main",
        "judge_status": status,
        "judge_label": label,
        "judge_message": message,
        "now_main": found_title,
        "missing_types": [], "missing_supplements": [],
        "has_update": has_update,
        "reasons": [message],
    }


def judge_tw(name: str, current_version: str, site_name: str,
             pcode: str, info: dict) -> dict:
    """依沿革頁資訊判定版本狀態。"""
    version = next((info[k] for k in DATE_LABELS if info.get(k)), "")
    url = LAW_PAGE_URL.format(pcode=pcode)
    effect = info.get("生效狀態", "")

    # 名稱與官網不一致時一併提示，避免文管誤以為系統查錯法規
    name_note = ""
    if normalize_name(site_name) != normalize_name(name):
        name_note = f"（注意：官網法規名稱為「{site_name}」，與內部紀錄不同，建議更正名稱）"

    if not version:
        msg = f"已於全國法規資料庫找到此法規（{pcode}），但沿革頁未提供日期資訊，請人工確認。{name_note}"
        return _result("unknown", "⚪ 無法判定", msg, False, "", url, site_name)

    effect_note = ""
    if effect and "尚未生效" in effect:
        effect_note = f" 另注意：{effect[:60]}"

    cur = (current_version or "").strip()
    if not cur:
        msg = (f"已建立基準版本：全國法規資料庫所載最新版本為 {version}。"
               f"原「目前使用版本」為空白，請文管人員確認後填入，之後即可自動比對修正。"
               f"{name_note}{effect_note}")
        return _result("baseline", "已建立基準版本", msg, False, version, url, site_name, "現行有效")

    if normalize_date(cur) == normalize_date(version):
        msg = f"目前使用版本與全國法規資料庫所載 {version} 一致，無需動作。{name_note}{effect_note}"
        return _result("valid", "無更新", msg, False, version, url, site_name, "現行有效")

    msg = (f"全國法規資料庫所載最新版本為 {version}，與目前使用版本（{cur}）不同，"
           f"表示此法規已修正，請取得最新條文。{name_note}{effect_note}")
    return _result("obsolete", "有更新 (法規已修正)", msg, True, version, url, site_name, "現行有效")


def _not_a_law_result(name: str) -> dict:
    msg = ("此文件未收錄於全國法規資料庫，研判為主管機關發布的指引／手冊／公告"
           "（非法規命令），無公開的版本沿革可自動比對，請人工至食藥署網站確認最新版本。")
    return _result("manual", "需人工確認", msg, False, "",
                   "https://law.moj.gov.tw/", "")


# ---------------------------------------------------------------------------
# 對外介面
# ---------------------------------------------------------------------------
def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
        verify=False,  # gov.tw 憑證鏈在部分環境無法驗證
        headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-TW,zh;q=0.9",
        },
    )


async def _resolve_with(client: httpx.AsyncClient, name: str, current_version: str) -> dict:
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "法規名稱為空"}

    try:
        resp = await _get(client, SEARCH_URL.format(kw=search_keyword(name)))
    except Exception as e:
        return {"ok": False, "error": f"全國法規資料庫搜尋失敗：{type(e).__name__}: {e}"}

    candidates = parse_search_results(resp.text)
    picked = pick_law(candidates, name)

    # 內部紀錄的名稱可能漏字（例：'…核發法' 官方為 '…核發辦法'），此時以完整名稱搜尋會 0 筆，
    # 詞幹比對沒有機會生效。改以詞幹再搜一次，仍以詞幹比對確認，避免比到不相干的法規。
    if not picked:
        stem = name_stem(name)
        if len(stem) >= 6 and stem != normalize_name(name):
            await asyncio.sleep(REQUEST_INTERVAL)
            try:
                resp2 = await _get(client, SEARCH_URL.format(kw=search_keyword(stem)))
                picked = pick_law(parse_search_results(resp2.text), name)
            except Exception:
                picked = None

    if not picked:
        return _not_a_law_result(name)

    site_name, pcode = picked
    await asyncio.sleep(REQUEST_INTERVAL)
    try:
        hist = await _get(client, HISTORY_URL.format(pcode=pcode))
    except Exception as e:
        return {"ok": False, "error": f"法規沿革頁讀取失敗（{pcode}）：{type(e).__name__}: {e}"}

    return judge_tw(name, current_version, site_name, pcode, parse_history(hist.text))


async def resolve_source_url(standard_name: str, current_version: str = "") -> dict:
    """查詢單一台灣法規的最新修正日期與判讀。"""
    async with _client() as client:
        return await _resolve_with(client, standard_name, current_version)


async def resolve_many(items: list, on_item=None) -> dict:
    """批量查找：共用單一連線並在請求間留間隔（政府網站對密集請求會斷線）。"""
    out = {}
    if not items:
        return out

    async with _client() as client:
        for idx, it in enumerate(items):
            key = it["key"]
            try:
                result = await _resolve_with(
                    client, it.get("standard_name") or "", it.get("current_version") or ""
                )
            except Exception as e:
                result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            out[key] = result
            if on_item is not None:
                try:
                    on_item(key, it, result)
                except Exception as cb_err:  # 回呼錯誤不應中斷整批
                    logger.warning("on_item 回呼錯誤（%s）: %s", key, cb_err)
            if idx < len(items) - 1:
                await asyncio.sleep(REQUEST_INTERVAL)
    return out
