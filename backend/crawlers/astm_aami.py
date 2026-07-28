"""ASTM / AAMI 標準版本追蹤（R500）。

  ASTM（7 筆）
      astm.org 可直接以純 HTTP 存取，**無反爬蟲防護**，且「短代號網址」會自動導向
      該標準的現行版頁面：

          https://www.astm.org/f1980.html  →  .../f1980-21.html
          https://www.astm.org/f88.html    →  .../f0088_f0088m-23.html
          https://www.astm.org/f1140.html  →  .../f1140_f1140m-13r25.html

      因此只要由標準代號組出短網址、跟隨轉址，再從最終網址的 slug 取出版本即可，
      不需解析頁面內容。

  AAMI（3 筆）
      ANSI Webstore 與 AAMI 自家商店（array.aami.org）皆受 Cloudflare 防護
      （回傳 403「Just a moment…」），AAMI 官網的標準頁也沒有逐項版本清單，
      無公開來源可自動比對，標記為需人工確認。

ASTM 版本字串的兩種寫法：
      文件標題  F1140M-13(2020)e1     ← 括號為重新核准年、eN 為編輯修訂
      網址 slug f1140_f1140m-13r20e01 ← 重新核准寫成 rYY、編輯修訂寫成 eNN
    兩者互為對應，比對時一律轉為 (基準年, 重新核准年) 後再比較。
"""
import re
import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

ASTM_URL = "https://www.astm.org/{designation}.html"
REQUEST_TIMEOUT = 40.0
REQUEST_INTERVAL = 1.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

AAMI_HINT = (
    "AAMI 標準的販售通路（ANSI Webstore 與 array.aami.org）皆受 Cloudflare 防護而無法自動存取，"
    "AAMI 官網亦未提供逐項版本清單，無公開來源可比對版本，"
    "請人工至 ANSI Webstore 或 AAMI 網站確認現行版本。"
)


def parse_designation(title: str):
    """由標準名稱取出 (體系, 代號, 版本字串)。

    'ASTM F88/F88M-23'        -> ('ASTM', 'F88',    '23')
    'ASTM F1140M-13(2020)e1'  -> ('ASTM', 'F1140M', '13(2020)e1')
    'ANSI/AAMI ST98:2022'     -> ('AAMI', 'ST98',   '2022')
    無法判定時回傳 (None, '', '')。
    """
    t = " ".join((title or "").split())

    if re.search(r"\bAAMI\b", t, re.IGNORECASE):
        m = re.search(r"\b(?:ANSI/)?AAMI\s+((?:TIR\s*)?[A-Z]*\d+)", t, re.IGNORECASE)
        desig = re.sub(r"\s+", "", m.group(1)) if m else ""
        ver = t.split(":", 1)[1].strip() if ":" in t else ""
        return "AAMI", desig, ver

    m = re.match(r"\s*ASTM\s+([A-Z]+\d+[A-Z]?)(?:/[A-Z0-9]+)?\s*-?\s*(.*)$", t, re.IGNORECASE)
    if m:
        return "ASTM", m.group(1).upper(), m.group(2).strip()
    return None, "", ""


def _yy_to_year(value) -> int:
    """兩位數年份轉四位數（13 → 2013、99 → 1999）；已是四位數則原樣回傳。"""
    n = int(value)
    if n >= 1000:
        return n
    return 1900 + n if n > 50 else 2000 + n


def parse_astm_version(version: str):
    """解析 ASTM 版本字串，回傳 (基準年, 重新核准年or None)。

    支援文件標題與網址 slug 兩種寫法：
        '23'          -> (2023, None)
        '13(2020)e1'  -> (2013, 2020)
        '13r25e01'    -> (2013, 2025)
        '23e01'       -> (2023, None)
    無法解析時回傳 (None, None)。
    """
    s = (version or "").strip().lower()
    m = re.match(r"(\d{2,4})", s)
    if not m:
        return None, None
    base = _yy_to_year(m.group(1))

    reapproved = None
    paren = re.search(r"\((\d{4})\)", s)          # 標題寫法 (2020)
    if paren:
        reapproved = int(paren.group(1))
    else:
        rr = re.search(r"r(\d{2,4})", s)          # slug 寫法 r25
        if rr:
            reapproved = _yy_to_year(rr.group(1))
    return base, reapproved


def effective_year(version: str):
    """版本的「有效年份」：有重新核准年就用它，否則用基準年。"""
    base, reapproved = parse_astm_version(version)
    return reapproved or base


def version_from_slug(slug: str) -> str:
    """由最終網址 slug 取出版本字串：'f1140_f1140m-13r25' -> '13r25'。"""
    name = (slug or "").rsplit("/", 1)[-1].replace(".html", "")
    return name.split("-", 1)[1] if "-" in name else ""


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


async def _fetch_current(client: httpx.AsyncClient, designation: str):
    """以短代號網址查現行版，回傳 (最終網址, 版本字串) 或 None。

    代號帶公制後綴 M（例如 F1140M）時短網址會 404，需去掉 M 再試一次。
    """
    tried = [designation]
    if len(designation) > 1 and designation.upper().endswith("M"):
        tried.append(designation[:-1])

    for desig in tried:
        try:
            resp = await client.get(ASTM_URL.format(designation=desig.lower()))
        except Exception:
            continue
        if resp.status_code == 200:
            final = str(resp.url)
            version = version_from_slug(final)
            if version:
                return final, version
        await asyncio.sleep(0.3)
    return None


def judge_astm(title: str, current_version: str, held_version: str,
               final_url: str, current_slug_version: str) -> dict:
    held = held_version or current_version
    held_year = effective_year(held)
    now_year = effective_year(current_slug_version)
    shown = current_slug_version

    designation_note = ""
    if held and current_slug_version and \
            re.sub(r"[^a-z0-9]", "", held.lower()) != re.sub(r"[^a-z0-9]", "", current_slug_version.lower()):
        designation_note = f"（官網現行版標示為 {current_slug_version}）"

    if not held_year or not now_year:
        msg = (f"已取得 ASTM 官網現行版 {current_slug_version}，"
               f"但無法解析版本年份以進行比對，請人工確認。")
        return _result("unknown", "⚪ 無法判定", msg, False, shown, final_url, "")

    if now_year > held_year:
        msg = (f"ASTM 官網現行版為 {current_slug_version}（{now_year} 年），"
               f"您持有的是 {held}（{held_year} 年），請取得最新版本。")
        return _result("obsolete", "有更新 (已發布新版)", msg, True, shown, final_url, "")

    if now_year < held_year:
        msg = (f"您持有的版本（{held}）比官網現行版（{current_slug_version}）還新，"
               f"請確認標準代號或版本紀錄是否有誤。")
        return _result("unknown", "⚪ 無法判定", msg, False, shown, final_url, "")

    msg = f"與 ASTM 官網現行版一致（{now_year} 年），無需動作。{designation_note}"
    return _result("valid", "無更新", msg, False, shown, final_url, "")


# ---------------------------------------------------------------------------
# 對外介面
# ---------------------------------------------------------------------------
def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
    )


async def _resolve_with(client: httpx.AsyncClient, title: str, current_version: str) -> dict:
    body, designation, held_version = parse_designation(title)

    if body == "AAMI":
        return _result("manual", "需人工確認", AAMI_HINT, False, "",
                       "https://webstore.ansi.org/", "")

    if body != "ASTM" or not designation:
        msg = f"無法從名稱解析出 ASTM／AAMI 標準代號（{title}），請確認名稱格式。"
        return _result("manual", "需人工確認", msg, False, "", "", "")

    found = await _fetch_current(client, designation)
    if not found:
        msg = (f"ASTM 官網查無代號 {designation} 的現行版頁面，"
               f"該標準可能已撤銷或代號有誤，請人工確認。")
        return _result("manual", "需人工確認", msg, False, "",
                       ASTM_URL.format(designation=designation.lower()), "")

    final_url, slug_version = found
    return judge_astm(title, current_version, held_version, final_url, slug_version)


async def resolve_source_url(standard_name: str, current_version: str = "") -> dict:
    """查詢單一 ASTM／AAMI 標準的現行版本與判讀。"""
    async with _client() as client:
        try:
            return await _resolve_with(client, standard_name, current_version)
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}


async def resolve_many(items: list, on_item=None) -> dict:
    """批量查找：共用單一連線並於請求間留間隔。"""
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
