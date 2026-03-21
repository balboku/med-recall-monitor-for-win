"""爬蟲基底類別 — 提供共用的 HTTP 請求、錯誤處理、速率限制、日誌記錄"""
import time
import asyncio
import logging
import httpx
from datetime import datetime
from typing import Optional, List, Dict, Any
from database import get_db
from config import REQUEST_TIMEOUT, REQUEST_HEADERS

logger = logging.getLogger(__name__)


class BaseCrawler:
    """所有爬蟲的基底類別"""

    def __init__(self, name: str):
        self.name = name
        self.client = httpx.AsyncClient(headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        self.timeout = REQUEST_TIMEOUT
        self._last_request_time: float = 0.0
        self._min_interval = 1.0  # 最小請求間隔（秒）

    async def _rate_limit(self):
        """速率限制：確保請求間隔不小於最小間隔"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

    async def get(self, url: str, params: Optional[Dict[str, Any]] = None) -> httpx.Response:
        """發送 GET 請求，含速率限制與自動重試機制（處理 429/50x 與網路異常）"""
        max_retries = 5
        base_delay = 2.0
        
        for attempt in range(max_retries):
            await self._rate_limit()
            try:
                response = await self.client.get(url, params=params)
                response.raise_for_status()
                logger.info(f"[{self.name}] GET {url} -> {response.status_code}")
                return response
            except httpx.HTTPStatusError as e:
                status_code = getattr(e.response, "status_code", None)
                if status_code in (429, 500, 502, 503, 504):
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"[{self.name}] 請求 {url} 遇到 {status_code}，{delay} 秒後重試 ({attempt+1}/{max_retries})")
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.error(f"[{self.name}] GET {url} 失敗且不重試: {e}")
                    raise
            except httpx.RequestError as e:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"[{self.name}] 請求 {url} 網路異常: {e}，{delay} 秒後重試 ({attempt+1}/{max_retries})")
                await asyncio.sleep(delay)
                continue
                
        # 超過重試次數後仍失敗
        raise httpx.RequestError(f"[{self.name}] GET {url} 達到最大重試次數 ({max_retries})", request=httpx.Request("GET", url))

    async def close(self):
        """關閉 HTTP client 連線"""
        await self.client.aclose()

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
