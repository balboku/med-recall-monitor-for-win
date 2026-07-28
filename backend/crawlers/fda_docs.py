"""FDA 指引與 CFR 法規版本追蹤（R401 / R402）。

R401（FDA / USP）與 R402（FDA Guidance）性質不同，分別處理：

  1. FDA Guidance（R402）
     來源：FDA 官方指引資料集
     `https://www.fda.gov/files/api/datatables/static/search-for-guidance.json`
     （純 HTTP、免驗證，約 2,800 份指引，含發布日期與 Final/Draft 狀態）
     版本概念：**發布日期（issue date）＋ Final/Draft 狀態**。

     註：原 fda_guidance.py 使用的
     `api.fda.gov/other/historicaldocument.json?search=openfda.type:guidance`
     已回傳 404（"No matches found"），該端點並不存在指引資料。

  2. 21 CFR（R401）
     來源：eCFR API `https://www.ecfr.gov/api/versioner/v1/versions/title-{title}.json?part={part}`
     版本概念：**該 part 所有條文中最新的 amendment_date**。

  3. 其餘（MIL-STD、USP）
     MIL-STD-105E 已被 ANSI/ASQ Z1.4 取代且不再改版；USP-NF 為訂閱制付費牆，
     無公開版本頁可比對，均標記為需人工確認。

標題比對的難處：
    FDA 的正式標題常帶收件對象後綴（"…: Guidance for Industry and FDA Staff"），
    公司清單多半省略；也有反過來把 "Guidance for Industry" 寫在前面的。
    故比對時同時使用「完整標題」與「去除前後綴的主體」兩種形式。
"""
import re
import difflib
import logging

import httpx

logger = logging.getLogger(__name__)

GUIDANCE_DATASET = "https://www.fda.gov/files/api/datatables/static/search-for-guidance.json"
GUIDANCE_SEARCH_PAGE = "https://www.fda.gov/regulatory-information/search-fda-guidance-documents"
ECFR_VERSIONS = "https://www.ecfr.gov/api/versioner/v1/versions/title-{title}.json?part={part}"
ECFR_PAGE = "https://www.ecfr.gov/current/title-{title}/part-{part}"

REQUEST_TIMEOUT = 90.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
MATCH_THRESHOLD = 0.85

# 收件對象後綴（"…: Guidance for Industry and FDA Staff"）
SUFFIX_RE = re.compile(
    r"\s*[:\-–]?\s*(final\s+)?guidance\s+(document\s+)?for\s+(industry|the\s+industry).*$"
    r"|\s*[:\-–]?\s*guidance\s+for\s+.*staff.*$"
    r"|\s*[:\-–]?\s*(draft|final)\s+guidance.*$"
    r"|\s*[:\-–]?\s*guidance\s+document.*$",
    re.IGNORECASE,
)
# 開頭的 "Guidance for Industry …" 前綴
PREFIX_RE = re.compile(
    r"^\s*(draft\s+|final\s+)?guidance\s+(document\s+)?(for\s+industry(\s+and\s+[\w\s]+staff)?)\s*[:\-–]?\s*",
    re.IGNORECASE,
)


def strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "")


def norm(s: str) -> str:
    """比對用正規化：去 HTML、解實體、僅保留英數字與空白。"""
    s = strip_html(s).lower()
    s = (s.replace("&amp;", "&").replace("&#039;", "'")
          .replace("&quot;", '"').replace("&nbsp;", " "))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def core_title(title: str) -> str:
    """取標題主體：移除 'Guidance for Industry…' 之類的前後綴後正規化。"""
    t = strip_html(title or "")
    t = PREFIX_RE.sub("", t)
    t = SUFFIX_RE.sub("", t)
    return norm(t.strip(" :-–"))


# ---------------------------------------------------------------------------
# FDA Guidance 資料集
# ---------------------------------------------------------------------------
def parse_guidance_dataset(rows: list) -> list:
    """把資料集轉為比對用結構。"""
    out = []
    for row in rows or []:
        raw_title = row.get("title", "")
        title = strip_html(raw_title).strip()
        if not title:
            continue
        m = re.search(r'href="([^"]+)"', raw_title)
        href = m.group(1) if m else ""
        if href.startswith("/"):
            href = "https://www.fda.gov" + href
        out.append({
            "title": title,
            "url": href,
            "issued": (row.get("field_issue_datetime") or "").strip(),
            "status": (row.get("field_final_guidance_1") or "").strip(),
            "norm": norm(title),
            "core": core_title(title),
        })
    return out


def match_guidance(company_title: str, docs: list):
    """在資料集中找出最相符的指引，回傳 (文件, 相似度)。"""
    cn, cc = norm(company_title), core_title(company_title)
    best, score = None, 0.0
    for d in docs:
        for a, b in ((cn, d["norm"]), (cc, d["core"])):
            if not a or not b:
                continue
            if a == b:
                return d, 1.0
            # 一方為另一方的開頭（公司清單常截斷標題）
            if len(a) >= 18 and (a.startswith(b) or b.startswith(a)):
                s = 0.97
            else:
                s = difflib.SequenceMatcher(None, a, b).ratio()
            if s > score:
                best, score = d, s
    return best, score


def judge_guidance(title: str, current_version: str, docs: list) -> dict:
    doc, score = match_guidance(title, docs)

    if not doc or score < MATCH_THRESHOLD:
        hint = f"最接近的候選為「{doc['title']}」（相似度 {score:.2f}）。" if doc else ""
        msg = ("無法在 FDA 官方指引清單中找到足夠相符的文件，可能是內部名稱與官方標題差異過大、"
               f"或該文件已撤回。{hint}請人工確認並更正名稱。")
        return _result("manual", "需人工確認", msg, False, "",
                       GUIDANCE_SEARCH_PAGE, "")

    shown = doc["issued"] + (f"（{doc['status']}）" if doc["status"] else "")
    found = doc["title"]
    url = doc["url"] or GUIDANCE_SEARCH_PAGE
    near = "" if score >= 0.99 else f"（比對相似度 {score:.2f}，官方標題：{found}）"

    draft_note = ""
    if doc["status"].lower() == "draft":
        draft_note = " 注意：此為 Draft 草案版，尚未定案。"

    cur = (current_version or "").strip()
    if not cur:
        msg = (f"已建立基準版本：FDA 現行版本發布日期為 {doc['issued']}"
               f"{'（' + doc['status'] + '）' if doc['status'] else ''}。"
               f"原「目前使用版本」為空白，請文管人員確認後填入。{near}{draft_note}")
        return _result("baseline", "已建立基準版本", msg, False, shown, url, found)

    if _norm_date(cur) == _norm_date(doc["issued"]):
        msg = f"目前使用版本與 FDA 現行發布日期 {doc['issued']} 一致，無需動作。{near}{draft_note}"
        return _result("valid", "無更新", msg, False, shown, url, found)

    msg = (f"FDA 現行版本發布日期為 {doc['issued']}，與目前使用版本（{cur}）不同，"
           f"表示此指引已改版，請取得最新版本。{near}{draft_note}")
    return _result("obsolete", "有更新 (已發布新版)", msg, True, shown, url, found)


def _norm_date(v: str) -> str:
    return re.sub(r"\D", "", v or "")


# ---------------------------------------------------------------------------
# 21 CFR（eCFR）
# ---------------------------------------------------------------------------
CFR_RE = re.compile(r"(\d+)\s*CFR\s*Part\s*(\d+)", re.IGNORECASE)


def parse_cfr_reference(title: str):
    """'21 CFR Part 820' -> ('21', '820')；非 CFR 回傳 None。"""
    m = CFR_RE.search(title or "")
    return (m.group(1), m.group(2)) if m else None


async def _judge_cfr(client: httpx.AsyncClient, title: str, current_version: str,
                     ref: tuple) -> dict:
    cfr_title, part = ref
    url = ECFR_PAGE.format(title=cfr_title, part=part)
    try:
        resp = await client.get(ECFR_VERSIONS.format(title=cfr_title, part=part))
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {"ok": False, "error": f"eCFR 查詢失敗：{type(e).__name__}: {e}"}

    dates = sorted({
        c.get("amendment_date") for c in data.get("content_versions", [])
        if c.get("amendment_date")
    })
    if not dates:
        msg = f"eCFR 未回傳 {cfr_title} CFR Part {part} 的修訂日期資訊，請人工確認。"
        return _result("unknown", "⚪ 無法判定", msg, False, "", url, title)

    latest = dates[-1]
    shown = latest
    cur = (current_version or "").strip()

    if not cur:
        msg = (f"已建立基準版本：{cfr_title} CFR Part {part} 於 eCFR 的最新條文修訂日期為 {latest}"
               f"（共 {len(dates)} 個修訂日期）。原「目前使用版本」為空白，請文管人員確認後填入。")
        return _result("baseline", "已建立基準版本", msg, False, shown, url, title)

    if _norm_date(cur) == _norm_date(latest):
        msg = f"目前使用版本與 eCFR 最新修訂日期 {latest} 一致，無需動作。"
        return _result("valid", "無更新", msg, False, shown, url, title)

    msg = (f"{cfr_title} CFR Part {part} 於 eCFR 的最新條文修訂日期為 {latest}，"
           f"與目前使用版本（{cur}）不同，請確認條文異動內容。")
    return _result("obsolete", "有更新 (條文已修訂)", msg, True, shown, url, title)


# ---------------------------------------------------------------------------
# 無公開版本來源者
# ---------------------------------------------------------------------------
MANUAL_HINTS = (
    (r"MIL-?STD",
     "MIL-STD-105E 已由 ANSI/ASQ Z1.4 取代多年，屬不再改版的歷史標準，"
     "無官方版本頁可自動比對，請人工確認是否改採現行標準。"),
    (r"\bUSP\b",
     "USP-NF 為訂閱制付費資料庫，無公開的現行版本頁可自動比對，"
     "請人工至 USP-NF 訂閱網站確認現行版本。"),
)


def _manual_hint(title: str):
    for pattern, hint in MANUAL_HINTS:
        if re.search(pattern, title or "", re.IGNORECASE):
            return hint
    return None


def _result(status, label, message, has_update, shown,
            source_url="", found_title=""):
    return {
        "ok": True,
        "source_url": source_url,
        "found_title": found_title,
        "now_status": "",
        "now_title": found_title,
        "now_stage": "",
        "now_year": shown,
        "now_list": ([{"status": "", "title": found_title}] if found_title else []),
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


# ---------------------------------------------------------------------------
# 對外介面
# ---------------------------------------------------------------------------
def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


async def fetch_guidance_docs(client: httpx.AsyncClient) -> list:
    resp = await client.get(GUIDANCE_DATASET)
    resp.raise_for_status()
    return parse_guidance_dataset(resp.json())


async def _resolve_with(client, title, current_version, docs):
    hint = _manual_hint(title)
    if hint:
        return _result("manual", "需人工確認", hint, False, "", "", "")

    ref = parse_cfr_reference(title)
    if ref:
        return await _judge_cfr(client, title, current_version, ref)

    if docs is None:
        return _result("manual", "需人工確認",
                       "FDA 指引清單取得失敗，無法比對版本。", False, "",
                       GUIDANCE_SEARCH_PAGE, "")
    return judge_guidance(title, current_version, docs)


async def resolve_source_url(standard_name: str, current_version: str = "") -> dict:
    """查詢單一 FDA 指引／CFR 的現行版本與判讀。"""
    async with _client() as client:
        docs = None
        if not _manual_hint(standard_name) and not parse_cfr_reference(standard_name):
            try:
                docs = await fetch_guidance_docs(client)
            except Exception as e:
                logger.warning("[fda_docs] 指引清單取得失敗: %s", e)
        try:
            return await _resolve_with(client, standard_name, current_version, docs)
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}


async def resolve_many(items: list, on_item=None) -> dict:
    """批量查找：指引資料集整批只下載一次。"""
    out = {}
    if not items:
        return out

    async with _client() as client:
        docs = None
        need_docs = any(
            not _manual_hint(it.get("standard_name") or "")
            and not parse_cfr_reference(it.get("standard_name") or "")
            for it in items
        )
        if need_docs:
            try:
                docs = await fetch_guidance_docs(client)
                logger.info("[fda_docs] FDA 指引資料集共 %d 份文件", len(docs))
            except Exception as e:
                logger.warning("[fda_docs] 指引清單取得失敗: %s", e)

        for it in items:
            key = it["key"]
            try:
                result = await _resolve_with(
                    client, it.get("standard_name") or "",
                    it.get("current_version") or "", docs,
                )
            except Exception as e:
                result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            out[key] = result
            if on_item is not None:
                try:
                    on_item(key, it, result)
                except Exception as cb_err:  # 回呼錯誤不應中斷整批
                    logger.warning("on_item 回呼錯誤（%s）: %s", key, cb_err)
    return out
