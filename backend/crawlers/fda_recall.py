"""FDA openFDA Device Recall API 爬蟲"""
import json
import logging
from datetime import datetime
from crawlers.base import BaseCrawler
from database import get_db
from config import FDA_RECALL_ENDPOINT, FDA_API_KEY

logger = logging.getLogger(__name__)


class FDARecallCrawler(BaseCrawler):
    """FDA 醫療器材召回記錄爬蟲"""

    def __init__(self):
        super().__init__("fda_recall")
        self._min_interval = 1.5  # FDA API 速率限制

    def _build_search_query(self, product: dict) -> str:
        """根據產品設定建立搜尋查詢"""
        parts = []

        # 使用 FDA 產品代碼搜尋
        codes = [c.strip() for c in product.get("fda_product_codes", "").split(",") if c.strip()]
        if codes:
            code_queries = [f'product_code:"{code}"' for code in codes]
            parts.append(f'({" OR ".join(code_queries)})')

        # 使用關鍵字搜尋
        keywords = [k.strip() for k in product.get("keywords", "").split(",") if k.strip()]
        if keywords:
            kw_queries = []
            for kw in keywords:
                kw_queries.append(
                    f'(product_description:"{kw}" OR reason_for_recall:"{kw}" OR openfda.device_name:"{kw}")'
                )
            parts.append(f'({" OR ".join(kw_queries)})')

        if not parts:
            return ""
        return " OR ".join(parts)

    def _fetch_recalls(self, search_query: str, limit: int = 100, skip: int = 0) -> dict:
        """從 FDA API 取得召回資料"""
        params = {
            "search": search_query,
            "limit": min(limit, 100),
            "skip": skip,
        }
        if FDA_API_KEY:
            params["api_key"] = FDA_API_KEY

        response = self.get(FDA_RECALL_ENDPOINT, params=params)
        return response.json()

    def _parse_recall(self, item: dict, product_id: int) -> dict:
        """解析單筆召回記錄"""
        openfda = item.get("openfda", {})
        return {
            "product_id": product_id,
            "source": "FDA",
            "recall_number": item.get("res_event_number", ""),
            "event_id": str(item.get("event_id", "")),
            "firm_name": item.get("recalling_firm", ""),
            "product_description": item.get("product_description", ""),
            "reason": item.get("reason_for_recall", ""),
            "classification": item.get("event_date_terminated") and "Terminated" or item.get("classification", ""),
            "status": item.get("status", ""),
            "recall_date": item.get("center_classification_date", ""),
            "termination_date": item.get("event_date_terminated", ""),
            "url": f"https://api.fda.gov/device/recall.json?search=res_event_number:{item.get('res_event_number', '')}",
            "raw_data": json.dumps(item, ensure_ascii=False),
        }

    def _save_recall(self, recall_data: dict) -> bool:
        """儲存召回記錄，回傳是否為新記錄"""
        conn = get_db()
        try:
            existing = conn.execute(
                "SELECT id FROM recalls WHERE recall_number = ?",
                (recall_data["recall_number"],)
            ).fetchone()

            if existing:
                return False

            cursor = conn.execute("""
                INSERT INTO recalls (product_id, source, recall_number, event_id,
                    firm_name, product_description, reason, classification,
                    status, recall_date, termination_date, url, raw_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                recall_data["product_id"], recall_data["source"],
                recall_data["recall_number"], recall_data["event_id"],
                recall_data["firm_name"], recall_data["product_description"],
                recall_data["reason"], recall_data["classification"],
                recall_data["status"], recall_data["recall_date"],
                recall_data["termination_date"], recall_data["url"],
                recall_data["raw_data"],
            ))
            conn.commit()
            return True
        finally:
            conn.close()

    def run_history(self, product: dict, start_date: str, end_date: str):
        """爬取指定產品與日期範圍的歷史紀錄，回傳原始資料清單"""
        search_query = self._build_search_query(product)
        if not search_query:
            return []
            
        # start_date / end_date 需為 YYYYMMDD 格式
        history_query = f"({search_query}) AND recall_initiation_date:[{start_date} TO {end_date}]"
        
        all_raw_data = []
        try:
            skip = 0
            while True:
                data = self._fetch_recalls(history_query, limit=100, skip=skip)
                results: list = data.get("results", [])
                total: int = data.get("meta", {}).get("results", {}).get("total", 0)

                for item in results:
                    all_raw_data.append(item)
                    # 順便儲存到本地資料庫 (如果不存在)
                    recall_data = self._parse_recall(item, product["id"])
                    self._save_recall(recall_data)

                skip += len(results)
                if skip >= total or not results:
                    break
        except Exception as e:
            logger.error(f"[{self.name}] 歷史爬取失敗: {e}")
            
        return all_raw_data

    def run(self):
        """執行 FDA 召回爬蟲 (日常差量更新)"""
        started_at = datetime.now().isoformat()
        products = self.get_active_products()
        total_found = 0
        total_new = 0

        logger.info(f"[{self.name}] 開始爬取，共 {len(products)} 個監控產品")

        for product in products:
            search_query = self._build_search_query(product)
            if not search_query:
                logger.warning(f"[{self.name}] 產品 '{product['name']}' 無搜尋條件，跳過")
                continue

            try:
                skip = 0
                while True:
                    # 日常爬取，不限制日期，僅取最新 (也可以在這裡加上近兩週的限制，但預設取100筆即可)
                    data = self._fetch_recalls(search_query, limit=100, skip=skip)
                    results: list = data.get("results", [])
                    total: int = data.get("meta", {}).get("results", {}).get("total", 0)

                    for item in results:
                        recall_data = self._parse_recall(item, product["id"])
                        total_found += 1
                        if self._save_recall(recall_data):
                            total_new += 1
                            # 建立新召回提醒
                            self.create_alert(
                                alert_type="recall",
                                title=f"新召回記錄: {recall_data['firm_name']}",
                                message=f"{recall_data['reason'][:200]}",
                                source="FDA",
                                reference_id=None,
                                reference_table="recalls",
                            )

                    skip += len(results)
                    # FDA 日常抓取建議不用取到翻頁，除非有新紀錄一直抓不完
                    if skip >= total or not results or skip >= 500:
                        break

                logger.info(
                    f"[{self.name}] 產品 '{product['name']}': "
                    f"找到 {total} 筆，新增 {total_new} 筆"
                )

            except Exception as e:
                logger.error(f"[{self.name}] 產品 '{product['name']}' 爬取失敗: {e}")
                continue

        self.log_crawl("success", total_found, total_new, started_at=started_at)
        logger.info(f"[{self.name}] 完成: 共找到 {total_found} 筆，新增 {total_new} 筆")
        return {"found": total_found, "new": total_new}
