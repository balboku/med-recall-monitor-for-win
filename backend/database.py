"""SQLite 資料庫模型定義與初始化"""
import sqlite3
from pathlib import Path
from config import DATABASE_PATH


def get_db():
    """取得資料庫連線"""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DATABASE_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """初始化資料庫表格"""
    conn = get_db()
    cursor = conn.cursor()

    # 使用者監控的產品清單
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            keywords TEXT NOT NULL DEFAULT '',
            fda_product_codes TEXT NOT NULL DEFAULT '',
            description TEXT DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 召回記錄
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recalls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            source TEXT NOT NULL,
            recall_number TEXT UNIQUE,
            event_id TEXT,
            firm_name TEXT,
            product_description TEXT,
            reason TEXT,
            classification TEXT,
            status TEXT,
            recall_date TEXT,
            termination_date TEXT,
            url TEXT,
            raw_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL
        )
    """)

    # 不良事件報告
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS adverse_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            source TEXT NOT NULL,
            report_number TEXT UNIQUE,
            event_type TEXT,
            date_received TEXT,
            brand_name TEXT,
            manufacturer TEXT,
            device_problem TEXT,
            event_description TEXT,
            patient_outcome TEXT,
            raw_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL
        )
    """)

    # 法規標準追蹤
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS standards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            standard_number TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            current_version TEXT,
            latest_version TEXT,
            publication_date TEXT,
            status TEXT DEFAULT 'active',
            source_url TEXT,
            notes TEXT DEFAULT '',
            has_update INTEGER DEFAULT 0,
            last_checked TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 提醒通知
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT,
            source TEXT,
            reference_id INTEGER,
            reference_table TEXT,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # AI 報告
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            start_date TEXT,
            end_date TEXT,
            report_html TEXT NOT NULL,
            stats_json TEXT,
            model_used TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        )
    """)

    # 爬蟲執行記錄
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS crawl_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crawler_name TEXT NOT NULL,
            status TEXT NOT NULL,
            records_found INTEGER DEFAULT 0,
            new_records INTEGER DEFAULT 0,
            error_message TEXT,
            started_at TIMESTAMP,
            completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 建立索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_recalls_source ON recalls(source)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_recalls_date ON recalls(recall_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_source ON adverse_events(source)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_date ON adverse_events(date_received)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_read ON alerts(is_read)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_type ON alerts(alert_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reports_product ON reports(product_id)")

    conn.commit()
    conn.close()
    print("✅ 資料庫初始化完成")


if __name__ == "__main__":
    init_db()
