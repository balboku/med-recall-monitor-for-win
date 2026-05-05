import sqlite3
import json
import logging
from pathlib import Path
import os
import sys

# Add parent dir to path so we can import from backend
sys.path.append(str(Path(__file__).parent.parent))

from env_loader import load_environment
from config import DATABASE_PATH

load_environment()
DATABASE_URL = os.getenv("DATABASE_URL")
pg_pool = None

if DATABASE_URL:
    try:
        import psycopg2
        import psycopg2.extras
        from psycopg2 import pool
        pg_pool = pool.SimpleConnectionPool(1, 10, DATABASE_URL)
    except Exception as e:
        DATABASE_URL = None

def get_db():
    if pg_pool:
        conn = pg_pool.getconn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        return conn, cur
    else:
        conn = sqlite3.connect(str(DATABASE_PATH))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        return conn, cur

def main():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("backfill_mdr_report_key")
    
    conn, cur = get_db()
    
    try:
        cur.execute("SELECT id, raw_data FROM adverse_events WHERE mdr_report_key IS NULL")
        rows = cur.fetchall()
        
        updated = 0
        for row in rows:
            record_id = row["id"]
            raw_data_str = row["raw_data"]
            try:
                raw_data = json.loads(raw_data_str)
                mdr_report_key = raw_data.get("mdr_report_key")
                if mdr_report_key:
                    if pg_pool:
                        cur.execute("UPDATE adverse_events SET mdr_report_key = %s WHERE id = %s", (mdr_report_key, record_id))
                    else:
                        cur.execute("UPDATE adverse_events SET mdr_report_key = ? WHERE id = ?", (mdr_report_key, record_id))
                    updated += 1
            except Exception as e:
                logger.warning(f"Failed to process record {record_id}: {e}")
                
        conn.commit()
        logger.info(f"Successfully processed {updated} records, updated mdr_report_key.")
        
    finally:
        if pg_pool:
            cur.close()
            pg_pool.putconn(conn)
        else:
            cur.close()
            conn.close()

if __name__ == "__main__":
    main()
