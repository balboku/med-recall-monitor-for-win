"""SQLite 資料庫模型定義與初始化（v2: 含 Audit Trail 支援）"""
import sqlite3
from pathlib import Path
from config import DATABASE_PATH


def get_db():
    """取得資料庫連線"""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # 增加 timeout 以處理並行寫入時的繁忙狀態
    conn = sqlite3.connect(str(DATABASE_PATH), timeout=30.0)
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
            severity TEXT NOT NULL DEFAULT 'info',
            is_read INTEGER NOT NULL DEFAULT 0,
            read_at TIMESTAMP,
            read_by TEXT,
            capa_ref TEXT,
            sop_ref TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # AI 報告（P1-3: 加入簽核狀態管理欄位）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            start_date TEXT,
            end_date TEXT,
            report_html TEXT NOT NULL,
            stats_json TEXT,
            model_used TEXT,
            report_status TEXT NOT NULL DEFAULT 'draft',
            generated_by TEXT,
            approved_by TEXT,
            approved_at TIMESTAMP,
            superseded_by INTEGER,
            data_truncated INTEGER NOT NULL DEFAULT 0,
            total_records_analyzed INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
            FOREIGN KEY (superseded_by) REFERENCES reports(id) ON DELETE SET NULL
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

    # 稽核追蹤日誌表（P1-2: Audit Trail）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operator TEXT NOT NULL DEFAULT 'system',
            action TEXT NOT NULL,
            target_table TEXT NOT NULL,
            target_id INTEGER,
            old_value TEXT,
            new_value TEXT,
            ip_address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # recalls 表補充 CAPA 欄位
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recalls_v2_check (id INTEGER PRIMARY KEY)
    """)

    # 建立索引（僅建立在全新安裝時就存在的欄位）
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_recalls_source ON recalls(source)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_recalls_date ON recalls(recall_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_source ON adverse_events(source)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_date ON adverse_events(date_received)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_read ON alerts(is_read)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_type ON alerts(alert_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reports_product ON reports(product_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_table ON audit_log(target_table)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_operator ON audit_log(operator)")

    conn.commit()
    conn.close()
    print("✅ 資料庫初始化完成（v2: Audit Trail 啟用）")


def migrate_db():
    """對既有資料庫進行欄位遷移（新增欄位不刪除舊資料）"""
    conn = get_db()
    cursor = conn.cursor()

    migrations = [
        # alerts 表新增欄位
        ("ALTER TABLE alerts ADD COLUMN severity TEXT NOT NULL DEFAULT 'info'",),
        ("ALTER TABLE alerts ADD COLUMN read_at TIMESTAMP",),
        ("ALTER TABLE alerts ADD COLUMN read_by TEXT",),
        ("ALTER TABLE alerts ADD COLUMN capa_ref TEXT",),
        ("ALTER TABLE alerts ADD COLUMN sop_ref TEXT",),
        # reports 表新增欄位
        ("ALTER TABLE reports ADD COLUMN report_status TEXT NOT NULL DEFAULT 'draft'",),
        ("ALTER TABLE reports ADD COLUMN generated_by TEXT",),
        ("ALTER TABLE reports ADD COLUMN approved_by TEXT",),
        ("ALTER TABLE reports ADD COLUMN approved_at TIMESTAMP",),
        ("ALTER TABLE reports ADD COLUMN superseded_by INTEGER",),
        ("ALTER TABLE reports ADD COLUMN data_truncated INTEGER NOT NULL DEFAULT 0",),
        ("ALTER TABLE reports ADD COLUMN total_records_analyzed INTEGER NOT NULL DEFAULT 0",),
        # recalls 表新增欄位
        ("ALTER TABLE recalls ADD COLUMN capa_ref TEXT",),
        ("ALTER TABLE recalls ADD COLUMN capa_status TEXT",),
    ]

    migrated = 0
    for (sql,) in migrations:
        try:
            cursor.execute(sql)
            migrated += 1
        except Exception:
            # 欄位已存在時 SQLite 會丟出例外，忽略即可
            pass

    # 建立 audit_log 表（若不存在）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operator TEXT NOT NULL DEFAULT 'system',
            action TEXT NOT NULL,
            target_table TEXT NOT NULL,
            target_id INTEGER,
            old_value TEXT,
            new_value TEXT,
            ip_address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_table ON audit_log(target_table)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_operator ON audit_log(operator)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_recalls_classification ON recalls(classification)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(report_status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity)")

    conn.commit()
    conn.close()
    print(f"✅ 資料庫遷移完成，執行 {migrated} 項欄位新增")


def write_audit_log(conn, operator: str, action: str, target_table: str,
                   target_id=None, old_value=None, new_value=None, ip_address=None):
    """寫入稽核日誌（可在任何路由中呼叫）"""
    try:
        conn.execute("""
            INSERT INTO audit_log (operator, action, target_table, target_id,
                                   old_value, new_value, ip_address)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (operator, action, target_table, target_id, old_value, new_value, ip_address))
    except Exception:
        pass  # 稽核日誌寫入失敗不應中斷主要業務流程


if __name__ == "__main__":
    init_db()
    migrate_db()
