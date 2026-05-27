import sys
import os
from pathlib import Path
import asyncio

backend_dir = r'c:\Users\day75\OneDrive\文件\MEGAsync\Leon\久方\暫存區\處理案件\久方軟體\med-recall-monitor-for-win-main\backend'
sys.path.insert(0, backend_dir)

from database import get_db
from scripts.import_standards_excel import get_source_url
from crawlers.standards import StandardsCrawler

async def fix_and_crawl():
    conn = get_db()
    try:
        standards = conn.execute('SELECT id, title, source_url, standard_number FROM standards').fetchall()
        updated_ids = []
        for s in standards:
            correct_url = get_source_url(s['title'])
            if s['source_url'] != correct_url: # Update any wrongly assigned URL
                print(f"Assigning URL to {s['title']}: {correct_url}")
                conn.execute(
                    'UPDATE standards SET source_url = ?, latest_version = NULL, has_update = 0 WHERE id = ?',
                    (correct_url, s['id'])
                )
                if correct_url:
                    updated_ids.append(s['id'])
        conn.commit()
    finally:
        conn.close()

    if updated_ids:
        print("Now running crawler to fetch correct versions...")
        crawler = StandardsCrawler()
        # Mock product_ids or bypass since StandardsCrawler doesn't actually use product_ids currently
        await crawler.run()
        print("Crawling complete!")
    else:
        print("No URLs needed fixing.")

if __name__ == '__main__':
    asyncio.run(fix_and_crawl())
