"""產品管理 API"""
from fastapi import APIRouter, HTTPException, Request, Header
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from database import get_db, write_audit_log
import json
import product_manager

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
    products = product_manager.get_products()
    products.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return products


@router.get("/{product_id}")
def get_product(product_id: int):
    """取得單一產品"""
    product = product_manager.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="產品不存在")
    return product


@router.post("")
def create_product(product: ProductCreate, request: Request, x_operator: Optional[str] = Header(None)):
    """新增監控產品（含 Audit Trail）"""
    operator = x_operator or "system"
    ip = request.client.host if request.client else None
    
    new_id = product_manager.create_product({
        "name": product.name,
        "keywords": product.keywords,
        "fda_product_codes": product.fda_product_codes,
        "description": product.description,
        "is_active": product.is_active,
    })
    
    conn = get_db()
    try:
        write_audit_log(conn, operator, "CREATE_PRODUCT", "products",
                        target_id=new_id, new_value=product.name, ip_address=ip)
        conn.commit()
    finally:
        conn.close()
        
    return {"id": new_id, "message": "產品新增成功"}


@router.put("/{product_id}")
def update_product(product_id: int, product: ProductUpdate, request: Request, x_operator: Optional[str] = Header(None)):
    """更新產品設定（含 Audit Trail）"""
    operator = x_operator or "system"
    ip = request.client.host if request.client else None
    
    existing = product_manager.get_product(product_id)
    if not existing:
        raise HTTPException(status_code=404, detail="產品不存在")

    old_data = dict(existing)
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
        updates["is_active"] = product.is_active

    if updates:
        product_manager.update_product(product_id, updates)
        
        # 記錄變更前後的值
        changed_fields = {k: v for k, v in updates.items() if k != 'updated_at'}
        conn = get_db()
        try:
            write_audit_log(conn, operator, "UPDATE_PRODUCT", "products",
                            target_id=product_id,
                            old_value=json.dumps({k: old_data.get(k) for k in changed_fields}, ensure_ascii=False),
                            new_value=json.dumps(changed_fields, ensure_ascii=False),
                            ip_address=ip)
            conn.commit()
        finally:
            conn.close()

    return {"message": "產品更新成功"}


@router.delete("/{product_id}")
def delete_product(product_id: int, request: Request, x_operator: Optional[str] = Header(None)):
    """刪除監控產品（含 Audit Trail）"""
    operator = x_operator or "system"
    ip = request.client.host if request.client else None
    
    existing = product_manager.get_product(product_id)
    if not existing:
        raise HTTPException(status_code=404, detail="產品不存在")
    
    product_name = existing.get("name", "unknown")
    deleted = product_manager.delete_product(product_id)
    
    if deleted:
        conn = get_db()
        try:
            write_audit_log(conn, operator, "DELETE_PRODUCT", "products",
                            target_id=product_id, old_value=product_name, ip_address=ip)
            conn.commit()
        finally:
            conn.close()
            
    return {"message": "產品刪除成功"}
