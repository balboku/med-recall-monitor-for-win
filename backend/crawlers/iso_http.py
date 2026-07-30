"""ISO 官網純 HTTP 存取（不需虛擬瀏覽器）。

背景：
    www.iso.org 的 Cloudflare 防護是「Managed Challenge」（被擋下時回應標頭帶
    `Cf-Mitigated: challenge`），判定依據主要是 TLS／HTTP2 指紋，而非 IP 或 User-Agent。
    因此以 curl_cffi 模擬 Chrome 的 TLS 指紋發出請求即可直接取得 200，不必啟動真實瀏覽器。
    實測（46 筆 ISO 標準的整批查找）：純 HTTP 24.7 秒 vs 虛擬瀏覽器 293.4 秒，約 12 倍，
    且兩者逐筆判定結果完全一致。

    另一半問題是「搜尋」：iso.org 的 search.html 是 Algolia InstantSearch，結果由前端 JS
    打 Algolia 取得——虛擬瀏覽器在這一步其實只是在替 Algolia 的 JS 渲染畫面。直接呼叫
    Algolia 查詢 API 即可拿到結構化 JSON（reference／seoURL），完全不經過 Cloudflare，
    且用的就是官網搜尋自己用的那個索引，結果集與瀏覽器路徑一致。

    Algolia 金鑰是官網內嵌在 search.html 的 search-only key，會隨官網更版而輪替，
    故每個行程第一次查詢時先從 search.html 動態解析，解析失敗才退回下方硬編碼預設值。

定位：
    本模組只負責「取得資料」，不含任何判定邏輯。判定仍由 iso_browser.parse_lifecycle()
    與 standards_common.judge_update() 處理，兩種取得方式共用同一套判定管線
    （見 CLAUDE.md 架構鐵則）。iso_browser 的四個對外同步函式會優先走本模組，
    取得失敗才退回 nodriver。

停用方式：
    設定環境變數 ISO_HTTP_DISABLE=1 可強制略過本模組、一律使用虛擬瀏覽器
    （Cloudflare 規則若日後收緊，這是不改程式碼的緊急退路）。

對外介面（皆為同步，無事件迴圈限制，可直接呼叫）：
    available()          → 本路徑目前是否可用
    search(query)        → [(標準頁絕對網址, 參照字串), ...]，格式同 extract_search_results()
    fetch_html(url)      → 標準頁 HTML（內容與虛擬瀏覽器取得者相同）
"""
import os
import re
import json
import time
import shutil
import logging
import tempfile
import threading
from pathlib import Path
from urllib.parse import quote, urljoin

logger = logging.getLogger(__name__)

ISO_BASE = "https://www.iso.org"
SEARCH_PAGE = f"{ISO_BASE}/search.html"

# 官網 search.html 內嵌的 Algolia search-only 設定；動態解析失敗時的後備值。
DEFAULT_ALGOLIA = {
    "app_id": "JCL49WV5AR",
    "api_key": (
        "MzcxYjJlODU3ZmEwYmRhZTc0NTZlODNlZmUwYzVjNDRiZDEzMzRjMjYwNTAwODU3YmIzNjEwZmNj"
        "NDFlOTBjYXJlc3RyaWN0SW5kaWNlcz1QUk9EX2lzb29yZ19lbiUyQ1BST0RfaXNvb3JnX2VuX2F1"
        "dG9jb21wbGV0ZQ=="
    ),
    "index": "PROD_isoorg_en",
}

# curl_cffi 的瀏覽器指紋樣板。實測同一時間不同樣板通過率不同（chrome131 曾回 403），
# 故依序輪替重試，並記住上次成功者優先使用。
IMPERSONATE_PROFILES = ("chrome136", "chrome124", "safari18_0")

REQUEST_TIMEOUT = 30.0
MIN_INTERVAL = 0.5  # 對 iso.org 的最小請求間隔（秒），避免整批掃描打得太急
CHALLENGE_MARKERS = ("just a moment", "attention required", "checking your browser",
                     "cf-mitigated")

try:
    from curl_cffi import requests as _cffi_requests
    HTTP_AVAILABLE = True
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - 視部署環境而定
    _cffi_requests = None
    HTTP_AVAILABLE = False
    _IMPORT_ERROR = e

_lock = threading.Lock()          # 序列化請求，讓速率限制真正生效
_sessions = {}                    # {impersonate 樣板: curl_cffi Session}
_last_profile = ""                # 上次成功的樣板
_algolia = None                   # 快取的 Algolia 設定
_ca_bundle_path = None            # 快取的 CA 憑證路徑
_last_request = 0.0


class IsoHttpError(RuntimeError):
    """純 HTTP 路徑取得失敗（呼叫端應考慮退回虛擬瀏覽器）。"""


def available() -> bool:
    """本路徑目前是否可用（套件已安裝且未被環境變數停用）。"""
    if os.getenv("ISO_HTTP_DISABLE", "").strip().lower() in ("1", "true", "yes"):
        return False
    return HTTP_AVAILABLE


def import_error():
    """curl_cffi 匯入失敗的原因（供錯誤訊息使用）。"""
    return _IMPORT_ERROR


def _ensure_available():
    if not HTTP_AVAILABLE:
        raise IsoHttpError(
            f"套件 curl_cffi 無法載入（{_IMPORT_ERROR}）。"
            "請安裝 curl_cffi，詳見 requirements-local.txt 說明。"
        )
    if not available():
        raise IsoHttpError("環境變數 ISO_HTTP_DISABLE 已停用純 HTTP 路徑。")


def _looks_like_challenge(text: str) -> bool:
    """判斷回應是否為 Cloudflare 挑戰頁（狀態碼可能是 403，也可能是 200）。"""
    head = (text or "")[:2000].lower()
    return any(m in head for m in CHALLENGE_MARKERS)


def _ca_bundle() -> str:
    """回傳可供 libcurl 使用的 CA 憑證檔路徑（無法決定時回傳空字串，交由預設值處理）。

    libcurl 開不了含非 ASCII 字元的憑證路徑，會直接回報
    `curl: (77) error setting certificate verify locations`。本專案位於中文路徑下，
    certifi 就裝在 backend/.venv 之內，必然踩到這個限制，因此偵測到非 ASCII 路徑時
    先把憑證複製到系統暫存目錄（ASCII 路徑）再交給 libcurl。
    """
    global _ca_bundle_path
    if _ca_bundle_path is not None:
        return _ca_bundle_path

    _ca_bundle_path = ""
    try:
        import certifi
        src = Path(certifi.where())
        if str(src).isascii():
            _ca_bundle_path = str(src)
            return _ca_bundle_path
        dst = Path(tempfile.gettempdir()) / "medwatch_cacert.pem"
        if not str(dst).isascii():
            raise RuntimeError(f"暫存目錄路徑仍含非 ASCII 字元：{dst}")
        if not dst.exists() or dst.stat().st_size != src.stat().st_size:
            shutil.copyfile(src, dst)
        _ca_bundle_path = str(dst)
        logger.info("[iso_http] CA 憑證改用 %s（libcurl 無法讀取非 ASCII 路徑）", dst)
    except Exception as e:
        logger.warning("[iso_http] 準備 CA 憑證失敗（%s），改用套件預設值", e)
    return _ca_bundle_path


def _session_for(profile: str):
    """取得（並快取）指定指紋樣板的連線工作階段，讓整批請求共用連線。"""
    sess = _sessions.get(profile)
    if sess is None:
        ca = _ca_bundle()
        kwargs = {"impersonate": profile}
        if ca:
            kwargs["verify"] = ca
        sess = _cffi_requests.Session(**kwargs)
        _sessions[profile] = sess
    return sess


def _throttle():
    global _last_request
    elapsed = time.time() - _last_request
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_request = time.time()


def _get(url: str) -> str:
    """取得 iso.org 頁面內容；所有指紋樣板皆失敗時丟出 IsoHttpError。"""
    _ensure_available()
    global _last_profile
    profiles = list(IMPERSONATE_PROFILES)
    if _last_profile in profiles:
        profiles.remove(_last_profile)
        profiles.insert(0, _last_profile)

    errors = []
    with _lock:
        for profile in profiles:
            _throttle()
            try:
                resp = _session_for(profile).get(url, timeout=REQUEST_TIMEOUT)
            except Exception as e:
                errors.append(f"{profile}: {type(e).__name__}: {e}")
                continue
            if resp.status_code == 200 and not _looks_like_challenge(resp.text):
                _last_profile = profile
                return resp.text
            errors.append(
                f"{profile}: HTTP {resp.status_code}"
                + ("（Cloudflare 挑戰頁）" if _looks_like_challenge(resp.text) else "")
            )
    raise IsoHttpError(f"取得 {url} 失敗；{'；'.join(errors)}")


def _post_json(url: str, payload: dict, headers: dict) -> dict:
    """對 Algolia 送出查詢（該網域無 Cloudflare，不套用 iso.org 的速率限制）。"""
    _ensure_available()
    profile = _last_profile or IMPERSONATE_PROFILES[0]
    try:
        resp = _session_for(profile).post(
            url, data=json.dumps(payload), headers=headers, timeout=REQUEST_TIMEOUT
        )
    except Exception as e:
        raise IsoHttpError(f"Algolia 查詢失敗：{type(e).__name__}: {e}")
    if resp.status_code != 200:
        raise IsoHttpError(f"Algolia 查詢失敗：HTTP {resp.status_code} {resp.text[:200]}")
    try:
        return resp.json()
    except Exception as e:
        raise IsoHttpError(f"Algolia 回應非 JSON：{e}")


def _load_algolia() -> dict:
    """取得 Algolia 設定：優先自 search.html 動態解析，失敗則用內建預設值。"""
    global _algolia
    if _algolia is not None:
        return _algolia

    cfg = dict(DEFAULT_ALGOLIA)
    try:
        html = _get(SEARCH_PAGE)
        start = html.find("algolia = {")
        block = html[start:start + 1200] if start >= 0 else ""
        app = re.search(r"appID\s*:\s*'([^']+)'", block)
        key = re.search(r"apiKey\s*:\s*'([^']+)'", block)
        idx = re.search(r"index\s*:\s*\{.*?name\s*:\s*'([^']+)'", block, re.S)
        if app and key:
            cfg["app_id"], cfg["api_key"] = app.group(1), key.group(1)
            if idx:
                cfg["index"] = idx.group(1)
            logger.info("[iso_http] 已自 search.html 取得 Algolia 設定（index=%s）", cfg["index"])
        else:
            logger.warning("[iso_http] search.html 內未找到 Algolia 設定，改用內建預設值")
    except Exception as e:
        logger.warning("[iso_http] 取得 Algolia 設定失敗（%s），改用內建預設值", e)

    _algolia = cfg
    return cfg


def _abs_url(href: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return urljoin(ISO_BASE + "/", href.lstrip("/"))


def search(query: str, limit: int = 20) -> list:
    """查詢 ISO 官網搜尋索引，回傳 [(標準頁絕對網址, 參照字串), ...]。

    回傳格式刻意與 iso_browser.extract_search_results() 相同，可直接餵給 pick_target()。

    兩點與瀏覽器路徑對齊／刻意不同之處：
      * 只保留 /standard/ 頁面 —— 與瀏覽器路徑只取 /standard/ 連結一致，濾掉
        /sectors/ 等非標準頁的命中項。
      * 比對文字用 `reference`（如 'ISO 11607-1:2019'）而「不」併入頁面標題：
        修正案的標題本身含 'Amendment 1: …'，一旦併入，主標準也會被
        detect_doc_type() 誤判為 AMD，pick_target() 的主標準優先序就會失效。

    查無結果時回傳空清單（代表官網確實沒有這個標準，不是取得失敗）；
    取得失敗一律丟出 IsoHttpError。
    """
    cfg = _load_algolia()
    data = _post_json(
        f"https://{cfg['app_id']}-dsn.algolia.net/1/indexes/{cfg['index']}/query",
        {"params": f"query={quote(query)}&hitsPerPage={limit}"},
        {
            "X-Algolia-Application-Id": cfg["app_id"],
            "X-Algolia-API-Key": cfg["api_key"],
            "Content-Type": "application/json",
        },
    )

    results, seen = [], set()
    for hit in data.get("hits") or []:
        seo = hit.get("seoURL") or ""
        reference = (hit.get("reference") or "").strip()
        if "/standard/" not in seo or not reference:
            continue
        url = _abs_url(seo)
        if url in seen:
            continue
        seen.add(url)
        results.append((url, re.sub(r"\s+", " ", reference)))
    return results


def fetch_html(url: str) -> str:
    """取得 iso.org 頁面 HTML（內容與虛擬瀏覽器取得者相同，可直接餵給 parse_lifecycle）。"""
    return _get(url)
