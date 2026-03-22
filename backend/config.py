"""系統設定檔"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# 資料庫設定
DATABASE_URL = f"sqlite:///{BASE_DIR / 'data' / 'monitor.db'}"
DATABASE_PATH = BASE_DIR / "data" / "monitor.db"

# FDA openFDA API 設定
FDA_API_BASE = "https://api.fda.gov"
FDA_RECALL_ENDPOINT = f"{FDA_API_BASE}/device/recall.json"
FDA_EVENT_ENDPOINT = f"{FDA_API_BASE}/device/event.json"
FDA_API_KEY = os.getenv("FDA_API_KEY", "")  # 選填，無 key 也可使用

# TFDA 設定
TFDA_SAFETY_URL = "https://www.fda.gov.tw/TC/site.aspx?sid=46"

# 爬蟲排程間隔（小時）— 可透過環境變數覆蓋
CRAWL_INTERVAL_FDA_RECALL = int(os.getenv("CRAWL_INTERVAL_FDA_RECALL", "24"))   # 每日
CRAWL_INTERVAL_FDA_MAUDE = int(os.getenv("CRAWL_INTERVAL_FDA_MAUDE", "24"))     # 每日
CRAWL_INTERVAL_TFDA = int(os.getenv("CRAWL_INTERVAL_TFDA", "24"))               # 每日
CRAWL_INTERVAL_STANDARDS = int(os.getenv("CRAWL_INTERVAL_STANDARDS", "168"))     # 每週

# HTTP 請求設定
REQUEST_TIMEOUT = 30
REQUEST_HEADERS = {
    "User-Agent": "MedRecallMonitor/1.0 (Quality Assurance Research Tool)"
}

# 確保 data 目錄存在
(BASE_DIR / "data").mkdir(parents=True, exist_ok=True)
