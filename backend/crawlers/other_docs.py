"""其他國際文件的版本狀態分類（R000）。

⚠️ 本模組**不是爬蟲**，而是「知識型分類器」。

原因：R000 這 11 筆的來源各自獨立且皆無可用的公開版本清單，實測結果：

    來源                     實測結果
    imdrf.org               連線逾時／被重置，無法穩定存取
    FDA MDSAP 頁面          404（頁面已搬遷且無穩定入口）
    ISPE（GAMP 5）          會員／付費牆
    ISTA                    付費牆
    GHTF                    組織已於 2012 年解散，網站不再維護

為這 11 筆各建一支爬蟲的投資報酬率極低，且會產生長期維護負擔。
因此改為依文件性質給出**具體且誠實的狀態**，而非籠統的「不支援」——
其中 GHTF 系列可明確判定為「不再改版」，這對文管而言是實際可用的結論。

若日後某個來源變得可穩定存取，應改寫為真正的 adapter 並移出本模組。
"""
import re
import logging

logger = logging.getLogger(__name__)

# (比對樣式, 狀態標籤, 說明)
CLASSIFICATIONS = (
    (
        r"^\s*GHTF\b",
        "已停止維護 (不再改版)",
        "GHTF（Global Harmonization Task Force）已於 2012 年解散，並由 IMDRF"
        "（International Medical Device Regulators Forum）接續。此文件屬凍結的歷史文件，"
        "不會再發布新版本，無需持續追蹤版本更新；但建議確認對應主題是否已有 IMDRF 文件取代。",
    ),
    (
        r"\bIMDRF\b",
        "需人工確認",
        "IMDRF 官網（imdrf.org）自本系統所在網路環境連線逾時／被重置，無法穩定自動存取。"
        "IMDRF 仍持續發布新文件，請人工至 imdrf.org 的 Documents 頁面確認是否已有新版。",
    ),
    (
        r"\bGAMP\b",
        "需人工確認",
        "GAMP 指引由 ISPE 發行，僅供會員／付費取得，無公開的版本頁可自動比對，"
        "請人工至 ISPE 網站確認現行版本。",
    ),
    (
        r"\bISTA\b",
        "需人工確認",
        "ISTA 測試規範為付費標準，無公開的版本頁可自動比對，"
        "請人工至 ISTA 網站確認現行版本。",
    ),
    (
        r"\bMDSAP\b",
        "需人工確認",
        "MDSAP 稽核程序文件散見於各主管機關網站，FDA 的對應頁面已搬遷且無穩定入口，"
        "無法自動比對版本，請人工至 FDA MDSAP 專區確認現行版本。",
    ),
    (
        r"\bUN\s*38\.?8\b|\bUN\b.*Transportation Testing",
        "需人工確認",
        "UN 38.3／38.8 屬《聯合國危險物品運輸試驗和標準手冊》的一部分，"
        "以修訂版(Revision)方式整本改版，無逐項版本頁可自動比對，"
        "請人工確認目前採用的手冊修訂版本。",
    ),
)

DEFAULT_MESSAGE = (
    "此文件無公開的版本清單可自動比對版本，請人工向發行單位確認現行版本。"
)


def classify(title: str):
    """回傳 (狀態標籤, 說明)。"""
    t = title or ""
    for pattern, label, message in CLASSIFICATIONS:
        if re.search(pattern, t, re.IGNORECASE):
            return label, message
    return "需人工確認", DEFAULT_MESSAGE


def _result(label: str, message: str, has_update: bool = False) -> dict:
    # 「已停止維護」屬確定結論，judge_status 用 valid 讓它不被列為待處理；
    # 其餘為 manual，代表需要人工介入。
    status = "valid" if label.startswith("已停止維護") else "manual"
    return {
        "ok": True,
        "source_url": "",
        "found_title": "",
        "now_status": "",
        "now_title": "",
        "now_stage": "",
        "now_year": "",
        "now_list": [],
        "previously": [],
        "newer_title": "", "newer_kind": "", "newer_year": "", "newer_url": "",
        "doc_type": "Main",
        "judge_status": status,
        "judge_label": label,
        "judge_message": message,
        "now_main": "",
        "missing_types": [], "missing_supplements": [],
        "has_update": has_update,
        "reasons": [message],
    }


async def resolve_source_url(standard_name: str, current_version: str = "") -> dict:
    """回傳單一文件的版本狀態分類（不進行網路查詢）。"""
    label, message = classify(standard_name)
    return _result(label, message)


async def resolve_many(items: list, on_item=None) -> dict:
    """批量分類（不進行網路查詢）。"""
    out = {}
    for it in items or []:
        key = it["key"]
        label, message = classify(it.get("standard_name") or "")
        result = _result(label, message)
        out[key] = result
        if on_item is not None:
            try:
                on_item(key, it, result)
            except Exception as cb_err:  # 回呼錯誤不應中斷整批
                logger.warning("on_item 回呼錯誤（%s）: %s", key, cb_err)
    return out
