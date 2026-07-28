"""法規標準查詢 API"""
import asyncio
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from database import get_db

router = APIRouter(prefix="/api/standards", tags=["standards"])


class StandardCreate(BaseModel):
    standard_number: str
    title: str
    current_version: str = ""
    source_url: str = ""
    category: str = ""
    notes: str = ""


class ResolveUrlRequest(BaseModel):
    standard_name: str               # 法規名稱／編號（例如 'ISO 10993-1'）
    current_version: str = ""        # 目前使用版本（用於判定有無更新）
    standard_id: Optional[int] = None  # 若為既有標準，查找成功後回寫「最新查找版本/日期」


def _resolve_source_kind(standard_name: str, standard_id: Optional[int]) -> str:
    """判斷此筆法規應到哪個來源查找：'ISO'、'IEC' 或 'EN'。

    優先採用資料庫既有的「類別」欄位，其次以法規名稱前綴推斷（新增中的標準尚未存檔）。
    EN 須優先判斷：'EN ISO 13485' 同時含 EN 與 ISO，但應走歐盟協調標準清單而非 ISO 官網。
    """
    name = standard_name.strip().upper()
    if standard_id:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT category, notes FROM standards WHERE id = ?", (standard_id,)
            ).fetchone()
        finally:
            conn.close()
        if row:
            for field in (row["category"], row["notes"]):
                value = (field or "").strip().upper()
                if value.startswith("TAIWAN TFDA"):
                    return "TW"
                if value.startswith("FDA"):
                    return "FDA"
                if "ASTM" in value or "AAMI" in value:
                    return "ASTM"
                if value == "INTERNATIONAL / OTHER":
                    return "OTHER"
                if value == "MDCG GUIDANCE":
                    return "MDCG"
                if value == "EU REGULATION":
                    return "EU"
                if value in ("EN ISO / EN", "BS EN", "EN"):
                    return "EN"
                if value in ("ISO", "IEC"):
                    return value
    if name.startswith(("ASTM", "AAMI", "ANSI/AAMI")):
        return "ASTM"
    if name.startswith(("EN ", "BS EN ")):
        return "EN"
    return "IEC" if name.startswith("IEC") else "ISO"


@router.post("/resolve-url")
async def resolve_source_url(req: ResolveUrlRequest):
    """到官網搜尋此單一法規，找到官方標準頁網址並解析生命週期。

    ISO 官網受 Cloudflare 防護，需以虛擬瀏覽器存取；
    IEC webstore 提供可直接呼叫的搜尋 API，純 HTTP 即可，速度快很多。
    成功回傳 source_url 供前端填入「官方來源網址」，並附帶版本判讀（現行版／是否有新版）。
    """
    name = (req.standard_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="請先填寫法規名稱")

    kind = _resolve_source_kind(name, req.standard_id)
    version = (req.current_version or "").strip()

    if kind == "OTHER":
        from crawlers import other_docs
        result = await other_docs.resolve_source_url(name, version)
    elif kind == "ASTM":
        from crawlers import astm_aami
        try:
            result = await astm_aami.resolve_source_url(name, version)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"ASTM／AAMI 查詢失敗：{e}")
    elif kind == "FDA":
        from crawlers import fda_docs
        try:
            result = await fda_docs.resolve_source_url(name, version)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"FDA 指引／CFR 查詢失敗：{e}")
    elif kind == "TW":
        from crawlers import tw_regulation
        try:
            result = await tw_regulation.resolve_source_url(name, version)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"全國法規資料庫查詢失敗：{e}")
    elif kind == "MDCG":
        from crawlers import mdcg_guidance
        try:
            result = await mdcg_guidance.resolve_source_url(name, version)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"MDCG 指引清單查詢失敗：{e}")
    elif kind == "EU":
        from crawlers import eu_regulation
        try:
            result = await eu_regulation.resolve_source_url(name, version)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"EU 法規查詢失敗：{e}")
    elif kind == "EN":
        from crawlers import en_harmonised
        try:
            result = await en_harmonised.resolve_source_url(name, version)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"歐盟協調標準清單查詢失敗：{e}")
    elif kind == "IEC":
        from crawlers import iec_api
        try:
            result = await iec_api.resolve_source_url(name, version)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"IEC 官網查找失敗：{e}")
    else:
        from crawlers import iso_browser
        if not iso_browser.BROWSER_AVAILABLE:
            raise HTTPException(
                status_code=503,
                detail="伺服器未安裝虛擬瀏覽器(nodriver)或本機 Chrome，無法執行 ISO 官網查找。",
            )
        try:
            # 瀏覽器須在獨立工作執行緒以全新事件迴圈執行，避免與 FastAPI 事件迴圈巢狀
            result = await asyncio.to_thread(
                iso_browser.resolve_source_url_sync, name, version
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"ISO 官網查找失敗：{e}")

    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", f"找不到相符的 {kind} 標準頁"))

    # 既有標準：回寫「最新查找版本」(latest_version) 與「最新查找日期」(last_checked)，
    # 並依判讀結果更新 has_update，供清單與編輯頁顯示。
    now_iso = datetime.now().isoformat()
    if req.standard_id:
        conn = get_db()
        try:
            conn.execute(
                """UPDATE standards
                   SET latest_version = ?, last_checked = ?, has_update = ?, judge_label = ?,
                       judge_categories = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    result.get("now_year") or result.get("now_title") or "",
                    now_iso,
                    1 if result.get("has_update") else 0,
                    result.get("judge_label") or "",
                    ",".join(result.get("judge_categories") or []),
                    now_iso,
                    req.standard_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    result["last_checked"] = now_iso
    return result


@router.get("/scan-progress")
def get_scan_progress():
    """法規標準掃描即時進度（供系統設定頁顯示執行進度）。"""
    import standards_progress
    return standards_progress.get()


@router.get("")
def list_standards():
    """取得所有追蹤的法規標準"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM standards ORDER BY standard_number"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@router.post("")
def create_standard(standard: StandardCreate):
    """新增追蹤的標準"""
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM standards WHERE standard_number = ?",
            (standard.standard_number,)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="此標準已在追蹤清單中")

        cursor = conn.execute("""
            INSERT INTO standards (standard_number, title, current_version,
                                   source_url, category, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (standard.standard_number, standard.title,
              standard.current_version, standard.source_url,
              standard.category, standard.notes))
        conn.commit()
        return {"id": cursor.lastrowid, "message": "標準新增成功"}
    finally:
        conn.close()


@router.post("/import")
def import_standards(standards: list[StandardCreate]):
    """批量匯入標準（若 standard_number 存在則更新，否則新增）"""
    conn = get_db()
    inserted = 0
    updated = 0
    try:
        for standard in standards:
            existing = conn.execute(
                "SELECT id FROM standards WHERE standard_number = ?",
                (standard.standard_number,)
            ).fetchone()
            
            if existing:
                conn.execute("""
                    UPDATE standards SET title = ?, current_version = ?,
                        source_url = ?, category = ?, notes = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (standard.title, standard.current_version,
                      standard.source_url, standard.category,
                      standard.notes, existing["id"]))
                updated += 1
            else:
                conn.execute("""
                    INSERT INTO standards (standard_number, title, current_version,
                                           source_url, category, notes)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (standard.standard_number, standard.title,
                      standard.current_version, standard.source_url,
                      standard.category, standard.notes))
                inserted += 1
        conn.commit()
        return {"message": f"匯入成功：新增 {inserted} 筆，更新 {updated} 筆", 
                "inserted": inserted, "updated": updated}
    finally:
        conn.close()


@router.put("/{standard_id}")
def update_standard(standard_id: int, standard: StandardCreate):
    """更新標準資訊"""
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM standards WHERE id = ?", (standard_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="標準不存在")

        conn.execute("""
            UPDATE standards SET standard_number = ?, title = ?,
                current_version = ?, source_url = ?, category = ?, notes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (standard.standard_number, standard.title,
              standard.current_version, standard.source_url,
              standard.category, standard.notes, standard_id))
        conn.commit()
        return {"message": "標準更新成功"}
    finally:
        conn.close()


@router.delete("/{standard_id}")
def delete_standard(standard_id: int):
    """移除追蹤的標準"""
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM standards WHERE id = ?", (standard_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="標準不存在")

        conn.execute("DELETE FROM standards WHERE id = ?", (standard_id,))
        conn.commit()
        return {"message": "標準移除成功"}
    finally:
        conn.close()

