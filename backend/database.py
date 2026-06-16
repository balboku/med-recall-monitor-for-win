"""SQLite / PostgreSQL 相容資料庫模型定義與初始化（v2: 含 Audit Trail 支援）"""
import os
import re
import sqlite3
from pathlib import Path
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
        # 增加 maxconn 到 20 應付爬蟲高併發
        pg_pool = pool.SimpleConnectionPool(1, 20, DATABASE_URL)
        print("PostgreSQL connection pool enabled")
    except ImportError:
        print("psycopg2 not installed, falling back to SQLite")
        DATABASE_URL = None
    except Exception as e:
        print(f"Failed to create PostgreSQL connection pool: {e}. Falling back to SQLite")
        DATABASE_URL = None


class PgCursorWrapper:
    def __init__(self, cursor):
        self._cursor = cursor
        self._lastrowid = None

    def _convert_query(self, query):
        import re
        # 處理 PostgreSQL 的 %s 參數替換與 % 轉義
        # 1. 將 SQLite 的 ? 替換為 %s
        query = query.replace("?", "%s")
        # 2. 轉義 SQL 中的 % 為 %% (因為 psycopg2 會解析 %)
        # 我們只在 query 中有 %s 時才需要轉義，但為了保險統一處理
        # 注意：我們不能直接 replace("%", "%%")，因為那會把剛剛產生的 %s 變成 %%s
        # 理想做法是先轉義原有 %，再換 ? -> %s
        return query

    def execute(self, query, params=None):
        import re
        # 重新實作更穩健的轉換邏輯
        # A. 先將原有的 % 轉義為 %%
        query = query.replace("%", "%%")
        # B. 將 ? 轉換為 %s
        query = query.replace("?", "%s")
        
        # C. SQLite LIKE 預設不分大小寫，PostgreSQL 需轉為 ILIKE
        query = re.sub(r"(?i)\bLIKE\b", "ILIKE", query)
        
        # D. SQLite strftime('%Y-%m', col) -> PostgreSQL TO_CHAR(CAST(NULLIF(col, '') AS DATE), 'YYYY-MM')
        def _repl_strftime(match):
            fmt = match.group(1).replace("%%", "%") # 還原格式符中的 %
            col = match.group(2)
            pg_fmt = fmt.replace('%Y', 'YYYY').replace('%m', 'MM').replace('%d', 'DD')
            return f"TO_CHAR(CAST(NULLIF({col}, '') AS DATE), '{pg_fmt}')"
        query = re.sub(r"strftime\('([^']+)',\s*([^)]+)\)", _repl_strftime, query)
        
        # E. SQLite datetime('now', '-7 days') -> Postgres NOW() - INTERVAL '7 days'
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
            ai_analysis TEXT,
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
            ai_analysis TEXT,
            mdr_report_key TEXT,
            event_description_zh TEXT,
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
            report_html TEXT NOT NULL DEFAULT '',
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

    _run_ddl(cursor, """
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
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
    print("Database initialization completed")


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
        ("ALTER TABLE reports ADD COLUMN report_html TEXT NOT NULL DEFAULT ''",),
        ("ALTER TABLE reports ADD COLUMN generated_by TEXT",),
        ("ALTER TABLE reports ADD COLUMN approved_by TEXT",),
        ("ALTER TABLE reports ADD COLUMN approved_at TIMESTAMP",),
        ("ALTER TABLE reports ADD COLUMN superseded_by INTEGER",),
        ("ALTER TABLE reports ADD COLUMN data_truncated INTEGER NOT NULL DEFAULT 0",),
        ("ALTER TABLE reports ADD COLUMN total_records_analyzed INTEGER NOT NULL DEFAULT 0",),
        ("ALTER TABLE recalls ADD COLUMN capa_ref TEXT",),
        ("ALTER TABLE recalls ADD COLUMN capa_status TEXT",),
        ("ALTER TABLE recalls ADD COLUMN ai_analysis TEXT",),
        ("ALTER TABLE adverse_events ADD COLUMN ai_analysis TEXT",),
        ("ALTER TABLE adverse_events ADD COLUMN mdr_report_key TEXT",),
        ("ALTER TABLE adverse_events ADD COLUMN event_description_zh TEXT",),
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

    _run_ddl(cursor, """
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

    # ---- 標準「法規名稱」格式正規化 ----
    # ISO/IEC 標準的「法規名稱」應只包含編號（例如「ISO 10993-4」），版本資訊
    # （年份）應存於「目前使用版本」(current_version)。過去資料常將兩者
    # 合併存放於「法規名稱」(例如「ISO 10993-4:2017」或「ISO10993-1:2018」)，
    # 此處一次性將這類記錄拆解：法規名稱正規化為僅含編號，若「目前使用版本」
    # 原本為空白則補上拆解出的版本（已有值則保留不變）。
    standards_normalized = 0
    try:
        title_version_pattern = re.compile(
            r"^\s*((?:ISO|IEC)(?:/(?:IEC|TR|TS))?\s*\d+(?:[-/]\d+)*)\s*[:：]\s*(\d{4}.*)$",
            re.IGNORECASE,
        )
        rows = cursor.execute("SELECT id, title, current_version FROM standards").fetchall()
        for row in rows:
            title = (row["title"] or "").strip()
            match = title_version_pattern.match(title)
            if not match:
                continue

            base = re.sub(r"\s+", " ", match.group(1).strip())
            base = re.sub(r"^(ISO|IEC)(?=\d)", r"\1 ", base, flags=re.IGNORECASE)
            version = match.group(2).strip()

            current_version = (row["current_version"] or "").strip()
            new_current_version = current_version or version

            if base != title or new_current_version != current_version:
                cursor.execute(
                    "UPDATE standards SET title = ?, current_version = ? WHERE id = ?",
                    (base, new_current_version, row["id"]),
                )
                standards_normalized += 1
        conn.commit()
    except Exception:
        if DATABASE_URL:
            conn.rollback()

    # ---- 依「參考資料/外來文件清單.xlsx」ISO 類別法規清單，精確覆寫法規名稱與目前使用版本 ----
    # 對應表以「公司文件編號」(standard_number) 為鍵，直接覆寫 title / current_version。
    iso_standard_mapping = {
        "R101-0001-01": ("ISO 13485", "2016"),
        "R101-0002-01": ("ISO 14971", "2019"),
        "R101-0003-01": ("ISO 2859-1", "1999"),
        "R101-0004-01": ("ISO 10993-1", "2018"),
        "R101-0005-02": ("ISO 10993-7", "2026"),
        "R101-0006-01": ("ISO 10993-10", "2021"),
        "R101-0007-01": ("ISO 10993-17", "2023"),
        "R101-0008-01": ("ISO 11607-1", "2019+Amd 1:2023"),
        "R101-0009-01": ("ISO 15223-1", "2021"),
        "R101-0009-02": ("ISO 15223-1", "2021+Amd 1:2025"),
        "R101-0010-01": ("ISO 9227", "2017"),
        "R101-0011-01": ("ISO 11737-2", "2019"),
        "R101-0012-01": ("ISO 11135", "2014+Amd 1:2018"),
        "R101-0013-01": ("ISO 3601-3", "2005"),
        "R101-0014-01": ("ISO 11737-1", "2018+Amd 1:2021"),
        "R101-0015-01": ("ISO 14155", "2020"),
        "R101-0016-01": ("ISO 10993-9", "2009"),
        "R101-0017-01": ("ISO 10993-13", "2010"),
        "R101-0018-01": ("ISO 10993-14", "2001"),
        "R101-0019-01": ("ISO 10993-15", "2019"),
        "R101-0020-01": ("ISO 10993-5", "2009"),
        "R101-0021-01": ("ISO/TR 24971", "2020"),
        "R101-0022-01": ("ISO 14644-1", "2015"),
        "R101-0023-01": ("ISO 10993-4", "2017"),
        "R101-0024-01": ("ISO 10993-11", "2017"),
        "R101-0025-01": ("ISO 10993-18", "2020"),
        "R101-0026-01": ("ISO/TS 10993-19", "2020"),
        "R101-0027-01": ("ISO/TR 80002-2", "2017"),
        "R101-0028-01": ("ISO 17665", "2024"),
        "R101-0029-01": ("ISO 11607-2", "2019+Amd 1:2023"),
        "R101-0030-01": ("ISO 20417", "2021"),
        "R101-0031-01": ("ISO 10993-12", "2021"),
        "R101-0032-01": ("ISO 10993-23", "2021"),
        "R101-0033-01": ("ISO 17664-1", "2021"),
        "R101-0034-01": ("ISO 11138-2", "2017"),
        "R101-0035-01": ("ISO 19011", "2018"),
        "R101-0036-01": ("ISO 14698-1", "2003"),
        "R101-0037-01": ("ISO 14698-2", "2003"),
        "R101-0038-01": ("ISO 14644-2", "2015"),
        "R101-0039-01": ("ISO 14644-3", "2019"),
        "R101-0040-01": ("ISO/TR 20416", "2020"),
        "R101-0041-01": ("ISO 3166-1", "2020"),
        "R101-0042-01": ("ISO 8601-1", "2019+Amd 1:2022"),
        "R101-0043-01": ("ISO 15225", "2016"),
        "R101-0044-01": ("ISO 11737-3", "2023"),
        "R101-0045-01": ("ISO 17664-2", "2021"),
    }
    iso_mapping_applied = 0
    try:
        for standard_number, (title_val, version_val) in iso_standard_mapping.items():
            row = cursor.execute(
                "SELECT id, title, current_version FROM standards WHERE standard_number = ?",
                (standard_number,),
            ).fetchone()
            if not row:
                continue
            if row["title"] != title_val or (row["current_version"] or "") != version_val:
                cursor.execute(
                    "UPDATE standards SET title = ?, current_version = ? WHERE id = ?",
                    (title_val, version_val, row["id"]),
                )
                iso_mapping_applied += 1
        conn.commit()
    except Exception:
        if DATABASE_URL:
            conn.rollback()

    # ---- 清理被污染的「分類」(notes)：移除「來源網址查核失敗」訊息 ----
    # 舊版曾將查核失敗訊息附加到 notes（同時作為分類），產生
    # 「ISO ⚠️ 來源網址查核失敗…」「IEC ⚠️ …」這類假類別。
    # 此處還原為原分類（ISO/IEC）；若還原後為空，再依法規名稱前綴推斷。
    notes_cleaned = 0
    try:
        rows = cursor.execute(
            "SELECT id, title, notes FROM standards WHERE notes LIKE '%查核失敗%'"
        ).fetchall()
        for row in rows:
            notes = row["notes"] or ""
            cleaned = re.sub(r"\s*⚠.*source_url\s*$", "", notes).strip()
            if not cleaned:
                t = (row["title"] or "").strip().upper()
                cleaned = "ISO" if t.startswith("ISO") else ("IEC" if t.startswith("IEC") else "")
            if cleaned != notes:
                cursor.execute("UPDATE standards SET notes = ? WHERE id = ?", (cleaned, row["id"]))
                notes_cleaned += 1
        conn.commit()
    except Exception:
        if DATABASE_URL:
            conn.rollback()

    conn.commit()
    conn.close()
    print(f"Database migration completed, applied {migrated} column updates, "
          f"normalized {standards_normalized} standards titles, "
          f"applied {iso_mapping_applied} ISO standard mapping updates, "
          f"cleaned {notes_cleaned} polluted standard categories")


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
