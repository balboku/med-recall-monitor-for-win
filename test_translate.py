import sys
sys.path.append('backend')
from backend.database import get_db, pg_pool
from deep_translator import GoogleTranslator

def test():
    conn = get_db()
    try:
        cur = conn._conn.cursor() if pg_pool else conn.cursor()
        print("Fetching rows...")
        if pg_pool:
            cur.execute("SELECT id, event_description FROM adverse_events WHERE event_description_zh IS NULL AND event_description IS NOT NULL AND event_description != '' LIMIT 1")
            rows = cur.fetchall()
        else:
            rows = conn.execute("SELECT id, event_description FROM adverse_events WHERE event_description_zh IS NULL AND event_description IS NOT NULL AND event_description != '' LIMIT 1").fetchall()
        
        print(f"Found {len(rows)} rows to translate")
        if not rows:
            return

        row = rows[0]
        record_id = dict(row)["id"] if pg_pool else row["id"]
        en_text = dict(row)["event_description"] if pg_pool else row["event_description"]
        
        print(f"Translating ID {record_id}...")
        try:
            translated = GoogleTranslator(source='auto', target='zh-TW').translate(en_text)
            print(f"Success! Translated length: {len(translated)}")
        except Exception as e:
            print(f"Translation failed! Exception: {e}")
            import traceback
            traceback.print_exc()
            
    finally:
        if pg_pool: cur.close()
        conn.close()

if __name__ == '__main__':
    test()
