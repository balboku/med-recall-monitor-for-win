"""醫療器材召回與法規監控系統 — FastAPI 主程式"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import init_db
from scheduler import init_scheduler, shutdown_scheduler
from crawlers.standards import StandardsCrawler
from crawlers.fda_recall import FDARecallCrawler
from crawlers.fda_maude import FDAMaudeCrawler
from crawlers.tfda import TFDACrawler
from routes import products, recalls, events, standards, dashboard, reports


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
def trigger_crawl(crawler_name: str):
    """手動觸發爬蟲"""
    crawlers = {
        "fda_recall": FDARecallCrawler,
        "fda_maude": FDAMaudeCrawler,
        "tfda": TFDACrawler,
        "standards": StandardsCrawler,
    }

    if crawler_name not in crawlers and crawler_name != "all":
        return {"error": f"未知的爬蟲: {crawler_name}"}

    results = {}
    if crawler_name == "all":
        for name, cls in crawlers.items():
            try:
                crawler = cls()
                results[name] = crawler.run()
            except Exception as e:
                results[name] = {"error": str(e)}
    else:
        try:
            crawler = crawlers[crawler_name]()
            results[crawler_name] = crawler.run()
        except Exception as e:
            results[crawler_name] = {"error": str(e)}

    return {"results": results}


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
