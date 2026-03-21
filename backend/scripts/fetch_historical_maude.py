import os
import sys
import asyncio
from datetime import datetime

# 加入 backend 作為 module import base
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from crawlers.fda_maude import FDAMaudeCrawler

async def fetch_all():
    crawler = FDAMaudeCrawler()
    products = crawler.get_active_products()
    found_lfl = False
    
    for p in products:
        if p.get("fda_product_codes") == "LFL":
            found_lfl = True
            print(f"開始為產品 {p['name']} (LFL) 回補歷史資料...")
            start_year = 2000
            end_year = datetime.now().year
            
            for year in range(start_year, end_year + 1):
                s_date = f"{year}0101"
                e_date = f"{year}1231"
                print(f"開始抓取區間: {s_date} 到 {e_date} ... ", end="", flush=True)
                
                # 這裡調用歷史抓取函式 (內部會有 skip 分頁，單年不可能超過 2.5 萬筆)
                count = await crawler.run_history(p, s_date, e_date)
                print(f"共取得並儲存了 {count} 筆紀錄。")
                
            print("所有年份回補完成！")
            
    if not found_lfl:
        print("查無 Product Code 為 LFL 的監控產品，請於前端先設定。")

if __name__ == "__main__":
    asyncio.run(fetch_all())
