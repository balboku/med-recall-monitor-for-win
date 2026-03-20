"""爬蟲基底類別 — 提供共用的 HTTP 請求、錯誤處理、速率限制、日誌記錄"""
import time
import logging
import requests
from datetime import datetime
from typing import Optional, List, Dict, Any
from database import get_db
from config import REQUEST_TIMEOUT, REQUEST_HEADERS

logger = logging.getLogger(__name__)


class BaseCrawler:
    """所有爬蟲的基底類別"""

    def __init__(self, name: str):
        self.name = name
        self.session = requests.Session()
        self.session.headers.update(REQUEST_HEADERS)
        self.timeout = REQUEST_TIMEOUT
        self._last_request_time: float = 0.0
        self._min_interval = 1.0  # 最小請求間隔（秒）

    def _rate_limit(self):
        """速率限制：確保請求間隔不小於最小間隔"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

    def get(self, url: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
        """發送 GET 請求，含速率限制與錯誤處理"""
        self._rate_limit()
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            logger.info(f"[{self.name}] GET {url} -> {response.status_code}")
            return response
        except requests.exceptions.RequestException as e:
            logger.error(f"[{self.name}] GET {url} 失敗: {e}")
            raise

    def log_crawl(self, status: str, records_found: int = 0,
                  new_records: int = 0, error_message: Optional[str] = None,
                  started_at: Optional[str] = None):
        """記錄爬蟲執行日誌"""
        conn = get_db()
        try:
            conn.execute("""
                INSERT INTO crawl_logs (crawler_name, status, records_found,
                                        new_records, error_message, started_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (self.name, status, records_found, new_records,
                  error_message, started_at or datetime.now().isoformat()))
            conn.commit()
        finally:
            conn.close()

    def create_alert(self, alert_type: str, title: str, message: str,
                     source: str, reference_id: Optional[int] = None,
                     reference_table: Optional[str] = None):
        """建立新提醒通知"""
        conn = get_db()
        try:
            conn.execute("""
                INSERT INTO alerts (alert_type, title, message, source,
                                    reference_id, reference_table)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (alert_type, title, message, source, reference_id, reference_table))
            conn.commit()
        finally:
            conn.close()

    def get_active_products(self) -> List[Dict[str, Any]]:
        """取得所有啟用中的監控產品"""
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT * FROM products WHERE is_active = 1"
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def run(self, **kwargs):
        """執行爬蟲（子類別必須實作）"""
        raise NotImplementedError("子類別必須實作 run() 方法")
