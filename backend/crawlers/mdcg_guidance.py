"""MDCG 指引文件版本追蹤（R302）。

資料來源：
    執委會「MDCG endorsed documents and other guidance」清單頁（純 HTTP 即可取得）。
    註：舊網址 health.ec.europa.eu/medical-devices-dialogue-between-interested-parties/...
    已失效（HTTP 404），執委會改版後搬遷至 medical-devices-sector/new-regulations/ 之下。

版本概念：
    MDCG 文件的識別是「MDCG 年份-流水號」（可再帶子編號，例如 MDCG 2024-1-5），
    版本則是修訂版次 `rev.N`；未標示 rev 即為初版。

解析上的三個陷阱（皆為實測清單中真實存在的情形）：
    1. 同一編號會出現多筆連結：主文件、附錄（Appendix A）、附件（Annex）等。
       若以 dict 直接覆寫，會把主文件的 rev 蓋掉 ——
       例如 `MDCG 2021-15 rev.1` 會被 `MDCG 2021-15/MDCG 2024-7 Annex` 覆蓋而漏判更新。
    2. 子編號文件是獨立文件：`MDCG 2024-1-5` 不可被歸到 `MDCG 2024-1` 之下。
    3. 部分文件同時列出多個版本，需取修訂版次最高者。
"""
import re
import logging

import httpx

logger = logging.getLogger(__name__)

MDCG_LIST_URL = (
    "https://health.ec.europa.eu/medical-devices-sector/new-regulations/"
    "guidance-mdcg-endorsed-documents-and-other-guidance_en"
)
REQUEST_TIMEOUT = 60.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# 文件編號：MDCG 年份-流水號（可含子編號，如 MDCG 2024-1-5）
DOC_RE = re.compile(r"^(MDCG\s+\d{4}-\d+(?:-\d+)*)\s*(.*)$", re.IGNORECASE)
REV_RE = re.compile(r"\brev\.?\s*(\d+)", re.IGNORECASE)


def normalize_doc_id(doc_id: str) -> str:
    """'MDCG  2022-5' -> 'MDCG 2022-5'（統一空白），供比對使用。"""
    return re.sub(r"\s+", " ", (doc_id or "").strip()).upper()


def parse_reference(text: str):
    """將文件標題拆為 (文件編號, 修訂版次, 其餘描述)。

    'MDCG 2022-5 rev.1'                  -> ('MDCG 2022-5', 1, '')
    'MDCG 2024-5 Appendix A'             -> ('MDCG 2024-5', 0, 'Appendix A')
    'MDCG 2021-15/MDCG 2024-7 Annex'     -> ('MDCG 2021-15', 0, '/MDCG 2024-7 Annex')
    'MDCG 2024-1-5'                      -> ('MDCG 2024-1-5', 0, '')
    非 MDCG 文件回傳 (None, 0, '')。
    """
    t = re.sub(r"\s+", " ", (text or "").strip())
    m = DOC_RE.match(t)
    if not m:
        return None, 0, ""
    doc_id = normalize_doc_id(m.group(1))
    rest = m.group(2).strip()

    rev = 0
    rm = REV_RE.search(rest)
    if rm:
        rev = int(rm.group(1))
        rest = REV_RE.sub("", rest).strip()
    # 清單中的修訂版次寫法不一致，有的是 'MDCG 2021-6 rev.1'，有的是 'MDCG 2021-6 - rev.1'。
    # 移除 rev 後可能殘留分隔符號，若不清掉會被誤認為附錄／附件而漏判修訂版次。
    rest = rest.strip(" -–—:,;()").strip()
    return doc_id, rev, rest


def parse_listing(html: str) -> dict:
    """解析清單頁，回傳 {文件編號: {revision, title, variants}}。

    revision 取「主文件」（編號後沒有附錄／附件等額外描述者）中最高的修訂版次；
    若該編號在清單中只有附錄類項目，則 has_main=False，交由判定端提示人工確認。
    """
    from crawlers.html_parser import parse_html

    soup = parse_html(html)
    index = {}
    for a in soup.find_all("a"):
        text = re.sub(r"\s+", " ", a.get_text(strip=True))
        doc_id, rev, rest = parse_reference(text)
        if not doc_id:
            continue

        entry = index.setdefault(doc_id, {
            "revision": 0, "title": "", "variants": [], "has_main": False,
        })
        entry["variants"].append(text)

        is_main = not rest  # 編號（與 rev）之外沒有其他描述 → 主文件
        if is_main:
            if not entry["has_main"] or rev > entry["revision"]:
                entry["has_main"] = True
                entry["revision"] = rev
                entry["title"] = text
        elif not entry["has_main"] and not entry["title"]:
            entry["title"] = text
    return index


def _rev_label(rev: int) -> str:
    return f"rev.{rev}" if rev else "初版（無 rev）"


def judge_mdcg(title: str, current_version: str, index: dict) -> dict:
    """判定單一 MDCG 文件是否有新修訂版。

    注意：R302 的「目前使用版本」(current_version) 欄位在匯入時被污染 ——
    匯入程式把文件流水號誤讀為年份（例如 'MDCG 2024-13' 被解析成 '2013'），
    故一律以**法規名稱(title)中的 rev.N** 為準，僅在名稱未帶 rev 且
    current_version 本身像修訂版次時才採用它。
    """
    doc_id, held_rev, _rest = parse_reference(title)
    if not doc_id:
        msg = f"無法從名稱解析出 MDCG 文件編號（{title}），請確認名稱格式。"
        return _result(title, "manual", "需人工確認", msg, False, "")

    if not REV_RE.search(title or ""):
        cv_rev = REV_RE.search(current_version or "")
        if cv_rev:
            held_rev = int(cv_rev.group(1))

    entry = index.get(doc_id)
    if entry is None:
        msg = (f"{doc_id} 未出現在執委會現行 MDCG 指引清單頁，"
               f"可能已被取代、撤回或改列於其他文件，請人工確認。")
        return _result(title, "manual", "需人工確認", msg, False, "", doc_id=doc_id)

    listed_rev = entry["revision"]
    listed_title = entry["title"] or doc_id
    shown = _rev_label(listed_rev)

    if not entry["has_main"]:
        msg = (f"{doc_id} 在清單頁僅出現附錄／附件項目（{', '.join(entry['variants'][:3])}），"
               f"未見主文件，無法判定修訂版次，請人工確認。")
        return _result(title, "unknown", "⚪ 無法判定", msg, False, shown,
                       doc_id=doc_id, listed_title=listed_title)

    if listed_rev > held_rev:
        msg = (f"執委會現行清單所列為 {listed_title}（{_rev_label(listed_rev)}），"
               f"您持有的是 {_rev_label(held_rev)}，請取得最新修訂版。")
        return _result(title, "obsolete", "有更新 (已發布新修訂版)", msg, True, shown,
                       doc_id=doc_id, listed_title=listed_title)

    if listed_rev < held_rev:
        msg = (f"您持有的版本（{_rev_label(held_rev)}）比執委會清單所列"
               f"（{_rev_label(listed_rev)}）還新，請確認文件編號或清單是否有誤。")
        return _result(title, "unknown", "⚪ 無法判定", msg, False, shown,
                       doc_id=doc_id, listed_title=listed_title)

    msg = f"{doc_id} 與執委會現行清單一致（{_rev_label(listed_rev)}），無需動作。"
    return _result(title, "valid", "無更新", msg, False, shown,
                   doc_id=doc_id, listed_title=listed_title)


def _result(title, status, label, message, has_update, shown,
            doc_id="", listed_title=""):
    return {
        "ok": True,
        "source_url": MDCG_LIST_URL,
        "found_title": listed_title,
        "now_status": "In force" if status == "valid" else "",
        "now_title": listed_title or doc_id,
        "now_stage": "",
        "now_year": shown,
        "now_list": ([{"status": "In force", "title": listed_title}] if listed_title else []),
        "previously": [],
        "newer_title": "", "newer_kind": "", "newer_year": "", "newer_url": "",
        "doc_type": "Main",
        "judge_status": status,
        "judge_label": label,
        "judge_message": message,
        "now_main": listed_title or doc_id,
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


async def fetch_index(client: httpx.AsyncClient) -> dict:
    resp = await client.get(MDCG_LIST_URL)
    resp.raise_for_status()
    return parse_listing(resp.text)


async def resolve_source_url(standard_name: str, current_version: str = "") -> dict:
    """查詢單一 MDCG 文件的現行修訂版次與判讀。"""
    async with _client() as client:
        try:
            index = await fetch_index(client)
        except Exception as e:
            return {"ok": False, "error": f"MDCG 指引清單取得失敗：{type(e).__name__}: {e}"}
    return judge_mdcg(standard_name, current_version, index)


async def resolve_many(items: list, on_item=None) -> dict:
    """批量查找：整批只抓一次清單頁。"""
    out = {}
    if not items:
        return out

    async with _client() as client:
        try:
            index = await fetch_index(client)
            logger.info("[mdcg_guidance] 清單共 %d 份 MDCG 文件", len(index))
        except Exception as e:
            err = {"ok": False, "error": f"MDCG 指引清單取得失敗：{type(e).__name__}: {e}"}
            for it in items:
                out[it["key"]] = err
                if on_item is not None:
                    try:
                        on_item(it["key"], it, err)
                    except Exception as cb_err:
                        logger.warning("on_item 回呼錯誤（%s）: %s", it["key"], cb_err)
            return out

    for it in items:
        key = it["key"]
        try:
            result = judge_mdcg(
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
