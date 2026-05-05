"""FDA openFDA Device Recall API crawler."""

import json
import logging
from datetime import datetime

from config import FDA_API_KEY, FDA_RECALL_ENDPOINT
from crawlers.base import BaseCrawler
from database import get_db

logger = logging.getLogger(__name__)


class FDARecallCrawler(BaseCrawler):
    """Crawler for FDA medical device recall records."""

    def __init__(self):
        super().__init__("fda_recall")
        self._min_interval = 1.5

    def _build_search_query(self, product: dict) -> str:
        """Build an openFDA query from product codes and keywords."""
        parts = []

        codes = [
            code.strip()
            for code in product.get("fda_product_codes", "").split(",")
            if code.strip()
        ]
        if codes:
            code_queries = [f'product_code:"{code}"' for code in codes]
            parts.append(f'({" OR ".join(code_queries)})')

        keywords = [
            keyword.strip()
            for keyword in product.get("keywords", "").split(",")
            if keyword.strip()
        ]
        if keywords:
            keyword_queries = []
            for keyword in keywords:
                keyword_queries.append(
                    (
                        f'(product_description:"{keyword}" '
                        f'OR reason_for_recall:"{keyword}" '
                        f'OR openfda.device_name:"{keyword}")'
                    )
                )
            parts.append(f'({" OR ".join(keyword_queries)})')

        if not parts:
            return ""
        return " OR ".join(parts)

    async def _fetch_recalls(
        self, search_query: str, limit: int = 100, skip: int = 0
    ) -> dict:
        """Fetch recall records from the FDA API."""
        params = {
            "search": search_query,
            "limit": min(limit, 100),
            "skip": skip,
            # openFDA device recall docs use event_date_initiated; the previous
            # sort field could cause the crawler to retry and then silently fail.
            "sort": "event_date_initiated:desc",
        }
        if FDA_API_KEY:
            params["api_key"] = FDA_API_KEY

        response = await self.get(FDA_RECALL_ENDPOINT, params=params)
        return response.json()

    def _parse_recall(self, item: dict, product_id: int) -> dict:
        """Normalize one recall record."""
        termination_date = item.get("event_date_terminated", "")
        raw_status = item.get("status", "")
        computed_status = "Terminated" if termination_date else raw_status

        raw_date = (
            item.get("center_classification_date")
            or item.get("recall_initiation_date")
            or item.get("event_date_initiated")
            or ""
        )

        formatted_date = raw_date
        if raw_date and len(raw_date) == 8 and "-" not in raw_date:
            formatted_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"

        return {
            "product_id": product_id,
            "source": "FDA",
            "recall_number": item.get("product_res_number", ""),
            "event_id": item.get("res_event_number", ""),
            "firm_name": item.get("recalling_firm", ""),
            "product_description": item.get("product_description", ""),
            "reason": item.get("reason_for_recall", ""),
            "classification": item.get("classification", ""),
            "status": computed_status,
            "recall_date": formatted_date,
            "termination_date": termination_date,
            "url": (
                "https://api.fda.gov/device/recall.json"
                f"?search=res_event_number:{item.get('res_event_number', '')}"
            ),
            "raw_data": json.dumps(item, ensure_ascii=False),
        }

    def _save_recall(self, recall_data: dict) -> bool:
        """Persist a recall record and return whether it is newly inserted."""
        conn = get_db()
        try:
            existing = conn.execute(
                "SELECT id FROM recalls WHERE recall_number = ?",
                (recall_data["recall_number"],),
            ).fetchone()
            if existing:
                return False

            conn.execute(
                """
                INSERT INTO recalls (
                    product_id, source, recall_number, event_id,
                    firm_name, product_description, reason, classification,
                    status, recall_date, termination_date, url, raw_data
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    recall_data["product_id"],
                    recall_data["source"],
                    recall_data["recall_number"],
                    recall_data["event_id"],
                    recall_data["firm_name"],
                    recall_data["product_description"],
                    recall_data["reason"],
                    recall_data["classification"],
                    recall_data["status"],
                    recall_data["recall_date"],
                    recall_data["termination_date"],
                    recall_data["url"],
                    recall_data["raw_data"],
                ),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    async def run_history(self, product: dict, start_date: str, end_date: str) -> int:
        """Fetch historical recall records for a date range."""
        search_query = self._build_search_query(product)
        if not search_query:
            return 0

        history_query = (
            f"({search_query}) AND event_date_initiated:[{start_date} TO {end_date}]"
        )

        total_processed = 0
        try:
            skip = 0
            while True:
                data = await self._fetch_recalls(history_query, limit=100, skip=skip)
                results: list = data.get("results", [])
                total: int = data.get("meta", {}).get("results", {}).get("total", 0)

                for item in results:
                    recall_data = self._parse_recall(item, product["id"])
                    self._save_recall(recall_data)
                    total_processed += 1

                skip += len(results)
                if skip >= total or not results:
                    break
        except Exception as exc:
            logger.error("[%s] historical recall sync failed: %s", self.name, exc)

        return total_processed

    async def run(self, historical: bool = False, product_ids: list = None, **kwargs):
        """Run the scheduled FDA recall crawler."""
        started_at = datetime.now().isoformat()
        log_id = self.start_crawl_log(started_at)
        products = self.get_active_products(product_ids)
        total_found = 0
        total_new = 0
        product_errors: list[str] = []

        logger.info("[%s] starting recall crawl for %s active products", self.name, len(products))

        try:
            for product in products:
                search_query = self._build_search_query(product)
                if not search_query:
                    logger.warning(
                        "[%s] product '%s' has no FDA search criteria",
                        self.name,
                        product["name"],
                    )
                    continue

                try:
                    skip = 0
                    product_total = 0
                    product_new = 0

                    while True:
                        data = await self._fetch_recalls(search_query, limit=100, skip=skip)
                        results: list = data.get("results", [])
                        total: int = data.get("meta", {}).get("results", {}).get("total", 0)

                        for item in results:
                            recall_data = self._parse_recall(item, product["id"])
                            total_found += 1
                            product_total += 1
                            if self._save_recall(recall_data):
                                total_new += 1
                                product_new += 1
                                self.create_alert(
                                    alert_type="recall",
                                    title=f"新召回記錄: {recall_data['firm_name']}",
                                    message=recall_data["reason"][:200],
                                    source="FDA",
                                    reference_id=None,
                                    reference_table="recalls",
                                )

                        skip += len(results)
                        if skip >= total or not results or skip >= 500:
                            break

                    logger.info(
                        "[%s] product '%s': found=%s new=%s",
                        self.name,
                        product["name"],
                        product_total,
                        product_new,
                    )
                except Exception as exc:
                    logger.error(
                        "[%s] product '%s' recall crawl failed: %s",
                        self.name,
                        product["name"],
                        exc,
                    )
                    product_errors.append(f"{product['name']}: {exc}")
                    continue

            status = "success"
            error_summary = None
            if product_errors:
                error_summary = "; ".join(product_errors[:5])
                if len(product_errors) == len(products):
                    status = "error"

            self.finish_crawl_log(log_id, status, total_found, total_new, error_summary)
            logger.info("[%s] finished: found=%s new=%s", self.name, total_found, total_new)
            return {"found": total_found, "new": total_new}
        except Exception as exc:
            self.finish_crawl_log(log_id, "error", total_found, total_new, str(exc))
            raise
