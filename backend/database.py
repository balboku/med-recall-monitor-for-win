"""SQLite / PostgreSQL 相容資料庫模型定義與初始化（v2: 含 Audit Trail 支援）"""
import os
import sqlite3
from pathlib import Path
from config import DATABASE_PATH

DATABASE_URL = os.getenv("DATABASE_URL")
pg_pool = None

if DATABASE_URL:
    try:
        import psycopg2
        import psycopg2.extras
        from psycopg2 import pool
        # 增加 maxconn 到 20 應付爬蟲高併發
        pg_pool = pool.SimpleConnectionPool(1, 20, DATABASE_URL)
        print("✅ 已啟用 PostgreSQL 連線池")
    except ImportError:
        print("⚠️ 未安裝 psycopg2，將回退至 SQLite")
        DATABASE_URL = None
    except Exception as e:
        print(f"⚠️ 建立 PostgreSQL 連線池失敗: {e}，將回退至 SQLite")
        DATABASE_URL = None


class PgCursorWrapper:
    def __init__(self, cursor):
        self._cursor = cursor
        self._lastrowid = None

    def _convert_query(self, query):
        import re
        # 簡易的 ? 轉 %s 的替換
        query = query.replace("?", "%s")
        # SQLite LIKE 預設不分大小寫，PostgreSQL 需轉為 ILIKE
        query = re.sub(r"(?i)\bLIKE\b", "ILIKE", query)
        
        # SQLite strftime('%Y-%m', col) -> PostgreSQL TO_CHAR(col, 'YYYY-MM')
        def _repl_strftime(match):
            fmt = match.group(1)
            col = match.group(2)
            pg_fmt = fmt.replace('%Y', 'YYYY').replace('%m', 'MM').replace('%d', 'DD')
            return f"TO_CHAR({col}, '{pg_fmt}')"
        query = re.sub(r"strftime\('([^']+)',\s*([^)]+)\)", _repl_strftime, query)
        
        return query

    def execute(self, query, params=None):
        query = self._convert_query(query)
        # PostgreSQL doesn't like datetime() without type cast if used like sqlite, but mostly we use standard SQL.
        # SQLite's datetime('now', '-7 days') -> not natively compatible with Postgres
        # We need a small hack to replace sqlite's datetime('now', '-X days') with Postgres' NOW() - INTERVAL 'X days'
        import re
        query = re.sub(r"datetime\('now',\s*'-(\d+)\s+days'\)", r"NOW() - INTERVAL '\1 days'", query)
        
        if params is not None:
            self._cursor.execute(query, params)
        else:
            self._cursor.execute(query)
            
        q_upper = query.upper().strip()
        if q_upper.startswith("INSERT "):
            try:
                self._cursor.execute("SELECT LASTVAL()")
                row = self._cursor.fetchone()
                if row:
                    self._lastrowid = row[0]
            except Exception:
                pass
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def fetchmany(self, size=None):
        if size is None:
            return self._cursor.fetchmany()
        return self._cursor.fetchmany(size)

    def close(self):
        self._cursor.close()

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return self._lastrowid


class PgConnectionWrapper:
    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        return PgCursorWrapper(self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor))

    def execute(self, query, params=None):
        cur = self.cursor()
        return cur.execute(query, params)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        if pg_pool:
            pg_pool.putconn(self._conn)
        else:
            self._conn.close()


def get_db():
    """取得資料庫連線"""
    if pg_pool:
        conn = pg_pool.getconn()
        return PgConnectionWrapper(conn)
    else:
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DATABASE_PATH), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn


def _run_ddl(cursor, sql):
    if pg_pool:
        # SQLite 轉 PostgreSQL 語法相容
        sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        sql = sql.replace("DATETIME DEFAULT CURRENT_TIMESTAMP", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    cursor.execute(sql)


def init_db():
    """初始化資料庫表格"""
    conn = get_db()
    cursor = conn.cursor()

    _run_ddl(cursor, """
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

    _run_ddl(cursor, """
        CREATE TABLE IF NOT EXISTS recalls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            source TEXT NOT NULL,
            recall_number TEXT,
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

    _run_ddl(cursor, """
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

    _run_ddl(cursor, """
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

    _run_ddl(cursor, """
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

    _run_ddl(cursor, """
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

    _run_ddl(cursor, """
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

    _run_ddl(cursor, """
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

    _run_ddl(cursor, """
        CREATE TABLE IF NOT EXISTS recalls_v2_check (id INTEGER PRIMARY KEY AUTOINCREMENT)
    """)

    # 建立索引
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_recalls_source ON recalls(source)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_recalls_date ON recalls(recall_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_source ON adverse_events(source)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_date ON adverse_events(date_received)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_read ON alerts(is_read)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_type ON alerts(alert_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reports_product ON reports(product_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_table ON audit_log(target_table)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_operator ON audit_log(operator)")
    except Exception:
        pass

    conn.commit()
    conn.close()
    print("✅ 資料庫初始化完成（已相容 PostgreSQL）")


def migrate_db():
    conn = get_db()
    cursor = conn.cursor()

    migrations = [
        ("ALTER TABLE alerts ADD COLUMN severity TEXT NOT NULL DEFAULT 'info'",),
        ("ALTER TABLE alerts ADD COLUMN read_at TIMESTAMP",),
        ("ALTER TABLE alerts ADD COLUMN read_by TEXT",),
        ("ALTER TABLE alerts ADD COLUMN capa_ref TEXT",),
        ("ALTER TABLE alerts ADD COLUMN sop_ref TEXT",),
        ("ALTER TABLE reports ADD COLUMN report_status TEXT NOT NULL DEFAULT 'draft'",),
        ("ALTER TABLE reports ADD COLUMN generated_by TEXT",),
        ("ALTER TABLE reports ADD COLUMN approved_by TEXT",),
        ("ALTER TABLE reports ADD COLUMN approved_at TIMESTAMP",),
        ("ALTER TABLE reports ADD COLUMN superseded_by INTEGER",),
        ("ALTER TABLE reports ADD COLUMN data_truncated INTEGER NOT NULL DEFAULT 0",),
        ("ALTER TABLE reports ADD COLUMN total_records_analyzed INTEGER NOT NULL DEFAULT 0",),
        ("ALTER TABLE recalls ADD COLUMN capa_ref TEXT",),
        ("ALTER TABLE recalls ADD COLUMN capa_status TEXT",),
    ]

    migrated = 0
    for (sql,) in migrations:
        try:
            cursor.execute(sql)
            conn.commit()
            migrated += 1
        except Exception:
            if DATABASE_URL:
                conn.rollback()
            pass
            
    _run_ddl(cursor, """
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
    
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_table ON audit_log(target_table)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_operator ON audit_log(operator)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_recalls_classification ON recalls(classification)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(report_status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity)")
    except Exception:
        pass

    conn.commit()
    conn.close()
    print(f"✅ 資料庫遷移完成，執行 {migrated} 項欄位新增（已相容 PostgreSQL）")


def write_audit_log(conn, operator: str, action: str, target_table: str,
                   target_id=None, old_value=None, new_value=None, ip_address=None):
    try:
        conn.execute("""
            INSERT INTO audit_log (operator, action, target_table, target_id,
                                   old_value, new_value, ip_address)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (operator, action, target_table, target_id, old_value, new_value, ip_address))
    except Exception:
        pass


if __name__ == "__main__":
    init_db()
    migrate_db()
