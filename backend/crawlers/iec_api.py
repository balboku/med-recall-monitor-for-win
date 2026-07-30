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
    build_missing_main_entries,
    build_under_revision_entries,
    combine_judge_entries,
    norm_doc,
    collect_db_docs,
    extract_base_number,
    normalize_base_number,
    IEC_REPACKAGED_FORMS,
    SUPPLEMENT_TYPES,
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
        if detect_doc_type(ref, flavor="iec") not in SUPPLEMENT_TYPES:
            info["now_status"], info["now_title"] = st, ref
            break
    if not info["now_title"] and info["now_list"]:
        info["now_status"], info["now_title"] = info["now_list"][0]

    return info


# 附屬文件元件（AMD1:2012、Amd 1:2020、COR1:2019…），正規化為 'amd12012' 形式後比對
SUPPLEMENT_TOKEN_RE = re.compile(r"(amd|cor|ish|add)\s*(\d+)\s*:\s*(\d{4})", re.IGNORECASE)


def supplement_tokens(text: str) -> list:
    """取出字串中的附屬文件元件（依出現順序）。

    'IEC 60529:1989+AMD2:2013+COR1:2019' → ['amd22013', 'cor12019']
    """
    return [f"{m.group(1).lower()}{m.group(2)}{m.group(3)}"
            for m in SUPPLEMENT_TOKEN_RE.finditer(text or "")]


def version_part(reference: str) -> str:
    """取參照字串冒號後的版本部分：'IEC 60529:1989+AMD1:1999 CSV' → '1989+AMD1:1999 CSV'。"""
    return reference.split(":", 1)[1].strip() if ":" in (reference or "") else ""


def base_part(version: str) -> str:
    """取版本字串的基礎版部分（第一個 '+' 或 '/' 之前）：'1989+AMD2:2013' → '1989'。"""
    return re.split(r"[+/]", (version or "").strip(), 1)[0].strip()


def _year(text) -> int:
    """取字串中的第一個西元年份（沒有則回傳 0）。'1998-01' → 1998。"""
    m = re.search(r"(\d{4})", str(text or ""))
    return int(m.group(1)) if m else 0


def parse_holding(standard_name: str, current_version: str) -> dict:
    """把文管紀錄的「目前使用版本」解析成 IEC 的持有內容模型。

    IEC 的 '+' 與 '/' 語意不同（見 IEC 規則第 3 節），正規化比對會把兩者一併抹除，
    因此必須在比對前先分辨：

        'attached'  '2015/AMD1:2020'   斜線掛載 → 持有的是那份修正案／勘誤本身
        'chain'     '2006+Amd1:2015'   加號連寫 → 本體已併入這些修正案的合併版
                                       （官方寫法會再標註 CSV，文管紀錄常省略，語意相同）
        'plain'     '2020'             只有版本年份，未標註任何附屬文件
    """
    uv = (current_version or "").strip()
    user_doc = f"{standard_name}:{uv}" if uv else (standard_name or "")
    tokens = supplement_tokens(uv)
    if detect_doc_type(user_doc, flavor="iec") in SUPPLEMENT_TYPES:
        kind = "attached"
    elif tokens:
        kind = "chain"
    else:
        kind = "plain"
    return {"kind": kind, "doc": user_doc, "version": uv,
            "base": base_part(uv), "year": _year(uv), "tokens": tokens}


def latest_body_entry(now_entries: list):
    """取出 NOW 家族中「最完整的本體文件」（edition 最高的主標準或合併版）。

    只考慮本體類文件，排除掛在其下的 AMD/COR/ISH，否則會取到「合併版的勘誤單」
    而非合併版本身。回傳 entry dict 或 None。
    """
    body = [
        e for e in now_entries
        if detect_doc_type(e["reference"], flavor="iec") not in SUPPLEMENT_TYPES
    ] or list(now_entries)
    if not body:
        return None
    return max(
        body,
        key=lambda e: (parse_edition(e["edition"]) or (0, 0), e.get("publication_date") or ""),
    )


def match_user_entry(standard_name: str, current_version: str, lc: dict, holding: dict = None):
    """在 IEC 生命週期中找出「使用者手上這份文件」對應的項目。

    IEC 的參照年份是「基礎版年份」，修正案另帶自己的年份（ed 3.2 寫作
    'IEC 60601-1:2005+AMD1:2012+AMD2:2020 CSV'）。因此文管紀錄的「2020」可能指的是
    修正案年份而非基礎版年份，不能直接拿年份和主標準比較，否則會出現
    「持有 2023 版卻被要求更新到 2017 版」這種顛倒的判讀。

    比對順序：
      1. 完整字串精確比對（正規化後）。合併版寫法（'+' 連寫）不採計「斜線掛載的
         修正案本身」，否則 '2006+Amd1:2015' 會比對到 'IEC 62304:2006/AMD1:2015'
         而被判成「只持有修正案、缺主標準本體」。
      2. 合併版寫法：以「基礎版＋附屬文件元件集合」比對本體級項目，
         即使文管紀錄漏標 CSV 也能對應到官方的合併版（例：'2006+Amd1:2015'
         → 'IEC 62304:2006+AMD1:2015 CSV'）。

    刻意「不」再以單一年份猜測對應項目：同一年份可能是修正案年份也可能是合併版年份，
    猜錯會把「只持有修正案」誤判為「持有最新合併版」。比對不到時一律回傳 (None, False)，
    由 judge_update_iec() 依年份關係判定為有更新或無法判定（需人工確認）。

    回傳 (entry, 是否落在 NOW)；找不到時回傳 (None, False)。
    """
    entries = [(e, True) for e in lc.get("now_entries", [])] + \
              [(e, False) for e in lc.get("prev_entries", [])]
    if not entries:
        return None, False

    holding = holding or parse_holding(standard_name, current_version)
    un = norm_doc(holding["doc"])

    for entry, is_now in entries:
        if norm_doc(entry["reference"]) != un:
            continue
        if holding["kind"] == "chain" and \
                detect_doc_type(entry["reference"], flavor="iec") in SUPPLEMENT_TYPES:
            continue
        return entry, is_now

    if holding["kind"] != "chain":
        return None, False

    want = set(holding["tokens"])
    candidates = [
        (e, n) for e, n in entries
        if detect_doc_type(e["reference"], flavor="iec") not in SUPPLEMENT_TYPES
        and base_part(version_part(e["reference"])) == holding["base"]
        and set(supplement_tokens(e["reference"])) == want
    ]
    if not candidates:
        return None, False
    candidates.sort(key=lambda p: (parse_edition(p[0]["edition"]) or (0, 0),
                                   p[0].get("publication_date") or ""))
    return candidates[-1]


def missing_family_supplements(holding: dict, now_entries: list, db_docs) -> list:
    """比對「官網現行合併版所含的附屬文件」與「持有版本字串＋資料庫收錄」，列出缺少的項目。

    用於文管紀錄以 '+' 連寫、但湊不出任何一個官方合併版的情形
    （例：持有 '1989+AMD2:2013+COR1:2019'，官網現行合併版為 '1989+AMD1:1999+AMD2:2013 CSV'
    → 缺少 AMD1:1999）。回傳官網的參照字串清單。
    """
    latest = latest_body_entry(now_entries)
    if not latest:
        return []
    have = set(holding.get("tokens") or [])
    ref_by_token = {}
    for e in now_entries:
        if detect_doc_type(e["reference"], flavor="iec") not in SUPPLEMENT_TYPES:
            continue
        toks = supplement_tokens(e["reference"])
        if toks:
            ref_by_token.setdefault(toks[-1], e["reference"])
    missing = []
    for token in supplement_tokens(latest["reference"]):
        if token in have:
            continue
        ref = ref_by_token.get(token)
        if ref and norm_doc(ref) in (db_docs or set()):
            continue
        missing.append(ref or token.upper())
    return missing


def _missing_supplement_entry(missing: list, now_main: str, now_latest: str,
                              lead_message: str) -> dict:
    """組出子判斷 B 的「缺少（… 等附屬文件）」結果（缺件類型由官網實際缺項動態組出）。"""
    miss_types = []
    for ref in missing:
        dt = detect_doc_type(ref, flavor="iec")
        lab = dt if dt in ("COR", "ISH") else "AMD"
        if lab not in miss_types:
            miss_types.append(lab)
    types_str = " / ".join(miss_types) if miss_types else "AMD"
    return {
        "judge_status": "missing_supplement",
        "judge_category": "missing",
        "missing_types": miss_types,
        "missing_supplements": missing,
        "judge_label": f"缺少（{types_str} 等附屬文件）",
        "judge_message": (
            lead_message
            + (f"缺少：{', '.join(missing)}。" if missing else "")
            + (f"建議取得合併版 {now_latest}。" if now_latest else "")),
    }


def judge_update_iec(standard_name: str, current_version: str, lc: dict,
                     db_docs=None) -> dict:
    """依 IEC 的 edition 版本模型判定更新狀態，輸出與共用規則一致的狀態字串。

    判定依「IEC 法規版本更新判定邏輯規則」第 4.3 節（狀態用詞見「法規版本判定通用規則」
    第 3 節：「有更新」不細分原因，細節寫在提示訊息；「缺少」必須指明缺什麼）：

        使用者 edition ≧ NOW 最高 edition → no_update  無更新
        主版相同、次版落後                → missing    缺少（AMD / COR / ISH 等附屬文件）
        主版落後（基礎標準已改版）        → has_update  有更新
        持有已失效的 AMD / COR / ISH      → has_update  有更新

    並依通用規則第 2 節，與版本落點（A）互相獨立地一併輸出：
        C. 改版預告 → 修訂中（IEC 的 `in_progress` / `PREPARING` 研擬中新版）
        B. 家族完整性 → 缺少（主標準本體）（持有的是附屬文件，但資料庫沒有主標準）
    多個狀態以「、」串接，順序固定為 A → C → B。

    比對不到任何生命週期項目時（見 match_user_entry 的說明）：
        持有年份 == 官網主標準基礎版年份 或 較舊 → 回退至共用判定（judge_update）
        持有年份 > 官網主標準基礎版年份         → ⚪ 無法判定：該年份是某份修正案的年份，
            無從得知文管實際持有的是合併版還是單一修正案，需人工確認
        以 '+' 連寫但湊不出任何官方合併版      → 缺少（… 等附屬文件）：本體未改版，
            缺的是字串中沒列到的修正案
    """
    db_docs = db_docs or set()
    holding = parse_holding(standard_name, current_version)
    entry, is_now = match_user_entry(standard_name, current_version, lc, holding)

    now_entries = lc.get("now_entries", [])
    now_editions = [parse_edition(e["edition"]) for e in now_entries]
    now_editions = [ed for ed in now_editions if ed]
    now_max = max(now_editions) if now_editions else ()

    # NOW 的主標準本體（非附屬文件），用於提示文字
    now_main = ""
    for e in now_entries:
        if detect_doc_type(e["reference"], flavor="iec") not in SUPPLEMENT_TYPES:
            now_main = e["reference"]
            break
    if not now_main and now_entries:
        now_main = now_entries[0]["reference"]

    # NOW 家族中最完整的本體文件，作為建議取得的目標
    _latest = latest_body_entry(now_entries)
    now_latest = _latest["reference"] if _latest else ""

    if entry is None:
        return _judge_unmatched(standard_name, current_version, lc, db_docs,
                                holding, now_main, now_latest, now_entries)

    user_ed = parse_edition(entry["edition"])
    user_type = detect_doc_type(entry["reference"], flavor="iec")
    is_supplement = user_type in SUPPLEMENT_TYPES
    now_max_str = ".".join(str(x) for x in now_max) if now_max else ""

    # ---- 子判斷 A：這筆文件本身的 edition 是否落後 ----
    a_entries = []
    if not is_now and is_supplement:
        # 持有已失效的修正案／勘誤 → 內容已整合至新版
        kind = "修正案" if user_type in ("AMD", "ADD") else "技術勘誤"
        a_entries.append({
            "judge_status": "integrated",
            "judge_category": "has_update",
            "missing_types": [], "missing_supplements": [],
            "judge_label": "有更新",
            "judge_message": (
                f"您持有的舊版{kind} {entry['reference']} 已失效，相關內容已整合至最新版 "
                f"{now_latest or now_main or '（最新版）'}，請直接取得最新版本。"),
        })
    elif not user_ed or not now_max:
        # edition 缺漏而無法比對 → 回退至共用的字串／年份判定
        return judge_update(standard_name, current_version, lc, db_docs, flavor="iec")
    elif user_ed >= now_max:
        # 已是最新 edition → 無更新（合併版即已含後續修正案，故不再另查家族缺件）
        a_entries.append({
            "judge_status": "valid",
            "judge_category": "no_update",
            "missing_types": [], "missing_supplements": [],
            "judge_label": "無更新",
            "judge_message": (
                f"您持有的 {entry['reference']}（Edition {entry['edition']}）"
                f"即為 IEC 官網現行最新版本。"),
        })
    elif user_ed[0] < now_max[0]:
        # 主版落後 → 基礎標準已改版
        a_entries.append({
            "judge_status": "obsolete",
            "judge_category": "has_update",
            "missing_types": [], "missing_supplements": [],
            "judge_label": "有更新",
            "judge_message": (
                f"您持有的 {entry['reference']}（Edition {entry['edition']}）已被改版，"
                f"請更新至最新版 {now_latest or now_main}（Edition {now_max_str}）。"),
        })
    elif is_supplement:
        # 主版相同、次版落後，但這筆附屬文件本身仍列於官網現行清單 →
        # 「文件本身是最新的」，落後的是整個家族的合併版次，故 A 明確輸出無更新
        # （通用規則 2.3），家族缺件另由子判斷 B 呈現。
        a_entries.append({
            "judge_status": "valid",
            "judge_category": "no_update",
            "missing_types": [], "missing_supplements": [],
            "judge_label": "無更新",
            "judge_message": (
                f"您持有的 {entry['reference']} 即為 IEC 官網現行的附屬文件。"),
        })

    # ---- 子判斷 B：家族完整性 ----
    b_entries = []
    if is_supplement:
        # 持有的是附屬文件 → 檢查資料庫是否收錄了對應的主標準本體
        b_entries.extend(build_missing_main_entries(now_main, db_docs))
    elif a_entries and a_entries[0]["judge_status"] == "obsolete":
        pass  # 主版已落後：先更新主標準本體，不再逐項列出舊版家族的缺件
    elif user_ed and now_max and user_ed[0] == now_max[0] and user_ed < now_max:
        # 主版相同、次版落後 → 基礎標準未變，缺的是修正案／勘誤
        missing = [
            e["reference"] for e in now_entries
            if detect_doc_type(e["reference"], flavor="iec") in SUPPLEMENT_TYPES
            and norm_doc(e["reference"]) not in db_docs
        ]
        b_entries.append(_missing_supplement_entry(
            missing, now_main, now_latest,
            f"基礎標準 {now_main} 本體未改版，但您持有的 Edition {entry['edition']} "
            f"尚未併入後續修正案（官網現行為 Edition {now_max_str}）。"))

    # ---- 子判斷 C：官網已預告改版（IEC 的研擬中新版）----
    c_entries = build_under_revision_entries(lc, now_main)

    # 家族完全齊全且無任何改版預告時，把「無更新」的訊息說得更完整
    if not b_entries and not c_entries and len(a_entries) == 1 \
            and a_entries[0]["judge_category"] == "no_update":
        a_entries[0]["judge_message"] += "文件齊全，無需動作。"

    return combine_judge_entries(a_entries + c_entries + b_entries, now_main)


def _judge_unmatched(standard_name: str, current_version: str, lc: dict, db_docs,
                     holding: dict, now_main: str, now_latest: str,
                     now_entries: list) -> dict:
    """比對不到生命週期項目時的判定（見 judge_update_iec 的說明）。

    IEC 的版本字串無法只用一個年份表達，因此這裡以「持有年份 vs 官網主標準基礎版年份」
    的關係來決定：年份較舊代表本體已改版；年份較新則代表文管記的是某份修正案的年份，
    此時無從得知實際持有的是合併版還是單一修正案，只能請人工確認。
    """
    now_main_year = _year(version_part(now_main))
    user_year = holding["year"]
    c_entries = build_under_revision_entries(lc, now_main)

    # 以 '+' 連寫、基礎版年份與官網主標準相同，但湊不出任何官方合併版
    # → 本體未改版，缺的是字串中沒列到的修正案（例：漏了 AMD1:1999）
    if holding["kind"] == "chain" and now_main_year and user_year == now_main_year:
        missing = missing_family_supplements(holding, now_entries, db_docs)
        if missing:
            b_entry = _missing_supplement_entry(
                missing, now_main, now_latest,
                f"基礎標準 {now_main} 本體未改版，但您持有的版本"
                f"（{holding['version']}）尚未併入官網現行合併版的全部修正案。")
            return combine_judge_entries(c_entries + [b_entry], now_main)
        return combine_judge_entries([{
            "judge_status": "valid",
            "judge_category": "no_update",
            "missing_types": [], "missing_supplements": [],
            "judge_label": "無更新",
            "judge_message": (
                f"您持有的版本（{holding['version']}）已涵蓋官網現行 {now_main} "
                f"及其全部現行附屬文件。"),
        }] + c_entries, now_main)

    # 持有年份比官網主標準的基礎版年份新 → 該年份是某份修正案的年份
    # （例：IEC 60601-1-6 官網本體為 2010，文管記 2020，2020 其實是 AMD2 的年份）
    # → 無法判斷持有的是合併版還是單一修正案，需人工確認
    if holding["kind"] != "attached" and now_main_year and user_year > now_main_year:
        missing = missing_family_supplements(holding, now_entries, db_docs)
        return combine_judge_entries([{
            "judge_status": "unknown",
            "judge_category": "unknown",
            "missing_types": [], "missing_supplements": missing,
            "judge_label": "⚪ 無法判定",
            "judge_message": (
                f"持有版本記為 {holding['version']}，但官網現行主標準本體為 {now_main}"
                f"（基礎版 {now_main_year}）；{user_year} 是其後修正案的年份，"
                f"無法判斷實際持有的是合併版 {now_latest or '（合併版）'} 還是單一修正案"
                + (f"（官網現行附屬文件尚有 {', '.join(missing)} 未見於紀錄）" if missing else "")
                + "，請人工確認實際持有文件並補正版本寫法。"),
        }] + c_entries, now_main)

    # 其餘（年份較舊、無年份、或斜線掛載的附屬文件）：回退至共用的字串／年份判定
    return judge_update(standard_name, current_version, lc, db_docs, flavor="iec")


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
