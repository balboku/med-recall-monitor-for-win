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
    notes: str = ""


class ResolveUrlRequest(BaseModel):
    standard_name: str               # 法規名稱／編號（例如 'ISO 10993-1'）
    current_version: str = ""        # 目前使用版本（用於判定有無更新）
    standard_id: Optional[int] = None  # 若為既有標準，查找成功後回寫「最新查找版本/日期」


@router.post("/resolve-url")
async def resolve_source_url(req: ResolveUrlRequest):
    """以虛擬瀏覽器到 ISO 官網搜尋此單一法規，找到官方標準頁網址並解析 Life cycle。

    成功回傳 source_url 供前端填入「官方來源網址」，並附帶版本判讀（現行版／是否有新版）。
    """
    name = (req.standard_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="請先填寫法規名稱")

    from crawlers import iso_browser
    if not iso_browser.BROWSER_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="伺服器未安裝虛擬瀏覽器(nodriver)或本機 Chrome，無法執行 ISO 官網查找。",
        )
    try:
        # 瀏覽器須在獨立工作執行緒以全新事件迴圈執行，避免與 FastAPI 事件迴圈巢狀
        result = await asyncio.to_thread(
            iso_browser.resolve_source_url_sync, name, (req.current_version or "").strip()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ISO 官網查找失敗：{e}")

    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "找不到相符的 ISO 標準頁"))

    # 既有標準：回寫「最新查找版本」(latest_version) 與「最新查找日期」(last_checked)，
    # 並依判讀結果更新 has_update，供清單與編輯頁顯示。
    now_iso = datetime.now().isoformat()
    if req.standard_id:
        conn = get_db()
        try:
            conn.execute(
                """UPDATE standards
                   SET latest_version = ?, last_checked = ?, has_update = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    result.get("now_year") or result.get("now_title") or "",
                    now_iso,
                    1 if result.get("has_update") else 0,
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
                                   source_url, notes)
            VALUES (?, ?, ?, ?, ?)
        """, (standard.standard_number, standard.title,
              standard.current_version, standard.source_url, standard.notes))
        conn.commit()
        return {"id": cursor.lastrowid, "message": "標準新增成功"}
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
                current_version = ?, source_url = ?, notes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (standard.standard_number, standard.title,
              standard.current_version, standard.source_url,
              standard.notes, standard_id))
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
