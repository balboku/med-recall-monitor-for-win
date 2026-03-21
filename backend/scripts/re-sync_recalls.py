
import asyncio
import logging
import os
import sys

# 將 backend 加入路徑
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from database import get_db
from crawlers.fda_recall import FDARecallCrawler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("re-sync-recalls")

async def main():
    logger.info("開始重新同步召回資料 (使用 product_res_number)...")
    
    # 1. 取得所有產品
    conn = get_db()
    products = conn.execute("SELECT * FROM products WHERE is_active = 1").fetchall()
    conn.close()
    
    crawler = FDARecallCrawler()
    
    # 2. 為每個產品執行歷史同步 (1900-2026)
    for p in products:
        product_dict = dict(p)
        logger.info(f"正在同步產品: {product_dict['name']}")
        
        # 先清除該產品的舊召回資料
        conn = get_db()
        conn.execute("DELETE FROM recalls WHERE product_id = ?", (product_dict['id'],))
        conn.commit()
        conn.close()
        
        processed = await crawler.run_history(product_dict, "1900-01-01", "2026-12-31")
        logger.info(f"產品 {product_dict['name']} 同步完成，處理了 {processed} 筆")
        
    # 最終檢查資料庫總數
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM recalls").fetchone()[0]
    conn.close()
    logger.info(f"✅ 召回資料重新同步完成！資料庫總數: {total}")

if __name__ == "__main__":
    asyncio.run(main())
