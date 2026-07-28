"""法規標準「版本更新判定」共用邏輯（與來源網站無關）。

本模組收錄原先寫在 `iso_browser.py` 內、與 ISO 官網頁面解析無關的純判定邏輯，
讓 ISO（虛擬瀏覽器）與 IEC（webstore 搜尋 API）等不同來源共用同一套規則，
規則依據「需求/法規標準追蹤/ISO 法規版本更新判定邏輯規則.md」。

各來源的差異以 `flavor` 參數表示：
    'iso' — ISO 官網慣例（預設，行為與重構前完全一致）
    'iec' — IEC webstore 慣例（多了 ISH 解釋單，以及 CSV/SER/DB 等商品形式後綴）
"""
import re

# ---------------------------------------------------------------------------
# 文件類型判定
# ---------------------------------------------------------------------------
# IEC 的「商品形式」後綴：同一份標準的不同販售包裝，並非獨立的規範性文件。
# CSV（Consolidated version，主標準已併入修正案）與 DB（Database）本身是實際出版品，
# 其餘（SER 系列包、RLV 紅線版、CMV 註解版…）僅為重新包裝，比對家族時應排除。
IEC_PRODUCT_FORMS = ("CSV", "DB", "SER", "RLV", "CMV", "EXV", "PRV", "PAC", "TRF")
IEC_REPACKAGED_FORMS = ("SER", "RLV", "CMV", "EXV", "PRV", "PAC", "TRF")

# 視為「附屬文件」的類型（主標準之外的補充件），家族完整性比對時使用
SUPPLEMENT_TYPES = ("AMD", "COR", "ADD", "ISH")


def detect_doc_type(doc_str: str, flavor: str = "iso") -> str:
    """第一步：文件類型字串判定。

    flavor='iso' 回傳 'AMD'|'COR'|'ADD'|'TS'|'TR'|'PAS'|'Main'
        依規則順序：先判後綴(Amd/Cor/Add)，再判前綴(TS/TR/PAS)，都沒命中才視為主標準(Main)。
        寬鬆比對：資料庫的版本可能寫成 '2018+Amd 1:2021'（用 +），故以是否含 'amd/cor/add' 字樣判定。

    flavor='iec' 另可回傳 'ISH' 與 IEC_PRODUCT_FORMS 中的商品形式（如 'CSV'）。
        IEC 的判定順序與 ISO 不同：必須先看「以斜線掛載」的附屬文件（/AMD、/COR、/ISH），
        因為 'IEC 60601-1:2005+AMD1:2012 CSV/COR1:2012' 是「對合併版的勘誤」＝附屬文件，
        而 'IEC 60601-1:2005+AMD1:2012 CSV' 只是把修正案併入本體的合併版＝主標準等價物。
    """
    s = (doc_str or "")
    low = s.lower()

    if flavor == "en":
        # 歐盟協調標準的附屬文件寫法與 ISO/IEC 不同：
        #   /AC:2018  技術勘誤（corrigendum）
        #   /A1:2023、/A11:2021  修正案（amendment）
        # 而 '+A1:2023' 是「本體已含該修正案」的合併寫法，屬主標準等價物（比照 IEC 的 CSV）。
        if re.search(r"/\s*ac\b", low):
            return "COR"
        if re.search(r"/\s*a\d+\b", low):
            return "AMD"
        return "Main"

    if flavor == "iec":
        # 1. 以斜線掛載的附屬文件；同時出現多個時取「最後一個」（最外層的那份）
        last_type, last_pos = "", -1
        for kind, pat in (("AMD", r"/\s*amd"), ("COR", r"/\s*cor"),
                          ("ISH", r"/\s*ish"), ("ADD", r"/\s*add")):
            for m in re.finditer(pat, low):
                if m.start() > last_pos:
                    last_pos, last_type = m.start(), kind
        if last_type:
            return last_type
        # 2. 商品形式後綴（CSV / SER / DB …）
        for form in IEC_PRODUCT_FORMS:
            if re.search(rf"\b{form.lower()}\b", low):
                return form
        # 3. 前綴型文件（IEC TS / IEC TR / IEC PAS，斜線或空白皆可）
        for kind in ("TS", "TR", "PAS"):
            if re.search(rf"\biec\s*[/ ]\s*{kind.lower()}\b", low):
                return kind
        return "Main"

    # ---- ISO（預設）----
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


def norm_doc(s: str) -> str:
    """文件字串正規化（移除所有非英數字、轉小寫）以利跨格式比對，
    例如 'ISO 11737-1:2018/Amd 1:2021' 與 'ISO 11737-1:2018+Amd 1:2021' 視為相同。"""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def entry_is_supplement(title: str, flavor: str = "iso") -> bool:
    """該文件是否為附屬文件（AMD / COR / ADD / ISH）。"""
    return detect_doc_type(title, flavor) in SUPPLEMENT_TYPES


def extract_base_number(title: str) -> str:
    """從標準標題擷取基本編號（去除年份/修正案資訊），例如：
    'ISO 2859-1:1999'        -> 'ISO 2859-1'
    'IEC/TR 80002-1:2009'    -> 'IEC/TR 80002-1'
    'IEC TS 60601-4-2:2024'  -> 'IEC TS 60601-4-2'（IEC 官網以空白分隔）

    若文字中找不到 ISO/IEC 編號格式，回傳空字串（而非整段文字），
    避免將內部文件編號或純文字法規名稱誤判為「基本編號」。
    """
    if not title:
        return ""
    match = re.search(
        r"((?:ISO|IEC)(?:\s*[/ ]\s*(?:IEC|TR|TS|PAS))?\s*[\d]+(?:-\d+)*)",
        title,
        re.IGNORECASE,
    )
    if match:
        return re.sub(r"\s+", " ", match.group(1).strip())
    return ""


def normalize_base_number(base: str) -> str:
    """標準化標準基本編號以利比對，移除所有非英數字元
    （避免 'IEC/TR 80002-1' 與 'IEC TR 80002-1' 等格式差異造成誤判）"""
    return re.sub(r"[^a-z0-9]", "", base.lower()) if base else ""


# ---------------------------------------------------------------------------
# 第二、三步：生命週期與資料庫狀態判定
# ---------------------------------------------------------------------------
# 四大頂層分類（供前端篩選／統計使用，一筆判定結果可同時命中多個）：
#   'no_update'  無更新
#   'has_update' 有更新（主標準已改版 / 舊版附屬文件已整合）
#   'missing'    缺少（主標準本體 / AMD、COR、ADD 等附屬文件）
#   'not_found'  查無結果（可能已作廢）
# 'unknown'（無法判定）維持獨立於四大類之外的第五種狀態，需人工確認。
JUDGE_CATEGORIES = ("no_update", "has_update", "missing", "not_found", "unknown")


def judge_update(user_title: str, user_version: str, lc: dict,
                 db_docs=None, flavor: str = "iso") -> dict:
    """依文件落在 NOW / Previously 區塊、文件類型，並結合內部資料庫比對，判定更新狀態。

    lc: 生命週期結構，需含 now_list / previously（[(status, title), ...]）。
    db_docs: 內部資料庫中「同編號」已收錄文件的正規化字串集合（norm_doc 後）。
             用於「缺補充件／缺主標準」交叉比對；None 視為空集合。

    判定拆成兩個互相獨立、可同時成立的子判斷，最後取聯集：
        A. 這筆文件「本身」版本是否落後於官網現行版（NOW／Previously／年份回退）。
        B. 這筆文件所屬「家族」（主標準＋AMD/COR/ADD…）在資料庫中是否齊全。
    例如使用者持有舊版主標準（A：有更新），而新版主標準的 AMD 尚未收錄（B：缺少），
    兩者會同時出現在回傳結果中，而非互斥地只回報其中一種。

    回傳：
        judge_statuses: 命中的細節狀態代碼列表，例如 ['obsolete', 'missing_supplement']
        judge_categories: 命中的頂層分類列表（見 JUDGE_CATEGORIES），例如 ['has_update', 'missing']
        judge_status:   （相容用）judge_statuses 以「+」串接的字串
        judge_label:    中文狀態標籤，多筆時以「、」串接
        judge_message:  給使用者的提示，多筆時以換行串接
        has_update:     是否需提醒（僅 no_update / unknown 為 False，其餘 True）
        now_main:       NOW 區塊的主標準字串（供提示用）
        missing_types / missing_supplements: 缺少子判斷（B）的細節，未命中則為空列表
    """
    db_docs = db_docs or set()
    # 組出使用者持有的完整文件字串（法規名稱 + 版本）
    uv = (user_version or "").strip()
    if uv:
        user_doc = f"{user_title}:{uv}" if not re.match(r"^\s*[:：]", uv) else f"{user_title}{uv}"
    else:
        user_doc = user_title or ""
    doc_type = detect_doc_type(user_doc, flavor)

    now_list = lc.get("now_list") or ([(lc.get("now_status", ""), lc.get("now_title", ""))]
                                      if lc.get("now_title") else [])
    prev_list = lc.get("previously") or []

    # NOW 區塊的主標準（第一筆非附屬文件）
    now_main = ""
    for _st, t in now_list:
        if not entry_is_supplement(t, flavor) and not now_main:
            now_main = t
    if not now_main and now_list:
        now_main = now_list[0][1]

    un = norm_doc(user_doc)
    now_norm = {norm_doc(t): t for _st, t in now_list}
    prev_norm = {norm_doc(t): t for _st, t in prev_list}

    # NOW 區塊中的附屬文件（Amd/Cor/Add/ISH）
    now_supplement_titles = [t for _st, t in now_list if entry_is_supplement(t, flavor)]

    # ---- 子判斷 A：這筆文件本身版本是否落後 ----
    # 顯示用標籤一律只寫「有更新」，不細分是主標準改版還是附屬文件被整合
    # （文件類型本身已可由 doc_type 判斷，不需在標籤重複說明）；細節保留在 judge_message。
    a_entries = []
    if un in now_norm:
        pass  # 版本即為現行，A 不貢獻任何狀態
    elif un in prev_norm:
        if doc_type in ("AMD", "ADD"):
            a_entries.append({
                "judge_status": "integrated",
                "judge_category": "has_update",
                "judge_label": "有更新",
                "judge_message": (
                    f"您持有的舊版修正案已失效，相關技術變更已整合至最新版主標準 "
                    f"{now_main or '（最新版）'}，請直接取得最新版主標準。"),
            })
        elif doc_type in ("COR", "ISH"):
            a_entries.append({
                "judge_status": "integrated",
                "judge_category": "has_update",
                "judge_label": "有更新",
                "judge_message": (
                    f"您持有的舊版技術勘誤已失效，相關勘誤已於最新版主標準 "
                    f"{now_main or '（最新版）'} 中修正，請直接取得最新版主標準。"),
            })
        else:
            a_entries.append({
                "judge_status": "obsolete",
                "judge_category": "has_update",
                "judge_label": "有更新",
                "judge_message": (
                    f"您持有的舊版主標準已改版，請更新至最新主標準 {now_main or '（最新版）'}。"),
            })
    else:
        # 未在 NOW / Previously 找到：以年份回退判斷（避免漏接）
        now_year_m = re.search(r":(\d{4})", now_main)
        now_year = now_year_m.group(1) if now_year_m else ""
        uv_year_m = re.search(r"(\d{4})", uv)
        uv_year = uv_year_m.group(1) if uv_year_m else ""
        if now_year and uv_year and now_year != uv_year:
            a_entries.append({
                "judge_status": "obsolete",
                "judge_category": "has_update",
                "judge_label": "有更新",
                "judge_message": (
                    f"您持有的版本（{uv_year}）未出現在官網現行清單，且現行版為 {now_main}，"
                    f"研判已改版，請確認並更新。"),
            })
        else:
            a_entries.append({
                "judge_status": "unknown",
                "judge_category": "unknown",
                "missing_types": [], "missing_supplements": [],
                "judge_label": "⚪ 無法判定",
                "judge_message": (
                    f"未能在官網 Life cycle 的 NOW / Previously 區塊比對到您持有的版本"
                    f"（{user_doc}），請人工確認。現行版：{now_main or '未知'}。"),
            })

    # ---- 子判斷 B：家族完整性 ----
    # 與 A 是否命中無關，獨立判斷；doc_type 已可判斷這筆是主標準還是附屬文件，
    # 故「有更新」與「缺少」可同時成立並同時顯示（例如主標準已改版，且新版的 AMD 尚未收錄）。
    b_entries = []
    # 本身非附屬文件 → 檢查官網現行的 AMD/COR/ADD 是否都已收錄於資料庫。
    if doc_type not in SUPPLEMENT_TYPES:
        if now_supplement_titles:
            missing = [t for t in now_supplement_titles if norm_doc(t) not in db_docs]
            if missing:
                miss_types = []
                for t in missing:
                    dt = detect_doc_type(t, flavor)
                    lab = dt if dt in ("COR", "ISH") else "AMD"
                    if lab not in miss_types:
                        miss_types.append(lab)
                types_str = " / ".join(miss_types) if miss_types else "AMD"
                b_entries.append({
                    "judge_status": "missing_supplement",
                    "judge_category": "missing",
                    "missing_types": miss_types,
                    "missing_supplements": missing,
                    "judge_label": f"缺少（{types_str} 等附屬文件）",
                    "judge_message": (
                        f"官網現行主標準 {now_main} 已發布補充文件 "
                        f"{', '.join(missing)}，但系統發現資料庫尚未收錄，請盡速更新資料庫。"),
                })
    # 本身是附屬文件 → 檢查對應的主標準本體是否已收錄於資料庫。
    # db_docs 必為非空（至少含目前判定的這筆紀錄）才檢查，避免標準未收錄於資料庫時誤判。
    elif now_main and db_docs and norm_doc(now_main) not in db_docs:
        b_entries.append({
            "judge_status": "missing_main",
            "judge_category": "missing",
            "missing_types": [],
            "missing_supplements": [],
            "judge_label": "缺少（主標準本體）",
            "judge_message": (
                f"系統發現資料庫已收錄補充文件，但缺少對應的最新主標準本體 "
                f"{now_main}。補充文件無法獨立使用，請盡速補充主標準。"),
        })

    entries = a_entries + b_entries
    if not entries:
        entries.append({
            "judge_status": "valid",
            "judge_category": "no_update",
            "missing_types": [], "missing_supplements": [],
            "judge_label": "無更新",
            "judge_message": "文件與附屬資料皆為最新且齊全，無需動作。",
        })

    return _combine_judge_entries(entries, now_main)


def _combine_judge_entries(entries: list, now_main: str) -> dict:
    """將子判斷 A、B 命中的多筆結果合併為單一回傳 dict（允許同時命中多個頂層分類）。"""
    judge_statuses = [e["judge_status"] for e in entries]
    judge_categories = []
    for e in entries:
        if e["judge_category"] not in judge_categories:
            judge_categories.append(e["judge_category"])
    missing_types, missing_supplements = [], []
    for e in entries:
        missing_types.extend(e.get("missing_types") or [])
        missing_supplements.extend(e.get("missing_supplements") or [])
    has_update = any(c in ("has_update", "missing") for c in judge_categories)
    return {
        "judge_statuses": judge_statuses,
        "judge_categories": judge_categories,
        "judge_status": "+".join(judge_statuses),
        "judge_label": "、".join(e["judge_label"] for e in entries),
        "judge_message": "\n".join(e["judge_message"] for e in entries),
        "has_update": has_update,
        "now_main": now_main,
        "missing_types": missing_types,
        "missing_supplements": missing_supplements,
    }


def collect_db_docs(standard_name: str) -> set:
    """蒐集內部資料庫中「同編號」已收錄文件的正規化字串集合（含其修正案/勘誤版本），
    供 NOW 主標準的「缺補充件」交叉比對。例如資料庫某筆 current_version 為
    '2019+Amd 1:2023'，會被視為已收錄附屬文件 'ISO 11607-1:2019/Amd 1:2023'。"""
    from database import get_db
    docs = set()
    base = normalize_base_number(extract_base_number(standard_name))
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
        rbase = normalize_base_number(extract_base_number(rtitle))
        if rbase and rbase == base:
            cv = (r["current_version"] or "").strip()
            docs.add(norm_doc(f"{rtitle}:{cv}" if cv else rtitle))
    return docs
