import json
import os
from datetime import datetime
from pathlib import Path
from database import get_db

BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR.parent / "config"
PRODUCTS_FILE = CONFIG_DIR / "products.json"

def _ensure_file():
    if not CONFIG_DIR.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not PRODUCTS_FILE.exists():
        with open(PRODUCTS_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f)

def get_products():
    _ensure_file()
    try:
        with open(PRODUCTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []

def _save_products(products):
    _ensure_file()
    with open(PRODUCTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(products, f, ensure_ascii=False, indent=2)
    sync_to_db()

def sync_to_db():
    """Sync JSON products to SQLite to maintain foreign key integrity and read operations."""
    products = get_products()
    conn = get_db()
    try:
        for p in products:
            existing = conn.execute("SELECT id FROM products WHERE id = ?", (p.get("id"),)).fetchone()
            if existing:
                conn.execute("""
                    UPDATE products SET 
                        name=?, keywords=?, fda_product_codes=?, description=?, is_active=?, updated_at=?
                    WHERE id=?
                """, (
                    p.get("name", ""), p.get("keywords", ""), p.get("fda_product_codes", ""),
                    p.get("description", ""), 1 if p.get("is_active", True) else 0,
                    p.get("updated_at"), p.get("id")
                ))
            else:
                conn.execute("""
                    INSERT INTO products (id, name, keywords, fda_product_codes, description, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    p.get("id"), p.get("name", ""), p.get("keywords", ""), p.get("fda_product_codes", ""),
                    p.get("description", ""), 1 if p.get("is_active", True) else 0,
                    p.get("created_at"), p.get("updated_at")
                ))
        
        db_ids = [row["id"] for row in conn.execute("SELECT id FROM products").fetchall()]
        json_ids = {p.get("id") for p in products}
        for db_id in set(db_ids) - json_ids:
            conn.execute("DELETE FROM products WHERE id = ?", (db_id,))
            
        conn.commit()
    except Exception as e:
        print(f"Error syncing products to DB: {e}")
    finally:
        conn.close()

def get_product(product_id: int):
    products = get_products()
    for p in products:
        if p.get("id") == product_id:
            return p
    return None

def create_product(product_data: dict) -> int:
    products = get_products()
    new_id = 1
    if products:
        new_id = max(p.get("id", 0) for p in products) + 1
    
    product = {
        "id": new_id,
        "name": product_data.get("name", ""),
        "keywords": product_data.get("keywords", ""),
        "fda_product_codes": product_data.get("fda_product_codes", ""),
        "description": product_data.get("description", ""),
        "is_active": product_data.get("is_active", True),
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    products.append(product)
    _save_products(products)
    return new_id

def update_product(product_id: int, updates: dict) -> bool:
    products = get_products()
    updated = False
    for p in products:
        if p.get("id") == product_id:
            for k, v in updates.items():
                p[k] = v
            p["updated_at"] = datetime.now().isoformat()
            updated = True
            break
    if updated:
        _save_products(products)
    return updated

def delete_product(product_id: int) -> bool:
    products = get_products()
    original_len = len(products)
    products = [p for p in products if p.get("id") != product_id]
    if len(products) < original_len:
        _save_products(products)
        return True
    return False
