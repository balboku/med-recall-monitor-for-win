"""EU 法規與歐盟指引文件版本追蹤（R301）。

R301 類別內含三種性質完全不同的文件，分別以不同來源判定：

  1. 歐盟法規／指令（Regulation、Directive）
     來源：EUR-Lex。以文件名稱推導 CELEX 編號後取得該法規頁面，讀取
     「Current consolidated version」與現行效力狀態。
     EU 法規的「版本」概念即為**現行合併版(consolidated version)的日期** ——
     法規本身編號不變，但歷次修訂會併入合併版並標上生效日期。

  2. 歐盟指引文件（Manual on borderline、Helsinki Procedure、NBOG 等）
     來源：執委會「MDCG endorsed documents and other guidance」清單頁，
     以連結文字比對文件名稱並取出版本後綴（v5、rev.4 …）。

  3. 其他（MEDDEV 舊版指引、EUDAMED 使用手冊）
     實測執委會已無穩定的公開清單頁可解析（舊指引封存頁 404、EUDAMED 手冊
     未列於任何可解析的清單），故標記為「需人工確認」並如實說明原因。

注意：R301 各筆的「目前使用版本」欄位原本皆為空白，首次掃描僅建立基準版本
（狀態寫入「已建立基準版本」），不會誤報為有更新。
"""
import re
import logging
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

EURLEX_URL = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"
# 執委會指引清單頁（舊網址 medical-devices-dialogue-between-interested-parties/... 已 404）
GUIDANCE_LIST_URL = (
    "https://health.ec.europa.eu/medical-devices-sector/new-regulations/"
    "guidance-mdcg-endorsed-documents-and-other-guidance_en"
)
REQUEST_TIMEOUT = 60.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# 無公開清單可自動判定者，說明原因供文管人員參考
MANUAL_ONLY_HINTS = (
    (r"MEDDEV",
     "MEDDEV 屬 MDD/AIMDD 時代的舊版指引，執委會已不再維護且封存頁面無法穩定解析，"
     "請人工確認是否已被 MDCG 指引取代。"),
    (r"EUDAMED",
     "EUDAMED 使用手冊未列於執委會任何可解析的公開清單頁（多為改版後直接置換的 PDF），"
     "請人工至 EUDAMED 網站確認最新版本。"),
)


# ---------------------------------------------------------------------------
# 一、EUR-Lex 法規
# ---------------------------------------------------------------------------
def to_celex(name: str) -> str:
    """由法規名稱推導 CELEX 編號。

    'Regulation (EU) 2017/745'      -> '32017R0745'
    'Directive 2011/65/EU'          -> '32011L0065'
    'Regulation (EC) No 1907/2006'  -> '32006R1907'
    'Directive 94/62/EC'            -> '31994L0062'

    歐盟編號有兩種慣例：
        年/號  Directive 94/62/EC、Regulation (EU) 2017/745（2015 起的新制法規）
        號/年  Regulation (EC) No 1907/2006（2015 前的舊制法規）
    故以「哪一段看起來像年份」判斷，不可固定取前段。
    """
    n = " ".join((name or "").split())
    m = re.search(
        r"(Regulation|Directive|Decision)[^\d]{0,20}?(?:No\s*)?(\d{1,4})/(\d{2,4})",
        n, re.IGNORECASE,
    )
    if not m:
        return ""
    kind = {"regulation": "R", "directive": "L", "decision": "D"}[m.group(1).lower()]
    a, b = m.group(2), m.group(3)

    def is_year(v):
        return len(v) == 4 and 1950 <= int(v) <= 2099

    if is_year(a):
        year, num = a, b
    elif is_year(b):
        year, num = b, a
    elif len(a) == 2:  # 舊制兩位數年份，年在前（例：94/62）
        year = ("19" + a) if int(a) > 50 else ("20" + a)
        num = b
    else:
        return ""
    return f"3{year}{kind}{int(num):04d}"


def parse_eurlex(html: str) -> dict:
    """解析 EUR-Lex 法規頁，取出效力狀態與現行合併版。"""
    info = {"in_force": "", "consolidated": "", "consolidated_date": "", "all_consolidated": []}

    # 「Current consolidated version:」與連結之間夾有 <strong>/<span>，故以寬鬆比對取 CELEX
    m = re.search(
        r"Current consolidated version:.{0,300}?CELEX:(0\d{4}[A-Z]\d{4}-(\d{8}))",
        html, re.S,
    )
    if m:
        info["consolidated"] = m.group(1)
        info["consolidated_date"] = m.group(2)

    info["all_consolidated"] = sorted(set(
        re.findall(r"CELEX[:%]3?A?(0\d{4}[A-Z]\d{4}-\d{8})", html)
    ))
    # 未標示「Current consolidated version」代表該法規尚未被修訂；
    # 若仍有合併版清單，取最新一筆作為現行版本。
    if not info["consolidated"] and info["all_consolidated"]:
        latest = info["all_consolidated"][-1]
        info["consolidated"] = latest
        info["consolidated_date"] = latest.rsplit("-", 1)[-1]

    for label in ("No longer in force", "In force"):
        if re.search(rf">\s*{label}\b", html):
            info["in_force"] = label
            break
    return info


def _fmt_date(yyyymmdd: str) -> str:
    if len(yyyymmdd or "") != 8:
        return yyyymmdd or ""
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


async def _judge_eurlex(client: httpx.AsyncClient, name: str, current_version: str) -> dict:
    celex = to_celex(name)
    url = EURLEX_URL.format(celex=celex)
    resp = await client.get(url)
    if resp.status_code != 200:
        return _manual_result(
            name, f"EUR-Lex 查無此法規頁面（推導編號 {celex}，HTTP {resp.status_code}），"
                  f"請人工確認法規名稱是否正確。", source_url=url)

    info = parse_eurlex(resp.text)
    shown = _fmt_date(info["consolidated_date"])
    ti = resp.text.lower().find("<title>")
    found_title = (
        re.sub(r"\s+", " ", resp.text[ti + 7:resp.text.lower().find("</title>")]).strip()
        if ti >= 0 else name
    )

    base = {
        "ok": True,
        "source_url": url,
        "found_title": found_title,
        "now_status": info["in_force"],
        "now_title": info["consolidated"] or celex,
        "now_stage": "",
        "now_year": shown,
        "now_list": [{"status": info["in_force"], "title": info["consolidated"] or celex}],
        "previously": [
            {"status": "Superseded", "title": c}
            for c in info["all_consolidated"][:-1]
        ],
        "newer_title": "", "newer_kind": "", "newer_year": "", "newer_url": "",
        "doc_type": "Main",
        "now_main": info["consolidated"] or celex,
        "missing_types": [], "missing_supplements": [],
    }

    # 法規已廢止 → 最高優先提醒
    if info["in_force"] == "No longer in force":
        msg = (f"此法規在 EUR-Lex 的效力狀態為「No longer in force」（已失效／已廢止），"
               f"請確認是否已由新法規取代。")
        return {**base, "judge_status": "obsolete", "judge_label": "有更新 (法規已廢止)",
                "judge_message": msg, "has_update": True, "reasons": [msg]}

    if not shown:
        msg = ("此法規在 EUR-Lex 為現行有效，但頁面未提供合併版(consolidated version)資訊"
               "（通常代表該法規自公布後尚未被修訂）。")
        return {**base, "judge_status": "unknown", "judge_label": "⚪ 無法判定",
                "judge_message": msg, "has_update": False, "reasons": [msg]}

    cur = (current_version or "").strip()
    if not cur:
        msg = (f"已建立基準版本：此法規現行合併版為 {shown}"
               f"（共 {len(info['all_consolidated'])} 個歷史合併版）。"
               f"原「目前使用版本」為空白，請文管人員確認後填入，之後即可自動比對改版。")
        return {**base, "judge_status": "baseline", "judge_label": "已建立基準版本",
                "judge_message": msg, "has_update": False, "reasons": [msg]}

    if _norm_ver(cur) == _norm_ver(shown):
        msg = f"目前使用版本與 EUR-Lex 現行合併版 {shown} 一致，無需動作。"
        return {**base, "judge_status": "valid", "judge_label": "無更新",
                "judge_message": msg, "has_update": False, "reasons": [msg]}

    msg = (f"EUR-Lex 現行合併版已更新為 {shown}，與目前使用版本（{cur}）不同，"
           f"表示此法規已有修訂併入，請取得最新合併版。")
    return {**base, "judge_status": "obsolete", "judge_label": "有更新 (已發布新合併版)",
            "judge_message": msg, "has_update": True, "reasons": [msg]}


def _norm_ver(v: str) -> str:
    """版本字串正規化（僅保留數字），讓 '2026-01-01'、'20260101'、'01/01/2026' 視為相同。"""
    return re.sub(r"\D", "", v or "")


# ---------------------------------------------------------------------------
# 二、執委會指引清單文件
# ---------------------------------------------------------------------------
VERSION_SUFFIX = re.compile(r"\s+(v\.?\s*\d+(?:\.\d+)?|rev\.?\s*\d+(?:\.\d+)?)\s*$", re.I)


def split_guidance_version(text: str):
    """將指引文件標題拆為 (名稱, 版本)。

    'Manual on borderline ... 2017/746 v5' -> ('Manual on borderline ... 2017/746', 'v5')
    'MDCG 2022-5 rev.1'                    -> ('MDCG 2022-5', 'rev.1')
    """
    t = " ".join((text or "").split())
    m = VERSION_SUFFIX.search(t)
    if not m:
        return t, ""
    return t[:m.start()].strip(), re.sub(r"\s+", "", m.group(1))


def _norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


async def fetch_guidance_index(client: httpx.AsyncClient) -> dict:
    """抓取執委會指引清單頁，回傳 {正規化文件名稱: (顯示標題, 版本)}。"""
    from crawlers.html_parser import parse_html

    resp = await client.get(GUIDANCE_LIST_URL)
    resp.raise_for_status()
    soup = parse_html(resp.text)
    index = {}
    for a in soup.find_all("a", href=True):
        text = re.sub(r"\s+", " ", a.get_text(strip=True))
        if len(text) < 6:
            continue
        name, version = split_guidance_version(text)
        key = _norm_name(name)
        if key and key not in index:
            index[key] = (text, version)
    return index


def _judge_guidance(name: str, current_version: str, index: dict) -> dict:
    doc_name, doc_version = split_guidance_version(name)
    key = _norm_name(doc_name)

    entry = index.get(key)
    if entry is None:
        # 名稱前綴比對（清單標題可能較長，例如附帶副標）
        for k, v in index.items():
            if k.startswith(key) or key.startswith(k):
                entry = v
                break

    if entry is None:
        return _manual_result(
            name,
            "此文件未出現在執委會現行指引清單頁，可能已被取代或撤回，請人工確認。",
            source_url=GUIDANCE_LIST_URL)

    listed_title, listed_version = entry
    base = {
        "ok": True,
        "source_url": GUIDANCE_LIST_URL,
        "found_title": listed_title,
        "now_status": "In force",
        "now_title": listed_title,
        "now_stage": "",
        "now_year": listed_version or "（清單未標示版本）",
        "now_list": [{"status": "In force", "title": listed_title}],
        "previously": [],
        "newer_title": "", "newer_kind": "", "newer_year": "", "newer_url": "",
        "doc_type": "Main",
        "now_main": listed_title,
        "missing_types": [], "missing_supplements": [],
    }

    held = (doc_version or current_version or "").strip()
    if not listed_version:
        msg = (f"文件仍列於執委會現行指引清單，但清單未標示版本號，無法自動比對版本，"
               f"請人工確認。清單標題：{listed_title}")
        return {**base, "judge_status": "unknown", "judge_label": "⚪ 無法判定",
                "judge_message": msg, "has_update": False, "reasons": [msg]}

    if not held:
        msg = (f"已建立基準版本：執委會現行指引清單所列版本為 {listed_version}。"
               f"原「目前使用版本」為空白，請文管人員確認後填入。")
        return {**base, "judge_status": "baseline", "judge_label": "已建立基準版本",
                "judge_message": msg, "has_update": False, "reasons": [msg]}

    if _norm_ver(held) == _norm_ver(listed_version):
        msg = f"目前使用版本 {held} 與執委會現行指引清單一致，無需動作。"
        return {**base, "judge_status": "valid", "judge_label": "無更新",
                "judge_message": msg, "has_update": False, "reasons": [msg]}

    msg = (f"執委會現行指引清單所列版本已是 {listed_version}，"
           f"您持有的為 {held}，請取得最新版本。清單標題：{listed_title}")
    return {**base, "judge_status": "obsolete", "judge_label": "有更新 (已發布新版)",
            "judge_message": msg, "has_update": True, "reasons": [msg]}


# ---------------------------------------------------------------------------
# 三、無法自動判定
# ---------------------------------------------------------------------------
def _manual_result(name: str, reason: str, source_url: str = "") -> dict:
    return {
        "ok": True,
        "source_url": source_url,
        "found_title": "",
        "now_status": "", "now_title": "", "now_stage": "", "now_year": "",
        "now_list": [], "previously": [],
        "newer_title": "", "newer_kind": "", "newer_year": "", "newer_url": "",
        "doc_type": "Main",
        "judge_status": "manual",
        "judge_label": "需人工確認",
        "judge_message": reason,
        "now_main": "",
        "missing_types": [], "missing_supplements": [],
        "has_update": False,
        "reasons": [reason],
    }


# ---------------------------------------------------------------------------
# 分派與對外介面
# ---------------------------------------------------------------------------
def classify(name: str) -> str:
    """判斷此筆文件應以哪種方式判定：'eurlex' | 'manual' | 'guidance'。

    判定為 EUR-Lex 法規時要求名稱**以** Regulation/Directive/Decision 開頭，不能只是內含 ——
    指引文件的標題常引用法規編號（例：'Manual on borderline and classification under
    Regulations (EU) 2017/745 and 2017/746 v3'），若只用內含比對會被誤判為 MDR 本身，
    抓回 MDR 的合併版日期而非該指引的版本。
    """
    n = (name or "").strip()
    for pattern, _hint in MANUAL_ONLY_HINTS:
        if re.search(pattern, n, re.IGNORECASE):
            return "manual"
    if re.match(r"^(Regulation|Directive|Decision)\b", n, re.IGNORECASE) and to_celex(n):
        return "eurlex"
    return "guidance"


def _manual_hint(name: str) -> str:
    for pattern, hint in MANUAL_ONLY_HINTS:
        if re.search(pattern, name or "", re.IGNORECASE):
            return hint
    return "此文件無公開清單可自動比對版本，請人工確認。"


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


async def _resolve_with(client, name, current_version, guidance_index):
    kind = classify(name)
    if kind == "manual":
        return _manual_result(name, _manual_hint(name))
    if kind == "eurlex":
        return await _judge_eurlex(client, name, current_version)
    if guidance_index is None:
        return _manual_result(name, "執委會指引清單頁取得失敗，無法比對版本。",
                              source_url=GUIDANCE_LIST_URL)
    return _judge_guidance(name, current_version, guidance_index)


async def resolve_source_url(standard_name: str, current_version: str = "") -> dict:
    """查詢單一 EU 法規／指引文件的現行版本與判讀。"""
    async with _client() as client:
        guidance_index = None
        if classify(standard_name) == "guidance":
            try:
                guidance_index = await fetch_guidance_index(client)
            except Exception as e:
                logger.warning("[eu_regulation] 指引清單取得失敗: %s", e)
        try:
            return await _resolve_with(client, standard_name, current_version, guidance_index)
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}


async def resolve_many(items: list, on_item=None) -> dict:
    """批量查找：指引清單頁整批只抓一次；EUR-Lex 逐筆查詢（共用連線）。"""
    out = {}
    if not items:
        return out

    async with _client() as client:
        guidance_index = None
        if any(classify(it.get("standard_name") or "") == "guidance" for it in items):
            try:
                guidance_index = await fetch_guidance_index(client)
                logger.info("[eu_regulation] 指引清單共 %d 筆文件", len(guidance_index))
            except Exception as e:
                logger.warning("[eu_regulation] 指引清單取得失敗: %s", e)

        for it in items:
            key = it["key"]
            try:
                result = await _resolve_with(
                    client, it.get("standard_name") or "",
                    it.get("current_version") or "", guidance_index,
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
