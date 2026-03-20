"""FDA openFDA Device Adverse Event (MAUDE) API 爬蟲"""
import json
import logging
from datetime import datetime
from crawlers.base import BaseCrawler
from database import get_db
from config import FDA_EVENT_ENDPOINT, FDA_API_KEY

logger = logging.getLogger(__name__)


class FDAMaudeCrawler(BaseCrawler):
    """FDA MAUDE 不良事件報告爬蟲"""

    def __init__(self):
        super().__init__("fda_maude")
        self._min_interval = 1.5

    def _build_search_query(self, product: dict) -> str:
        """根據產品設定建立搜尋查詢"""
        parts = []

        codes = [c.strip() for c in product.get("fda_product_codes", "").split(",") if c.strip()]
        if codes:
            code_queries = [f'device.product_code:"{code}"' for code in codes]
            parts.append(f'({" OR ".join(code_queries)})')

        keywords = [k.strip() for k in product.get("keywords", "").split(",") if k.strip()]
        if keywords:
            kw_queries = []
            for kw in keywords:
                kw_queries.append(
                    f'(device.brand_name:"{kw}" OR device.generic_name:"{kw}" OR '
                    f'device.openfda.device_name:"{kw}" OR mdr_text.text:"{kw}")'
                )
            parts.append(f'({" OR ".join(kw_queries)})')

        return " AND ".join(parts) if parts else ""

    def _fetch_events(self, search_query: str, limit: int = 100, skip: int = 0) -> dict:
        """從 FDA API 取得不良事件資料"""
        params = {
            "search": search_query,
            "limit": min(limit, 100),
            "skip": skip,
        }
        if FDA_API_KEY:
            params["api_key"] = FDA_API_KEY

        response = self.get(FDA_EVENT_ENDPOINT, params=params)
        return response.json()

    def _parse_event(self, item: dict, product_id: int) -> dict:
        """解析單筆不良事件"""
        devices: list = item.get("device", [{}])
        device = devices[0] if isinstance(devices, list) and devices else {} # type: ignore
        patients: list = item.get("patient", [{}])
        patient = patients[0] if isinstance(patients, list) and patients else {} # type: ignore
        mdr_text: list = item.get("mdr_text", [{}])

        # 組合事件描述
        descriptions = []
        for text_entry in mdr_text:
            t = text_entry.get("text", "")
            if t:
                descriptions.append(t)
        event_description = " | ".join(descriptions[:3]) # type: ignore

        # 判斷事件類型
        event_types = []
        if item.get("adverse_event_flag") == "Y":
            event_types.append("Adverse Event")
        if item.get("product_problem_flag") == "Y":
            event_types.append("Product Problem")

        # 病患結果
        outcomes = []
        sequences = patient.get("sequence_number_outcome", [])
        if isinstance(sequences, list):
            outcomes = sequences
        elif isinstance(sequences, str):
            outcomes = [sequences]

        return {
            "product_id": product_id,
            "source": "FDA_MAUDE",
            "report_number": item.get("report_number", ""),
            "event_type": ", ".join(event_types) if event_types else "Unknown",
            "date_received": item.get("date_received", ""),
            "brand_name": device.get("brand_name", ""),
            "manufacturer": device.get("manufacturer_d_name", ""),
            "device_problem": ", ".join(device.get("device_report_product_code", "") if isinstance(device.get("device_report_product_code"), list) else []),
            "event_description": event_description[:2000],
            "patient_outcome": ", ".join(outcomes),
            "raw_data": json.dumps(item, ensure_ascii=False),
        }

    def _save_event(self, event_data: dict) -> bool:
        """儲存不良事件，回傳是否為新記錄"""
        conn = get_db()
        try:
            existing = conn.execute(
                "SELECT id FROM adverse_events WHERE report_number = ?",
                (event_data["report_number"],)
            ).fetchone()

            if existing:
                return False

            conn.execute("""
                INSERT INTO adverse_events (product_id, source, report_number,
                    event_type, date_received, brand_name, manufacturer,
                    device_problem, event_description, patient_outcome, raw_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event_data["product_id"], event_data["source"],
                event_data["report_number"], event_data["event_type"],
                event_data["date_received"], event_data["brand_name"],
                event_data["manufacturer"], event_data["device_problem"],
                event_data["event_description"], event_data["patient_outcome"],
                event_data["raw_data"],
            ))
            conn.commit()
            return True
        finally:
            conn.close()

    def run_history(self, product: dict, start_date: str, end_date: str):
        """爬取指定產品與日期範圍的大量歷史不良事件紀錄"""
        search_query = self._build_search_query(product)
        if not search_query:
            return []
            
        history_query = f"({search_query}) AND date_received:[{start_date} TO {end_date}]"
        all_raw_data = []
        
        try:
            skip = 0
            while True:
                data = self._fetch_events(history_query, limit=100, skip=skip)
                results = data.get("results", [])
                total = data.get("meta", {}).get("results", {}).get("total", 0)

                for item in results:
                    all_raw_data.append(item)
                    event_data = self._parse_event(item, product["id"])
                    self._save_event(event_data)

                skip += len(results) # type: ignore
                if skip >= total or not results:
                    break
        except Exception as e:
            logger.error(f"[{self.name}] 歷史爬取失敗: {e}")
            
        return all_raw_data

    def run(self, historical: bool = False):
        """執行 MAUDE 不良事件爬蟲"""
        started_at = datetime.now().isoformat()
        products = self.get_active_products()
        total_found = 0
        total_new = 0

        logger.info(f"[{self.name}] 開始爬取 ({'歷史同步' if historical else '常規'}), 共 {len(products)} 個監控產品")

        for product in products:
            search_query = self._build_search_query(product)
            if not search_query:
                continue

            try:
                skip = 0
                # 如果是歷史同步則放寬到 10,000 筆，常規則 500 筆
                max_results = 10000 if historical else 500 
                while skip < max_results:
                    data = self._fetch_events(search_query, limit=100, skip=skip)
                    results: list = data.get("results", [])
                    total: int = data.get("meta", {}).get("results", {}).get("total", 0)

                    for item in results:
                        event_data = self._parse_event(item, product["id"])
                        total_found += 1
                        if self._save_event(event_data):
                            total_new += 1
                            self.create_alert(
                                alert_type="adverse_event",
                                title=f"新不良事件: {event_data['brand_name']}",
                                message=f"[{event_data['event_type']}] {event_data['event_description'][:150]}",
                                source="FDA_MAUDE",
                                reference_table="adverse_events",
                            )

                    skip += len(results) # type: ignore # type: ignore
                    if skip >= total or not results:
                        break

                logger.info(f"[{self.name}] 產品 '{product['name']}': 找到 {total} 筆")

            except Exception as e:
                logger.error(f"[{self.name}] 產品 '{product['name']}' 爬取失敗: {e}")
                continue

        self.log_crawl("success", total_found, total_new, started_at=started_at)
        logger.info(f"[{self.name}] 完成: 共找到 {total_found} 筆，新增 {total_new} 筆")
        return {"found": total_found, "new": total_new}
