import logging
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from database import init_db
from scheduler import init_scheduler, shutdown_scheduler
from crawlers.standards import StandardsCrawler
from crawlers.fda_recall import FDARecallCrawler
from crawlers.fda_maude import FDAMaudeCrawler
from crawlers.tfda import TFDACrawler
from routes import products, recalls, events, standards, dashboard, reports
from typing import Dict, Type, Any


# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用程式生命週期管理"""
    # 啟動
    logger.info("🚀 啟動醫療器材監控系統")
    init_db()

    # 初始化預設標準
    std_crawler = StandardsCrawler()
    std_crawler.init_default_standards()

    # 啟動排程器
    init_scheduler()

    yield

    # 關閉
    shutdown_scheduler()
    logger.info("🛑 系統已關閉")


app = FastAPI(
    title="醫療器材召回與法規監控系統",
    description="監控拋棄式無線超音波刀相關召回記錄、不良事件及法規標準",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 掛載路由
app.include_router(products.router)
app.include_router(recalls.router)
app.include_router(events.router)
app.include_router(standards.router)
app.include_router(dashboard.router)
app.include_router(reports.router)


@app.get("/")
def root():
    return {"message": "醫療器材召回與法規監控系統 API", "version": "1.0.0"}


@app.post("/api/crawl/{crawler_name}")
async def trigger_crawl(crawler_name: str, historical: bool = False):
    """手動觸發爬蟲（非同步執行），支援 historical=true 抓取大量數據"""
    crawlers_map: Dict[str, Type[Any]] = {
        "fda_recall": FDARecallCrawler,
        "fda_maude": FDAMaudeCrawler,
        "tfda": TFDACrawler,
        "standards": StandardsCrawler,
    }

    if crawler_name not in crawlers_map and crawler_name != "all":
        raise HTTPException(status_code=404, detail=f"未知的爬蟲: {crawler_name}")

    def run_crawl_task(name: str, cls: Type[Any], is_hist: bool):
        try:
            logger.info(f"開始執行背景爬取任務: {name} (historical={is_hist})")
            crawler = cls()
            crawler.run(historical=is_hist)
            logger.info(f"背景爬取任務完成: {name}")
        except Exception as e:
            logger.error(f"背景爬取任務失敗: {name}, 錯誤: {e}")

    if crawler_name == "all":
        for name, cls in crawlers_map.items():
            thread = threading.Thread(target=run_crawl_task, args=(name, cls, historical), daemon=True)
            thread.start()
        return {"message": "已在背景啟動所有爬蟲任務", "historical": historical}
    else:
        cls = crawlers_map[crawler_name]
        thread = threading.Thread(target=run_crawl_task, args=(crawler_name, cls, historical), daemon=True)
        thread.start()
        return {"message": f"已在背景啟動 {crawler_name} 爬蟲任務", "historical": historical}


@app.get("/api/crawl/logs")
def get_crawl_logs():
    """取得爬蟲執行記錄"""
    from database import get_db
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM crawl_logs ORDER BY completed_at DESC LIMIT 50"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
