import sqlite3
import json
import os
from datetime import datetime

# Paths are relative to backend/ (since we run this from backend folder)
DB_PATH = os.path.join("data", "monitor.db")
CONFIG_DIR = os.path.join("..", "config")
CONFIG_FILE = os.path.join(CONFIG_DIR, "products.json")

def main():
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM products ORDER BY id ASC").fetchall()
        products = []
        for row in rows:
            p = dict(row)
            # Ensure boolean for is_active instead of 1/0
            if "is_active" in p:
                p["is_active"] = bool(p["is_active"])
            products.append(p)
        
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(products, f, ensure_ascii=False, indent=2)
            
        print(f"Successfully migrated {len(products)} products to {CONFIG_FILE}")
    except Exception as e:
        print(f"Migration failed: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
