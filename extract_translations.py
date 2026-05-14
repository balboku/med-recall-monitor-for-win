import sqlite3
import json
import os
from pathlib import Path

def extract_translated_data():
    db_path = Path("backend/data/monitor.db")
    out_dir = Path("data")
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / "translated_events.json"
    
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return
        
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    query = """
        SELECT report_number, event_type, brand_name, manufacturer, event_description, event_description_zh 
        FROM adverse_events 
        WHERE event_description_zh IS NOT NULL 
          AND event_description_zh != ''
    """
    
    cursor.execute(query)
    rows = cursor.fetchall()
    
    data = []
    for r in rows:
        data.append(dict(r))
        
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print(f"Extracted {len(data)} translated records to {out_file}")
    
    conn.close()

if __name__ == "__main__":
    extract_translated_data()
