"""EN / EN ISO / BS EN 標準版本追蹤（依 EU 協調標準官方公報清單）。

判定基準：
    CEN/CENELEC 與 BSI 的官方標準商店皆為付費牆，且 CEN 的標準資料庫（Oracle APEX）
    純 HTTP 會回 500、結果為 JS 渲染，穩定性不足。因此本模組改以**歐盟執委會官方公布的
    「協調標準彙整清單」**作為判定依據 —— 對醫療器材業者而言，EN 標準真正要回答的問題是
    「我持有的版本是否仍具符合性推定（presumption of conformity）」，而這份公報清單正是
    該問題的權威答案。

資料來源：
    頁面  https://single-market-economy.ec.europa.eu/.../medical-devices_en
    檔案  該頁面上的「Summary list as xls file」(xlsx)
    註：下載網址含 UUID 且會隨改版變動，故每次都從頁面動態解析連結，不寫死。

清單結構（每一列＝一項協調標準的引用）：
    「Reference and title Provision」欄位為多行文字：
        第 1 行   主標準參照（例：EN ISO 13485:2016）
        第 2 行   標準名稱
        第 3 行起 隨該引用一併生效的修正案／勘誤（例：EN ISO 13485:2016/AC:2018）
    另有生效日(Start of legal effect)、失效日(End of legal effect)與撤銷公告欄位。

    因此一列＝一個「標準家族」，與 ISO 的 NOW 區塊（主標準＋AMD/COR）概念相同，
    可沿用 standards_common 的家族完整性判定邏輯。

狀態對應：
    失效日為空、或仍在未來        → NOW（現行仍具符合性推定；過渡期內亦視為有效）
    失效日已過                    → Previously（已失去符合性推定）
    完全不在清單中                → 非協調標準（另以母標準 ISO/IEC 的更新狀況輔助提示）
"""
import io
import re
import logging
from datetime import datetime

import httpx

from crawlers.standards_common import (
    norm_doc,
    judge_update,
    collect_db_docs,
    normalize_base_number,
    detect_doc_type,
    SUPPLEMENT_TYPES,
)

logger = logging.getLogger(__name__)

HARMONISED_PAGE = (
    "https://single-market-economy.ec.europa.eu/single-market/european-standards/"
    "harmonised-standards/medical-devices_en"
)
REQUEST_TIMEOUT = 60.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def extract_en_base(title: str) -> str:
    """擷取 EN 標準的基本編號，例如：
    'EN ISO 13485:2016/A11:2021'  -> 'EN ISO 13485'
    'EN ISO 11607-1:2020+A1:2023' -> 'EN ISO 11607-1'
    'BS EN 868-8:2009'            -> 'EN 868-8'（BS 前綴為英國採認，比對時去除）
    'EN 62366-1:2015+A1:2020'     -> 'EN 62366-1'
    """
    s = re.sub(r"^\s*BS\s+", "", (title or "").strip(), flags=re.IGNORECASE)
    m = re.match(r"(EN(?:\s+(?:ISO|IEC))?\s*\d+(?:-\d+)*)", s, re.IGNORECASE)
    return re.sub(r"\s+", " ", m.group(1).strip()) if m else ""


def parent_candidates(title: str) -> list:
    """由 EN 標準名稱推出可能的母標準名稱（供非協調標準改以母標準輔助判定）。

    'EN ISO 15225:2016'       -> ['ISO 15225']
    'EN 62366-1:2015+A1:2020' -> ['IEC 62366-1', 'ISO 62366-1']
    'BS EN 868-8:2009'        -> []（純 CEN 標準，無 ISO/IEC 母標準）
    """
    base = extract_en_base(title)
    if not base:
        return []
    m = re.match(r"EN\s+(ISO|IEC)\s+(.+)$", base, re.IGNORECASE)
    if m:
        return [f"{m.group(1).upper()} {m.group(2)}"]
    m = re.match(r"EN\s+(\d+(?:-\d+)*)$", base, re.IGNORECASE)
    if m:
        num = m.group(1)
        # EN 60000-69999 系列為 CENELEC 採認 IEC 標準；其餘（如 EN 868-8）為純 CEN 標準
        head = int(re.match(r"(\d+)", num).group(1))
        if 60000 <= head <= 69999:
            return [f"IEC {num}"]
    return []


# ---------------------------------------------------------------------------
# 官方清單下載與解析
# ---------------------------------------------------------------------------
def discover_summary_url(html: str) -> str:
    """從協調標準頁面 HTML 找出「Summary list as xls file」的下載網址。"""
    links = re.findall(r'href="([^"]*document/download/[^"]*)"', html or "")
    for link in links:
        url = link.replace("&amp;", "&")
        if ".xls" in url.lower():
            return url
    return ""


def _parse_date(value: str):
    """解析清單中的 'DD.MM.YYYY' 日期字串，無法解析時回傳 None。"""
    v = (value or "").strip()
    if not v:
        return None
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    return None


def parse_summary(content: bytes) -> dict:
    """解析協調標準清單 xlsx，回傳 {正規化基本編號: [引用項目, ...]}。

    每個引用項目：
        references  該引用涵蓋的所有文件（主標準 + 隨附修正案／勘誤）
        title       標準名稱
        start/end   生效日 / 失效日（datetime 或 None）
        in_force    目前是否仍具符合性推定
    """
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    index = {}
    now = datetime.now()

    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        # 找出標頭列（含 'Reference and title' 的那列）
        header_idx = None
        for i, row in enumerate(rows[:10]):
            if any(c and "Reference and title" in str(c) for c in row):
                header_idx = i
                break
        if header_idx is None:
            continue
        header = [str(c or "") for c in rows[header_idx]]

        def col(name, default):
            for j, h in enumerate(header):
                if name.lower() in h.lower():
                    return j
            return default

        c_ref = col("Reference and title", 2)
        c_start = col("Start of legal effect", 3)
        c_end = col("End of legal effect", 7)

        for row in rows[header_idx + 1:]:
            if not row or len(row) <= c_ref or not row[c_ref]:
                continue
            lines = [ln.strip() for ln in str(row[c_ref]).split("\n") if ln.strip()]
            if not lines:
                continue
            main_ref = lines[0]
            # 第 2 行為標準名稱，第 3 行起為隨附的修正案／勘誤
            title = lines[1] if len(lines) > 1 else ""
            supplements = [ln for ln in lines[2:] if re.match(r"^(BS\s+)?EN\b", ln, re.I)]

            def cell(idx):
                return str(row[idx]).strip() if len(row) > idx and row[idx] else ""

            end_dt = _parse_date(cell(c_end))
            entry = {
                "main_reference": main_ref,
                "references": [main_ref] + supplements,
                "title": title,
                "start": _parse_date(cell(c_start)),
                "end": end_dt,
                "end_raw": cell(c_end),
                # 失效日為空或仍在未來（過渡期內）→ 目前仍具符合性推定
                "in_force": end_dt is None or end_dt >= now,
            }
            key = normalize_base_number(extract_en_base(main_ref))
            if key:
                index.setdefault(key, []).append(entry)

    return index


async def fetch_summary_index(client: httpx.AsyncClient) -> tuple:
    """下載並解析最新的協調標準清單。回傳 (index, 來源網址)。"""
    page = await client.get(HARMONISED_PAGE)
    page.raise_for_status()
    url = discover_summary_url(page.text)
    if not url:
        raise RuntimeError("無法在歐盟協調標準頁面找到彙整清單(xls)的下載連結")
    logger.info("[en_harmonised] 下載協調標準清單: %s", url)
    resp = await client.get(url)
    resp.raise_for_status()
    return parse_summary(resp.content), url


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------
def _user_doc(title: str, current_version: str) -> str:
    """組出使用者持有的完整文件字串。

    EN 類別的資料庫「法規名稱」欄位本身已含版本（例：'EN ISO 13485:2016/A11:2021'），
    與 ISO/IEC（法規名稱僅存編號、版本另存一欄）不同，故名稱已含冒號版本時直接沿用，
    避免組出 'EN ISO 13485:2016/A11:2021:2016' 這種錯誤字串。
    """
    t = (title or "").strip()
    v = (current_version or "").strip()
    if ":" in t or not v:
        return t
    return f"{t}:{v}"


def _lifecycle_from_entries(entries: list) -> dict:
    """將協調清單中同一編號的所有引用，轉為 ISO 形式的 Life cycle 結構。"""
    lc = {
        "now_status": "", "now_title": "", "now_stage": "",
        "now_list": [], "previously": [],
        "newer_title": "", "newer_year": "", "newer_kind": "", "newer_url": "",
    }
    seen_now, seen_prev = set(), set()
    for e in entries:
        bucket, seen, label = (
            (lc["now_list"], seen_now, "In force") if e["in_force"]
            else (lc["previously"], seen_prev, "Withdrawn")
        )
        for ref in e["references"]:
            if norm_doc(ref) in seen:
                continue
            seen.add(norm_doc(ref))
            bucket.append((label, ref))

    for _st, ref in lc["now_list"]:
        lc["now_status"], lc["now_title"] = _st, ref
        break
    return lc


def _compose_en_supplement_version(lc: dict, doc_type: str) -> str:
    """附屬文件列的「最新同步版本」：只取公報現行引用中『同類型』的附屬文件。

    依通用規則第 4 節「同類型對同類型」：持有 '/AC:2018' 的那一列要跟公報現行的 AC 比，
    不能拿整份家族引用（'2016 + AC:2018 + A11:2021'）去比一份勘誤，
    否則兩欄並排時無法解釋該列的徽章。

    沿用 EN 的附屬文件寫法 '<主標準版次>/<附屬文件>'，例如 '2016/AC:2018'；
    組不出時回傳空字串，由呼叫端回退。
    """
    parts = []
    for _st, title in lc.get("now_list") or []:
        if detect_doc_type(title, "en") != doc_type or ":" not in title:
            continue
        part = title.split(":", 1)[1].strip()
        if part and part not in parts:
            parts.append(part)
    return " + ".join(parts)


def _not_harmonised_result(title: str, parents: list, parent_rows: list) -> dict:
    """非協調標準：不在公報清單內，改以母標準（ISO/IEC）的追蹤結果輔助提示。"""
    if parent_rows:
        bits = []
        has_update = False
        for row in parent_rows:
            label = row.get("judge_label") or ("有更新" if row.get("has_update") else "無更新")
            bits.append(f"{row['title']}（{label}）")
            if row.get("has_update"):
                has_update = True
        msg = (
            f"此標準未列入歐盟 MDR 協調標準清單，官方公報無現行引用可比對，"
            f"無法自動判定版本。其母標準追蹤狀況：{'；'.join(bits)}。"
            f"{'母標準已有更新，請人工確認 CEN 是否已跟進採認新版。' if has_update else '母標準目前無更新。'}"
        )
    else:
        has_update = False
        msg = (
            "此標準未列入歐盟 MDR 協調標準清單，且無對應的 ISO/IEC 母標準可連動，"
            "無法自動判定版本，請由文管人員人工確認。"
        )
    return {
        "ok": True,
        "source_url": HARMONISED_PAGE,
        "found_title": "",
        "now_status": "", "now_title": "", "now_stage": "", "now_year": "",
        "now_list": [], "previously": [],
        "newer_title": "", "newer_kind": "", "newer_url": "", "newer_year": "",
        "doc_type": detect_doc_type(title, "en"),
        "judge_statuses": ["not_harmonised"],
        "judge_categories": ["unknown"],
        "judge_status": "not_harmonised",
        "judge_label": "非協調標準（需人工確認）",
        "judge_message": msg,
        "now_main": "",
        "missing_types": [], "missing_supplements": [],
        "has_update": has_update,
        "reasons": [msg],
    }


def _lookup_parent_rows(parents: list) -> list:
    """查出母標準在資料庫中的追蹤結果（供非協調標準的輔助提示）。"""
    if not parents:
        return []
    from database import get_db
    out = []
    try:
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT title, judge_label, has_update FROM standards"
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return []
    wanted = {normalize_base_number(p) for p in parents}
    from crawlers.standards_common import extract_base_number
    for r in rows:
        rtitle = r["title"] or ""
        # 排除 EN / BS EN 自身：extract_base_number 會在 'EN ISO 15225' 中比到 'ISO 15225'，
        # 若不排除，母標準查詢會比對到自己而產生自我參照的提示。
        if re.match(r"^\s*(BS\s+)?EN\b", rtitle, re.IGNORECASE):
            continue
        if normalize_base_number(extract_base_number(rtitle)) in wanted:
            out.append({
                "title": r["title"],
                "judge_label": r["judge_label"],
                "has_update": bool(r["has_update"]),
            })
    return out


def judge_en_standard(title: str, current_version: str, index: dict) -> dict:
    """依協調標準清單判定單一 EN 標準的更新狀態。"""
    base = extract_en_base(title)
    entries = index.get(normalize_base_number(base), [])

    if not entries:
        parents = parent_candidates(title)
        return _not_harmonised_result(title, parents, _lookup_parent_rows(parents))

    lc = _lifecycle_from_entries(entries)
    user_doc = _user_doc(title, current_version)
    # 資料庫中同編號的其他紀錄（例如 AC / A11 各自一筆），供家族完整性比對
    db_docs = _collect_en_db_docs(base)

    # 拆成「編號 / 版本」兩段再交給共用判定：judge_update 會重新組回同一字串，
    # 但另需版本段才能在比不到 NOW/Previously 時以年份回退判斷（例如公報只剩新版）。
    if ":" in user_doc:
        name_part, version_part = user_doc.split(":", 1)
    else:
        name_part, version_part = user_doc, ""
    verdict = judge_update(name_part, version_part, lc, db_docs, flavor="en")

    now_main = verdict.get("now_main") or lc["now_title"]
    year_m = re.search(r":(\d{4})", now_main)

    # 「最新同步版本」顯示字串，依該筆的文件類型分兩種組法：
    #   附屬文件列（/AC、/A11）→ 公報現行的『同類型』附屬文件（通用規則第 4 節）
    #   主標準列              → 現行引用的完整內容（主標準＋隨附修正案），
    #                           因 EN 的符合性推定是對整份引用成立（EN 規則第 6 節）
    doc_type = detect_doc_type(user_doc, "en")
    in_force = [e for e in entries if e["in_force"]]
    shown = ""
    if doc_type in SUPPLEMENT_TYPES:
        shown = _compose_en_supplement_version(lc, doc_type)
    elif in_force:
        latest = max(in_force, key=lambda e: (e["start"] or datetime.min))
        shown = " + ".join(
            [latest["main_reference"].split(":", 1)[-1]]
            + [r.split("/", 1)[-1] for r in latest["references"][1:]]
        )
    if not shown:
        shown = year_m.group(1) if year_m else ""

    # 過渡期提醒：現行引用已公告失效日
    ending = [e for e in in_force if e["end"] is not None]
    if ending and not verdict["has_update"]:
        soonest = min(ending, key=lambda e: e["end"])
        verdict = dict(verdict)
        verdict["judge_message"] += (
            f" 注意：此引用已公告失效日 {soonest['end_raw']}，"
            f"屆期後將失去符合性推定，請留意後續公報。"
        )

    return {
        "ok": True,
        "source_url": HARMONISED_PAGE,
        "found_title": lc["now_title"],
        "now_status": lc["now_status"],
        "now_title": lc["now_title"],
        "now_stage": "",
        "now_year": shown,
        "now_list": [{"status": s, "title": t} for s, t in lc["now_list"]],
        "previously": [{"status": s, "title": t} for s, t in lc["previously"]],
        "newer_title": "", "newer_kind": "", "newer_year": "", "newer_url": "",
        "doc_type": doc_type,
        "judge_statuses": verdict["judge_statuses"],
        "judge_categories": verdict["judge_categories"],
        "judge_status": verdict["judge_status"],
        "judge_label": verdict["judge_label"],
        "judge_message": verdict["judge_message"],
        "now_main": now_main,
        "missing_types": verdict.get("missing_types", []),
        "missing_supplements": verdict.get("missing_supplements", []),
        "has_update": verdict["has_update"],
        "reasons": [verdict["judge_message"]],
    }


def expand_consolidated(reference: str) -> list:
    """將「本體＋修正案」的合併寫法展開為其涵蓋的各份文件。

    'EN ISO 11607-1:2020+A1:2023' 代表持有 2020 本體且已含 A1:2023 修正案，
    等同同時收錄 'EN ISO 11607-1:2020' 與 'EN ISO 11607-1:2020/A1:2023'。
    若不展開，家族完整性比對會誤判為「缺少主標準」。

    合併寫法之後可再掛獨立的附屬文件（本體已含 A1，之後官方又發了 AC）：
    'EN ISO 11607-1:2020+A1:2023/AC:2024' 展開為 2020 本體、/A1:2023 與 /AC:2024 三份。
    此處必須連 `/` 後綴一起吃下，否則整串會被當成單一份勘誤，
    家族比對將誤判為「缺少（主標準本體）」。

    僅有 `/` 而無 `+`（例 'EN ISO 13485:2016/AC:2018'）代表只持有該份附屬文件、
    不含本體，不得展開。
    """
    ref = (reference or "").strip()
    out = [ref]
    m = re.match(
        r"^(.*?:\s*\d{4})"              # 本體（含冒號年份）
        r"((?:\s*\+\s*A\w*[:\d]*)+)"    # 已併入本體的修正案（一個以上，`+` 為必要）
        r"((?:\s*/\s*A\w*[:\d]*)*)\s*$",  # 之後另行掛載的獨立附屬文件（可無）
        ref, re.IGNORECASE,
    )
    if not m:
        return out
    body = m.group(1).strip()
    out.append(body)
    for sup in re.findall(r"[+/]\s*(A\w*:?\s*\d*)", m.group(2) + m.group(3), re.IGNORECASE):
        out.append(f"{body}/{sup.strip()}")
    return out


def _collect_en_db_docs(base: str) -> set:
    """蒐集資料庫中同一 EN 編號的所有已收錄文件（EN 類別的版本直接寫在法規名稱裡），
    並將合併寫法展開為其涵蓋的各份文件。"""
    from database import get_db
    docs = set()
    want = normalize_base_number(base)
    if not want:
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
        t = r["title"] or ""
        if normalize_base_number(extract_en_base(t)) == want:
            for ref in expand_consolidated(_user_doc(t, r["current_version"] or "")):
                docs.add(norm_doc(ref))
    return docs


# ---------------------------------------------------------------------------
# 對外介面
# ---------------------------------------------------------------------------
def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


async def resolve_source_url(standard_name: str, current_version: str = "") -> dict:
    """查詢單一 EN 標準在歐盟協調標準清單中的現行引用與版本判讀。"""
    async with _client() as client:
        try:
            index, _url = await fetch_summary_index(client)
        except Exception as e:
            return {"ok": False, "error": f"協調標準清單取得失敗：{type(e).__name__}: {e}"}
    return judge_en_standard(standard_name, current_version, index)


async def resolve_many(items: list, on_item=None) -> dict:
    """批量查找：整批只下載一次協調標準清單。

    items: [{"key": ..., "standard_name": str, "current_version": str}, ...]
    on_item: 選填回呼 on_item(key, item, result)，每處理完一筆即呼叫。
    """
    out = {}
    if not items:
        return out

    async with _client() as client:
        try:
            index, _url = await fetch_summary_index(client)
        except Exception as e:
            err = {"ok": False, "error": f"協調標準清單取得失敗：{type(e).__name__}: {e}"}
            for it in items:
                out[it["key"]] = err
                if on_item is not None:
                    try:
                        on_item(it["key"], it, err)
                    except Exception as cb_err:
                        logger.warning("on_item 回呼錯誤（%s）: %s", it["key"], cb_err)
            return out

    logger.info("[en_harmonised] 協調標準清單共 %d 個標準編號", len(index))
    for it in items:
        key = it["key"]
        try:
            result = judge_en_standard(
                it.get("standard_name") or "", it.get("current_version") or "", index
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
