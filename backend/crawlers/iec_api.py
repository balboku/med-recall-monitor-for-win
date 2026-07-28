"""IEC webstore 標準版本追蹤（純 HTTP，不需虛擬瀏覽器）。

背景：
    ISO 官網（www.iso.org）受 Cloudflare 防護，必須以 nodriver 虛擬瀏覽器取得頁面
    （見 iso_browser.py）。IEC webstore 則無此限制，且其前端搜尋所使用的後端
    `https://webstore-search-api.iec.ch/api/search` 可直接以 POST 呼叫、免驗證，
    回傳的 `_source.lifecycle` 已是「整個標準家族」的結構化清單：

        [{"reference": "IEC 62366-1:2015",            "status": "PUBLISHED", "edition": "1.0", "id": "21863"},
         {"reference": "IEC 62366-1:2015/COR1:2016",  "status": "PUBLISHED", ...},
         {"reference": "IEC 62366-1:2015/AMD1:2020",  "status": "PUBLISHED", ...},
         {"reference": "IEC 62366-1", "in_progress": "true", "status": "PREPARING", "edition": "2.0", ...}]

    因此不需要解析 HTML，也不需要瀏覽器，速度與穩定性都遠優於 ISO 流程。

狀態對應（IEC → ISO 判定規則的 Life cycle 區塊）：
    PUBLISHED                      → NOW（現行有效的家族文件：主標準＋AMD/COR/ISH）
    REVISED / REPLACED / WITHDRAWN → Previously（已被改版或撤銷）
    PREPARING（in_progress）       → 研擬中的新版，另外以 newer_* 欄位呈現，不列入 NOW

對外介面（async，可直接在 FastAPI / 爬蟲的事件迴圈中呼叫）：
    resolve_source_url(standard_name, current_version="")  → 單筆查找與版本判讀
    resolve_many(items, on_item=None)                      → 批量查找（共用連線）
"""
import re
import logging
import httpx

from crawlers.standards_common import (
    detect_doc_type,
    judge_update,
    norm_doc,
    collect_db_docs,
    extract_base_number,
    normalize_base_number,
    IEC_REPACKAGED_FORMS,
)

logger = logging.getLogger(__name__)

SEARCH_API = "https://webstore-search-api.iec.ch/api/search"
PUBLICATION_URL = "https://webstore.iec.ch/publication/{id}"
REQUEST_TIMEOUT = 40.0

# IEC 生命週期狀態 → 是否為現行有效
NOW_STATUSES = ("PUBLISHED",)
PREVIOUS_STATUSES = ("REVISED", "REPLACED", "WITHDRAWN")


def _search_payload(query: str, size: int = 40) -> dict:
    """IEC webstore 前端送給搜尋 API 的 JSON 主體（欄位取自其搜尋頁的 Alpine.js 設定）。"""
    return {
        "query": query,
        "mode": "FULL",
        "language": "en",
        "validOnly": False,   # 需要一併取得已撤銷/已改版者，才能判定 Previously
        "showTrf": False,
        "from": 0,
        "size": size,
        "terms": [],
        "dateRanges": [],
        "publicationIds": [],
    }


def _search_query(standard_name: str) -> str:
    """由法規名稱組出送往 IEC 搜尋 API 的查詢字串。

    IEC 搜尋對「IEC/TR 80002-1」這類含斜線前綴的字串會查無結果（官網寫法是空白分隔的
    「IEC TR 80002-1」），改以「純編號」查詢最穩定，再於結果中做精確比對。
    """
    base = extract_base_number(standard_name) or standard_name
    # 去除 head 與 TS/TR/PAS 前綴，只留編號（例如 'IEC/TS 60601-4-2' -> '60601-4-2'）
    m = re.search(r"(\d+(?:-\d+)*)", base)
    return m.group(1) if m else base.strip()


async def _post_search(client: httpx.AsyncClient, query: str) -> list:
    """呼叫 IEC 搜尋 API，回傳 hits 清單（失敗時丟出例外）。"""
    resp = await client.post(SEARCH_API, json=_search_payload(query))
    resp.raise_for_status()
    data = resp.json()
    return (data.get("primary") or {}).get("hits", {}).get("hits", []) or []


def pick_target(hits: list, standard_name: str):
    """從搜尋結果中挑出與查詢編號『精確相符』的標準家族。

    必要性：查詢「60601-1」時 IEC 會一併回傳 60601-1-2、60601-1-3 等部號標準，
    以及「IEC 60601-1:2026 SER」這種把整個系列包在一起販售的商品，都必須排除。

    排序優先序：現行版(PUBLISHED) > 具生命週期資料 > 出版日期較新。
    回傳 hit 的 _source dict，或 None。
    """
    want = normalize_base_number(extract_base_number(standard_name))
    if not want:
        return None

    candidates = []
    for h in hits:
        src = h.get("_source") or {}
        ref = src.get("reference") or ""
        if normalize_base_number(extract_base_number(ref)) != want:
            continue
        # 排除 SER / RLV / CMV 等「重新包裝」商品，它們不是獨立的規範性文件
        if detect_doc_type(ref, flavor="iec") in IEC_REPACKAGED_FORMS:
            continue
        candidates.append((
            1 if src.get("status") in NOW_STATUSES else 0,
            len(src.get("lifecycle") or []),
            src.get("publication_date") or "",
            src,
        ))

    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], c[1], c[2]), reverse=True)
    return candidates[0][3]


def parse_edition(value) -> tuple:
    """將 IEC 的 edition 字串（'3.0'、'3.2'、'1'）解析為 (主版, 次版) 數字組，無法解析時回傳 ()。

    IEC 以 edition 表達版本：主版遞增代表「主標準改版」，次版遞增代表「已併入修正案」
    （例：ed 3.0 為 2005 年本體，ed 3.2 為本體＋AMD1＋AMD2 的合併版）。
    """
    m = re.match(r"\s*(\d+)(?:\.(\d+))?", str(value or ""))
    if not m:
        return ()
    return (int(m.group(1)), int(m.group(2) or 0))


def build_lifecycle(source: dict) -> dict:
    """將 IEC 的 `_source.lifecycle` 轉為與 ISO 相同結構的 Life cycle dict，
    使其可直接餵給共用的 judge_update()。

    除了 ISO 既有的 now_list / previously（(status, title) 組），另保留 now_entries /
    prev_entries（含 edition 的原始明細），供 IEC 專屬的 edition 版本判定使用。
    """
    info = {
        "now_status": "", "now_title": "", "now_stage": "",
        "now_list": [], "previously": [],
        "now_entries": [], "prev_entries": [],
        "newer_title": "", "newer_year": "", "newer_kind": "", "newer_url": "",
    }

    entries = source.get("lifecycle") or []
    if not entries:
        # 家族只有單一出版品時 IEC 不提供 lifecycle，以該筆自身作為 NOW
        entries = [{
            "reference": source.get("reference") or "",
            "status": source.get("status") or "",
            "edition": source.get("edition") or "",
            "publication_date": source.get("publication_date") or "",
            "id": source.get("id") or "",
        }]

    for e in entries:
        ref = (e.get("reference") or "").strip()
        if not ref:
            continue
        status = (e.get("status") or "").upper()

        # 研擬中的新版：不列入 NOW，改以 newer_* 呈現（供提前預警）
        if status == "PREPARING" or str(e.get("in_progress", "")).lower() == "true":
            if not info["newer_title"]:
                edition = e.get("edition") or ""
                info["newer_title"] = f"{ref}（Edition {edition}）" if edition else ref
                info["newer_kind"] = "Under development"
                info["newer_year"] = (e.get("forecast_pub_date") or "")[:4]
                if e.get("id"):
                    info["newer_url"] = PUBLICATION_URL.format(id=e["id"])
                info["now_stage"] = e.get("stage") or ""
            continue

        # 重新包裝的商品形式（SER/RLV/CMV…）不是獨立文件，排除以免污染家族比對
        if detect_doc_type(ref, flavor="iec") in IEC_REPACKAGED_FORMS:
            continue

        label = status.capitalize()
        entry = {
            "reference": ref,
            "status": label,
            "edition": e.get("edition") or "",
            "publication_date": e.get("publication_date") or "",
            "id": e.get("id") or "",
        }
        if status in NOW_STATUSES:
            info["now_list"].append((label, ref))
            info["now_entries"].append(entry)
        elif status in PREVIOUS_STATUSES:
            info["previously"].append((label, ref))
            info["prev_entries"].append(entry)

    # NOW 的代表文件：優先取「非附屬文件」的主標準本體
    for st, ref in info["now_list"]:
        if detect_doc_type(ref, flavor="iec") not in ("AMD", "COR", "ISH", "ADD"):
            info["now_status"], info["now_title"] = st, ref
            break
    if not info["now_title"] and info["now_list"]:
        info["now_status"], info["now_title"] = info["now_list"][0]

    return info


def _entry_years(reference: str) -> set:
    """取出參照字串中所有年份，例如 'IEC 60601-1-6:2010+AMD1:2013+AMD2:2020 CSV' → {2010, 2013, 2020}。"""
    return {int(y) for y in re.findall(r":(\d{4})", reference or "")}


def latest_body_entry(now_entries: list):
    """取出 NOW 家族中「最完整的本體文件」（edition 最高的主標準或合併版）。

    只考慮本體類文件，排除掛在其下的 AMD/COR/ISH，否則會取到「合併版的勘誤單」
    而非合併版本身。回傳 entry dict 或 None。
    """
    body = [
        e for e in now_entries
        if detect_doc_type(e["reference"], flavor="iec") not in ("AMD", "COR", "ISH", "ADD")
    ] or list(now_entries)
    if not body:
        return None
    return max(
        body,
        key=lambda e: (parse_edition(e["edition"]) or (0, 0), e.get("publication_date") or ""),
    )


def match_user_entry(standard_name: str, current_version: str, lc: dict):
    """在 IEC 生命週期中找出「使用者手上這份文件」對應的項目。

    IEC 的參照年份是「基礎版年份」，修正案另帶自己的年份（ed 3.2 寫作
    'IEC 60601-1:2005+AMD1:2012+AMD2:2020 CSV'）。因此文管紀錄的「2020」可能指的是
    修正案年份而非基礎版年份，不能直接拿年份和主標準比較，否則會出現
    「持有 2023 版卻被要求更新到 2017 版」這種顛倒的判讀。

    比對順序：
      1. 完整字串精確比對（正規化後）
      2. 年份比對：命中該年份的項目中取 edition 最高者
         （同一年份可能同時對應修正案與合併版，合併版才是文管實際使用的文件）
    回傳 (entry, 是否落在 NOW)；找不到時回傳 (None, False)。
    """
    entries = [(e, True) for e in lc.get("now_entries", [])] + \
              [(e, False) for e in lc.get("prev_entries", [])]
    if not entries:
        return None, False

    uv = (current_version or "").strip()
    user_doc = f"{standard_name}:{uv}" if uv else (standard_name or "")
    un = norm_doc(user_doc)

    for entry, is_now in entries:
        if norm_doc(entry["reference"]) == un:
            return entry, is_now

    ym = re.search(r"(\d{4})", uv)
    if not ym:
        return None, False
    year = int(ym.group(1))
    matches = [(e, n) for e, n in entries if year in _entry_years(e["reference"])]
    if not matches:
        return None, False
    matches.sort(key=lambda p: (parse_edition(p[0]["edition"]) or (0, 0),
                                p[0].get("publication_date") or ""))
    return matches[-1]


def judge_update_iec(standard_name: str, current_version: str, lc: dict,
                     db_docs=None) -> dict:
    """依 IEC 的 edition 版本模型判定更新狀態，輸出與 ISO 規則一致的狀態字串。

    對應關係（狀態欄位輸出值沿用「ISO 法規版本更新判定邏輯規則」）：
        edition 相同                    → 無更新
        主版相同、次版落後（缺修正案）  → 有更新 (缺少 AMD / COR / ISH)
        主版落後（基礎標準已改版）      → 有更新 (主標準已改版)
        持有已失效的修正案/勘誤         → 有更新 (舊版已整合)
    無法對應到任何生命週期項目時，回退至共用的字串比對判定（judge_update）。
    """
    db_docs = db_docs or set()
    entry, is_now = match_user_entry(standard_name, current_version, lc)
    if entry is None:
        # 找不到對應項目：交由共用邏輯以 NOW/Previously 字串與年份回退判定
        return judge_update(standard_name, current_version, lc, db_docs, flavor="iec")

    now_entries = lc.get("now_entries", [])
    now_editions = [parse_edition(e["edition"]) for e in now_entries]
    now_editions = [ed for ed in now_editions if ed]
    now_max = max(now_editions) if now_editions else ()
    user_ed = parse_edition(entry["edition"])

    # NOW 的主標準本體（非附屬文件），用於提示文字
    now_main = ""
    for e in now_entries:
        if detect_doc_type(e["reference"], flavor="iec") not in ("AMD", "COR", "ISH", "ADD"):
            now_main = e["reference"]
            break
    if not now_main and now_entries:
        now_main = now_entries[0]["reference"]

    # NOW 家族中最完整的本體文件，作為建議取得的目標
    _latest = latest_body_entry(now_entries)
    now_latest = _latest["reference"] if _latest else ""

    user_type = detect_doc_type(entry["reference"], flavor="iec")

    # 情境三B/C：持有已失效的修正案／勘誤 → 已整合至新版主標準
    if not is_now and user_type in ("AMD", "ADD", "COR", "ISH"):
        kind = "修正案" if user_type in ("AMD", "ADD") else "技術勘誤"
        return {
            "judge_statuses": ["integrated"],
            "judge_categories": ["has_update"],
            "judge_status": "integrated",
            "judge_label": "有更新",
            "judge_message": (
                f"您持有的舊版{kind} {entry['reference']} 已失效，相關內容已整合至最新版 "
                f"{now_latest or now_main or '（最新版）'}，請直接取得最新版本。"),
            "has_update": True,
            "now_main": now_main,
            "missing_types": [], "missing_supplements": [],
        }

    if not user_ed or not now_max:
        return judge_update(standard_name, current_version, lc, db_docs, flavor="iec")

    # 已是最新 edition → 無更新
    if user_ed >= now_max:
        return {
            "judge_statuses": ["valid"],
            "judge_categories": ["no_update"],
            "judge_status": "valid",
            "judge_label": "無更新",
            "judge_message": (
                f"您持有的 {entry['reference']}（Edition {entry['edition']}）"
                f"即為 IEC 官網現行最新版本，文件齊全，無需動作。"),
            "has_update": False,
            "now_main": now_main,
            "missing_types": [], "missing_supplements": [],
        }

    # 主版落後 → 基礎標準已改版
    if user_ed[0] < now_max[0]:
        return {
            "judge_statuses": ["obsolete"],
            "judge_categories": ["has_update"],
            "judge_status": "obsolete",
            "judge_label": "有更新",
            "judge_message": (
                f"您持有的 {entry['reference']}（Edition {entry['edition']}）已被改版，"
                f"請更新至最新版 {now_latest or now_main}"
                f"（Edition {'.'.join(str(x) for x in now_max)}）。"),
            "has_update": True,
            "now_main": now_main,
            "missing_types": [], "missing_supplements": [],
        }

    # 主版相同、次版落後 → 基礎標準未變，缺的是修正案／勘誤
    missing = []
    for e in now_entries:
        ref = e["reference"]
        if detect_doc_type(ref, flavor="iec") not in ("AMD", "COR", "ISH", "ADD"):
            continue
        if norm_doc(ref) not in db_docs:
            missing.append(ref)

    miss_types = []
    for ref in missing:
        dt = detect_doc_type(ref, flavor="iec")
        lab = dt if dt in ("COR", "ISH") else "AMD"
        if lab not in miss_types:
            miss_types.append(lab)
    types_str = " / ".join(miss_types) if miss_types else "AMD"

    return {
        "judge_statuses": ["missing_supplement"],
        "judge_categories": ["missing"],
        "judge_status": "missing_supplement",
        "judge_label": f"缺少（{types_str} 等附屬文件）",
        "judge_message": (
            f"基礎標準 {now_main} 本體未改版，但您持有的 Edition {entry['edition']} "
            f"尚未併入後續修正案（官網現行為 Edition {'.'.join(str(x) for x in now_max)}）。"
            + (f"缺少：{', '.join(missing)}。" if missing else "")
            + f"建議取得合併版 {now_latest}。"),
        "has_update": True,
        "now_main": now_main,
        "missing_types": miss_types,
        "missing_supplements": missing,
    }


def _build_not_found_result(standard_name: str, current_version: str) -> dict:
    """情境一：IEC 官網搜尋完全查無此標準 → 可能已作廢，需人工確認。"""
    doc_type = detect_doc_type(
        f"{standard_name}:{current_version}" if current_version else standard_name,
        flavor="iec",
    )
    msg = (
        "系統無法在 IEC 官網找到此標準的任何現行或歷史紀錄。"
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


def _build_result(source: dict, lc: dict, standard_name: str, current_version: str,
                  db_docs=None) -> dict:
    """組裝對外回傳 dict（欄位與 iso_browser 一致，以便共用回寫與前端顯示邏輯）。"""
    verdict = judge_update_iec(standard_name, current_version, lc, db_docs)
    doc_type = detect_doc_type(
        f"{standard_name}:{current_version}" if current_version else standard_name,
        flavor="iec",
    )

    now_title = lc["now_title"]

    # 「最新同步版本」顯示字串：取 NOW 家族中最完整本體文件的「版本部分」，而非單一年份。
    #
    # IEC 的版本無法用一個年份表達：主標準年份是「基礎版年份」，修正案各自帶年份，
    # 合併版寫作 'IEC 60529:1989+AMD1:1999+AMD2:2013 CSV'。若只取其中一個年份都會誤導 ——
    #   只取主標準年份 → IEC 60601-1-6 會顯示「當前 2020 / 最新 2010」，看似退版；
    #   只取最大年份   → IEC 60529 會顯示「當前 1989 / 最新 2013」，會被誤讀為主規範已改版成 2013。
    # 因此改為輸出自帶語意的完整版本字串（如 '1989+AMD1:1999+AMD2:2013 CSV'），
    # 一眼即可看出「基礎版仍是 1989，後續增加了兩個修正案」。
    latest_entry = latest_body_entry(lc.get("now_entries", []))
    latest_ref = latest_entry["reference"] if latest_entry else now_title
    now_year = latest_ref.split(":", 1)[1].strip() if ":" in latest_ref else ""

    source_url = PUBLICATION_URL.format(id=source["id"]) if source.get("id") else ""

    return {
        "ok": True,
        "source_url": source_url,
        "found_title": source.get("reference") or "",
        "now_status": lc["now_status"],
        "now_title": now_title,
        "now_stage": lc["now_stage"],
        "now_year": now_year,
        "now_list": [{"status": s, "title": t} for s, t in lc["now_list"]],
        "previously": [{"status": s, "title": t} for s, t in lc["previously"]],
        "newer_title": lc["newer_title"],
        "newer_kind": lc["newer_kind"],
        "newer_year": lc["newer_year"],
        "newer_url": lc["newer_url"],
        "edition": source.get("edition") or "",
        "doc_type": doc_type,
        "judge_statuses": verdict.get("judge_statuses") or [verdict["judge_status"]],
        "judge_categories": verdict.get("judge_categories") or [],
        "judge_status": verdict["judge_status"],
        "judge_label": verdict["judge_label"],
        "judge_message": verdict["judge_message"],
        "now_main": verdict["now_main"],
        "missing_types": verdict.get("missing_types", []),
        "missing_supplements": verdict.get("missing_supplements", []),
        "has_update": verdict["has_update"],
        "reasons": [verdict["judge_message"]],
    }


async def _resolve_with(client: httpx.AsyncClient, standard_name: str,
                        current_version: str) -> dict:
    """以既有 HTTP client 解析單一 IEC 標準。"""
    query = _search_query(standard_name)
    try:
        hits = await _post_search(client, query)
    except Exception as e:
        return {"ok": False, "error": f"IEC 搜尋 API 失敗：{type(e).__name__}: {e}", "query": query}

    if not hits:
        return _build_not_found_result(standard_name, current_version)

    source = pick_target(hits, standard_name)
    if not source:
        logger.info(
            "[iec_api] 搜尋 %r 有結果但無精確匹配（候選: %s），視為查無此標準（可能已作廢）。",
            query, [(h.get("_source") or {}).get("reference") for h in hits[:4]],
        )
        return _build_not_found_result(standard_name, current_version)

    lc = build_lifecycle(source)
    db_docs = collect_db_docs(standard_name)
    return _build_result(source, lc, standard_name, current_version, db_docs)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            ),
            "Content-Type": "application/json",
        },
    )


async def resolve_source_url(standard_name: str, current_version: str = "") -> dict:
    """搜尋 IEC 官網並解析該標準的生命週期，回傳官方網址與版本判讀。"""
    async with _client() as client:
        return await _resolve_with(client, standard_name, current_version)


async def resolve_many(items: list, on_item=None) -> dict:
    """批量查找：共用同一個 HTTP 連線依序處理整批。

    items: [{"key": <任意鍵>, "standard_name": str, "current_version": str}, ...]
    on_item: 選填回呼 on_item(key, item, result)，每處理完一筆即呼叫（供即時進度/寫回）。
    回傳 {key: result_dict}。單筆失敗不影響其餘項目。
    """
    out = {}
    if not items:
        return out
    async with _client() as client:
        for it in items:
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
    return out
