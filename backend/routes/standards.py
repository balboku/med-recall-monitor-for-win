"""法規標準查詢 API"""
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
