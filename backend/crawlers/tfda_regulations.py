"""
台灣 TFDA 法規更新追蹤爬蟲

涵蓋：
- 全國法規資料庫 (law.moj.gov.tw) -> 查詢各法規的最後修正日期
- TFDA 公告 (R602) -> 衛福部食藥署網站

由於政府網站的 SSL 憑證問題，使用 verify=False 繞過驗證。
"""
import re
import json
import logging
import urllib.parse
from datetime import datetime
from crawlers.base import BaseCrawler
from crawlers.html_parser import parse_html
from database import get_db

logger = logging.getLogger(__name__)

# 全國法規資料庫 API：查詢法規基本資訊（含最後修正日期）
# 參考：https://law.moj.gov.tw/api/swagger/index.html
MOJ_LAW_API = "https://law.moj.gov.tw/api/data/GetLaw.ashx?id={pcode}&type=json"

# 台灣法規法規代碼對應（pcode -> standard_number 前綴關鍵字）
TFDA_LAW_PCODES = {
    "醫療器材管理法": "L0030106",
    "醫療器材管理法施行細則": "L0030117",
    "醫療器材分類分級管理辦法": "L0030110",
    "醫療器材技術人員管理辦法": "L0030112",
    "醫療器材來源流向資料建立及管理辦法": "L0030119",
    "醫療器材製造業者設置標準": "L0030115",
    "醫療器材品質管理系統準則": "L0030129",
    "醫療器材品質管理系統檢查及製造許可核發法": "L0030130",
    "醫療器材委託製造作業準則": "L0030131",
    "醫療器材優良運銷準則": "L0030120",
    "醫療器材優良運銷檢查及運銷許可核發辦法": "L0030121",
    "醫療器材許可證核發與登錄及年度申報準則": "L0030122",
    "特定醫療器材專案核准製造及輸入辦法": "L0030123",
    "醫療器材優良臨床試驗管理辦法": "L0030124",
    "醫療器材安全監視管理辦法": "L0030140",
    "醫療器材嚴重不良事件通報辦法": "L0030141",
    "醫療器材回收處理辦法": "L0030142",
    "醫療器材創新科技研究發展獎勵辦法": "L0030143",
    "個人資料保護法": "I0050021",
    "個人資料保護法施行細則": "I0050022",
    "醫療器材標簽應刊載單一識別碼規定": "L0030144",
    "醫療器材上市後監督規範": "L0030145",
}


class TfdaRegulationsCrawler(BaseCrawler):
    """台灣 TFDA 法規更新追蹤爬蟲"""

    def __init__(self):
        super().__init__("tfda_regulations")
        self._min_interval = 2.0
        self._ssl_verify = False  # 繞過 gov.tw SSL 憑證問題

    async def _query_moj_law(self, pcode: str) -> dict:
        """
        查詢全國法規資料庫 API 取得法規的最後修正日期。
        """
        url = MOJ_LAW_API.format(pcode=pcode)
        try:
            # 使用 GET 請求，忽略 SSL 驗證
            import httpx
            async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
                response = await client.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; standards-monitor/1.0)"
                })
                if response.status_code == 200:
                    try:
                        data = response.json()
                        # 回應格式依 M.O.J. API 版本而異，嘗試解析
                        if isinstance(data, dict):
                            # 常見格式
                            last_modified = (
                                data.get("最後修正日期") or
                                data.get("LawModifiedDate") or
                                data.get("AmendDate") or ""
                            )
                            return {"last_modified": str(last_modified)}
                    except Exception:
                        # API 可能回傳 HTML，嘗試解析 HTML
                        soup = parse_html(response.text)
                        date_el = soup.find(string=re.compile(r"修正日期|修訂日期|發布日期"))
                        if date_el:
                            m = re.search(r"(\d{3,4}[年/]\d{1,2}[月/]\d{1,2}[日]?|\d{4}-\d{2}-\d{2})",
                                          date_el.parent.get_text())
                            if m:
                                return {"last_modified": m.group(1)}
        except Exception as e:
            logger.warning(f"[{self.name}] 查詢 MOJ API 失敗 (pcode={pcode}): {e}")
        return {}

    async def _query_law_html(self, pcode: str) -> dict:
        """
        備援方案：直接抓取全國法規資料庫法規頁面的 HTML，解析修正日期。
        """
        url = f"https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={pcode}"
        try:
            import httpx
            async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
                response = await client.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                })
                if response.status_code == 200:
                    soup = parse_html(response.text)
                    # 頁面中找修正日期文字
                    for tag in soup.find_all(string=re.compile(r"修正日期|異動日期|發布日期")):
                        parent = tag.parent
                        if parent:
                            date_m = re.search(r"\d{3,4}[年./-]\d{1,2}[月./-]\d{1,2}",
                                               parent.get_text())
                            if date_m:
                                return {"last_modified": date_m.group(0)}
        except Exception as e:
            logger.warning(f"[{self.name}] 法規 HTML 抓取失敗 (pcode={pcode}): {e}")
        return {}

    async def run(self, historical: bool = False, product_ids: list = None, **kwargs):
        """執行台灣 TFDA 法規更新檢查"""
        started_at = datetime.now().isoformat()
        log_id = self.start_crawl_log(started_at)
        total_checked = 0
        total_updated = 0

        try:
            conn = get_db()
            tfda_stds = conn.execute(
                "SELECT id, standard_number, title, current_version FROM standards "
                "WHERE standard_number LIKE 'R601%' OR standard_number LIKE 'R602%'"
            ).fetchall()
            conn.close()

            logger.info(f"[{self.name}] 開始檢查 {len(tfda_stds)} 筆台灣法規")

            for std_row in tfda_stds:
                title = std_row["title"] or ""
                current_ver = std_row["current_version"] or ""

                # 根據法規名稱找對應的 pcode
                pcode = None
                for law_name, code in TFDA_LAW_PCODES.items():
                    if law_name in title:
                        pcode = code
                        break

                total_checked += 1

                if not pcode:
                    logger.debug(f"[{self.name}] 無對應 pcode: {title[:30]}")
                    # 仍更新 last_checked
                    conn2 = get_db()
                    conn2.execute(
                        "UPDATE standards SET last_checked = ? WHERE id = ?",
                        (datetime.now().isoformat(), std_row["id"])
                    )
                    conn2.commit()
                    conn2.close()
                    continue

                # 先嘗試 API，失敗則用 HTML
                info = await self._query_moj_law(pcode)
                if not info.get("last_modified"):
                    info = await self._query_law_html(pcode)

                new_date = info.get("last_modified", "")
                has_update = 1 if new_date and new_date != current_ver else 0

                conn2 = get_db()
                try:
                    conn2.execute("""
                        UPDATE standards SET
                            latest_version = ?,
                            has_update = ?,
                            last_checked = ?,
                            updated_at = ?
                        WHERE id = ?
                    """, (new_date or current_ver, has_update,
                          datetime.now().isoformat(), datetime.now().isoformat(),
                          std_row["id"]))
                    conn2.commit()
                    if has_update:
                        total_updated += 1
                        self.create_alert(
                            alert_type="standard_update",
                            title=f"台灣法規修正: {std_row['standard_number']}",
                            message=f"《{title}》最新修正日期: {new_date}",
                            source="Taiwan TFDA / 全國法規資料庫",
                            reference_id=std_row["id"],
                            reference_table="standards",
                        )
                finally:
                    conn2.close()

            self.finish_crawl_log(log_id, "success", total_checked, total_updated)
            logger.info(f"[{self.name}] 完成: 檢查 {total_checked} 個，更新 {total_updated} 個")
            return {"checked": total_checked, "updated": total_updated}

        except Exception as e:
            self.finish_crawl_log(log_id, "error", total_checked, total_updated, str(e))
            logger.error(f"[{self.name}] 執行失敗: {e}")
            raise
