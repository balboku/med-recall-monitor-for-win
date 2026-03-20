"""產品管理 API"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from database import get_db

router = APIRouter(prefix="/api/products", tags=["products"])


class ProductCreate(BaseModel):
    name: str
    keywords: str = ""
    fda_product_codes: str = ""
    description: str = ""
    is_active: bool = True


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    keywords: Optional[str] = None
    fda_product_codes: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("")
def list_products():
    """取得所有監控產品"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM products ORDER BY created_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@router.get("/{product_id}")
def get_product(product_id: int):
    """取得單一產品"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="產品不存在")
        return dict(row)
    finally:
        conn.close()


@router.post("")
def create_product(product: ProductCreate):
    """新增監控產品"""
    conn = get_db()
    try:
        cursor = conn.execute("""
            INSERT INTO products (name, keywords, fda_product_codes,
                                  description, is_active)
            VALUES (?, ?, ?, ?, ?)
        """, (product.name, product.keywords, product.fda_product_codes,
              product.description, 1 if product.is_active else 0))
        conn.commit()
        return {"id": cursor.lastrowid, "message": "產品新增成功"}
    finally:
        conn.close()


@router.put("/{product_id}")
def update_product(product_id: int, product: ProductUpdate):
    """更新產品設定"""
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="產品不存在")

        updates = {}
        if product.name is not None:
            updates["name"] = product.name
        if product.keywords is not None:
            updates["keywords"] = product.keywords
        if product.fda_product_codes is not None:
            updates["fda_product_codes"] = product.fda_product_codes
        if product.description is not None:
            updates["description"] = product.description
        if product.is_active is not None:
            updates["is_active"] = 1 if product.is_active else 0

        if updates:
            updates["updated_at"] = datetime.now().isoformat()
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [product_id]
            conn.execute(
                f"UPDATE products SET {set_clause} WHERE id = ?", values
            )
            conn.commit()

        return {"message": "產品更新成功"}
    finally:
        conn.close()


@router.delete("/{product_id}")
def delete_product(product_id: int):
    """刪除監控產品"""
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="產品不存在")

        conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
        conn.commit()
        return {"message": "產品刪除成功"}
    finally:
        conn.close()
