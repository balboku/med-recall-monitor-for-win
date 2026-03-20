"""台灣 TFDA 安全及品質警訊爬蟲"""
import logging
import re
from datetime import datetime
from bs4 import BeautifulSoup
from crawlers.base import BaseCrawler
from database import get_db
from config import TFDA_SAFETY_URL

logger = logging.getLogger(__name__)


class TFDACrawler(BaseCrawler):
    """台灣食藥署安全警訊爬蟲"""

    def __init__(self):
        super().__init__("tfda")
        self._min_interval = 2.0  # 對政府網站放慢速率

    def _fetch_page(self, page: int = 0) -> str:
        """取得警訊列表頁面 HTML"""
        params = {
            "sid": "46",
            "p": page,
        }
        response = self.get(TFDA_SAFETY_URL, params=params)
        response.encoding = "utf-8"
        return response.text

    def _parse_list(self, html: str) -> list:
        """解析警訊列表頁面"""
        soup = BeautifulSoup(html, "lxml")
        items = []

        # 尋找警訊列表表格
        rows = soup.select("table.listTB tr") or soup.select(".CenterContent table tr")
        if not rows:
            # 嘗試其他選擇器
            rows = soup.select("#ctl00_CenterContent_GVList tr")

        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 2:
                continue

            link = row.find("a")
            if not link:
                continue

            title = link.get_text(strip=True)
            href = link.get("href", "")
            if href and not href.startswith("http"):
                href = f"https://www.fda.gov.tw{href}" if href.startswith("/") else f"https://www.fda.gov.tw/TC/{href}"

            date_text = ""
            for col in cols:
                text = col.get_text(strip=True)
                # 嘗試匹配日期格式（民國或西元）
                if re.match(r'\d{2,4}[-/\.]\d{1,2}[-/\.]\d{1,2}', text):
                    date_text = text
                    break

            items.append({
                "title": title,
                "url": href,
                "date": date_text,
            })

        return items

    def _matches_product(self, title: str, products: list) -> list:
        """檢查標題是否匹配任何監控產品的關鍵字"""
        matched = []
        title_lower = title.lower()
        for product in products:
            keywords = [k.strip().lower() for k in product.get("keywords", "").split(",") if k.strip()]
            for kw in keywords:
                if kw in title_lower:
                    matched.append(product)
                    break
        return matched

    def _save_recall(self, item: dict, product_id: int) -> bool:
        """儲存 TFDA 警訊為召回記錄"""
        conn = get_db()
        try:
            # 用 URL 作為唯一識別
            recall_number = f"TFDA-{hash(item['url']) & 0xFFFFFFFF:08x}"

            existing = conn.execute(
                "SELECT id FROM recalls WHERE recall_number = ? OR url = ?",
                (recall_number, item["url"])
            ).fetchone()

            if existing:
                return False

            conn.execute("""
                INSERT INTO recalls (product_id, source, recall_number,
                    firm_name, product_description, reason,
                    classification, status, recall_date, url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                product_id, "TFDA", recall_number,
                "", item["title"], item["title"],
                "", "Published", item.get("date", ""),
                item["url"],
            ))
            conn.commit()
            return True
        finally:
            conn.close()

    def run(self, **kwargs):
        """執行 TFDA 爬蟲"""
        started_at = datetime.now().isoformat()
        products = self.get_active_products()
        total_found = 0
        total_new = 0

        if not products:
            logger.info(f"[{self.name}] 無監控產品，跳過")
            self.log_crawl("success", 0, 0, started_at=started_at)
            return {"found": 0, "new": 0}

        logger.info(f"[{self.name}] 開始爬取 TFDA 安全警訊")

        try:
            # 爬取前 5 頁
            for page in range(5):
                html = self._fetch_page(page)
                items = self._parse_list(html)

                if not items:
                    break

                for item in items:
                    matched_products = self._matches_product(item["title"], products)
                    if matched_products:
                        total_found += 1
                        for product in matched_products:
                            if self._save_recall(item, product["id"]):
                                total_new += 1
                                self.create_alert(
                                    alert_type="recall",
                                    title=f"TFDA 安全警訊: {item['title'][:80]}",
                                    message=item["title"],
                                    source="TFDA",
                                    reference_table="recalls",
                                )

                logger.info(f"[{self.name}] 第 {page + 1} 頁: 找到 {len(items)} 筆警訊")

        except Exception as e:
            logger.error(f"[{self.name}] 爬取失敗: {e}")
            self.log_crawl("error", total_found, total_new, str(e), started_at)
            return {"found": total_found, "new": total_new}

        self.log_crawl("success", total_found, total_new, started_at=started_at)
        logger.info(f"[{self.name}] 完成: 匹配 {total_found} 筆，新增 {total_new} 筆")
        return {"found": total_found, "new": total_new}
