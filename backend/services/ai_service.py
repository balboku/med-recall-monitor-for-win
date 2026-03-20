import os
import time
import json
import logging
from typing import Tuple, Optional
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

logger = logging.getLogger(__name__)

# 初始化 3 組 API Keys
KEYS = [
    os.getenv("GEMINI_API_KEY_1"),
    os.getenv("GEMINI_API_KEY_2"),
    os.getenv("GEMINI_API_KEY_3"),
]
KEYS = [k for k in KEYS if k]

if not KEYS:
    logger.warning("未設定 Gemini API Keys，AI 服務可能無法運作。")

# Model 設定 - 預設使用高速高額度模型
MODEL_NAME = "gemini-2.5-flash"


class AIService:
    def __init__(self):
        self.current_idx = 0
        self.client = genai.Client(api_key=KEYS[self.current_idx]) if KEYS else None

    def _rotate_key(self) -> bool:
        if not KEYS:
            return False
        self.current_idx = (self.current_idx + 1) % len(KEYS)
        self.client = genai.Client(api_key=KEYS[self.current_idx])
        logger.info(f"🔄 [AI Service] 已切換至第 {self.current_idx + 1} 組 API Key")
        return True

    def _generate_with_retry(self, prompt: str, schema: Optional[dict] = None) -> str:
        if not self.client:
            raise ValueError("未定義 API Key")

        max_retries = len(KEYS) * 2
        retries = 0

        config_kwargs = {}
        if schema:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = schema
            
        config = types.GenerateContentConfig(**config_kwargs)

        while retries < max_retries:
            try:
                response = self.client.models.generate_content(
                    model=MODEL_NAME,
                    contents=prompt,
                    config=config
                )
                return response.text
            except Exception as e:
                err_str = str(e).lower()
                # 判斷是否為配額限制或 429
                if "429" in err_str or "quota" in err_str or "exhausted" in err_str:
                    logger.warning(f"⚠️ 觸發 API 限制或 429 Error，準備進行輪調: {e}")
                    self._rotate_key()
                    time.sleep(2)
                    retries += 1
                else:
                    # 其他預期外錯誤
                    raise e
                    
        raise RuntimeError("所有 API Key 皆已觸發速率限制或失效。")

    def generate_product_report(self, product_name: str, start_date: str, end_date: str, data: str) -> Tuple[str, str]:
        """
        產出總結報告，包含 HTML 與統計數據
        :return: (report_html_string, stats_json_string)
        """
        # 如果資料過大，進行簡單的截斷避免超過 Context Limits (Gemini 2.5 Flash 支援 1M+ tokens，通常不會超過，但以防萬一)
        if len(data) > 1000000:
            data = data[:1000000] + "\n...[資料截斷]"
            
        prompt = f"""
你是一位專業的醫療器材品保與法規專家。請分析以下「{product_name}」在 {start_date} 到 {end_date} 期間的歷史召回與不良事件紀錄。
這些紀錄包含 FDA 召回與 MAUDE 不良事件資料。

原始資料 (JSON)：
{data}

請提供：
1. 一份專業的專家總結報告（必須為 HTML 格式，不要給出 Markdown 程式碼區塊標記，只要純 HTML 字串。裡面可以使用 h3, p, ul, table 等標籤。內容應包含：問題重點總結、問題分類分析、風險評估、對品保工程師的建議）。
2. 一份統計數據的 JSON 物件，包含屬性：total_recalls (整數)、total_events (整數)、top_issues (字串陣列，列出最常見的3個問題摘要)、critical_warnings (整數，死亡或嚴重傷害事件數)。

請確保輸出為 JSON 物件，並遵循 response_schema。全程使用繁體中文。
"""
        schema = {
            "type": "OBJECT",
            "properties": {
                "report_html": {"type": "STRING", "description": "符合要求的 HTML 格式重點報告"},
                "stats_json": {
                    "type": "OBJECT",
                    "properties": {
                        "total_recalls": {"type": "INTEGER"},
                        "total_events": {"type": "INTEGER"},
                        "top_issues": {
                            "type": "ARRAY",
                            "items": {"type": "STRING"}
                        },
                        "critical_warnings": {"type": "INTEGER"}
                    },
                    "required": ["total_recalls", "total_events", "top_issues", "critical_warnings"]
                }
            },
            "required": ["report_html", "stats_json"]
        }

        try:
            response_text = self._generate_with_retry(prompt, schema=schema)
            # 有時模型會包在 markdown 裡，這裡處理掉
            if response_text.startswith("```json"):
                response_text = response_text[7:]
                if response_text.endswith("```"):
                    response_text = response_text[:-3]
            
            result = json.loads(response_text.strip())
            report_html = result.get("report_html", "<p>沒有產出報告內容</p>")
            stats_json = json.dumps(result.get("stats_json", {}))
            return report_html, stats_json
        except Exception as e:
            logger.error(f"Failed to generate report: {e}")
            return f"<p style='color:red;'>產出報告失敗：{e}</p>", "{}"

    def analyze_single_record(self, record_type: str, raw_data: str) -> str:
        """
        針對單筆紀錄進行深度專家級解析
        :return: HTML 格式字串
        """
        type_str = "FDA 產品召回記錄" if record_type == "recall" else "FDA MAUDE 不良事件報告"
        
        prompt = f"""
你是一位專業的醫療器材法規與品保專家。這裡有一筆 {type_str} 的單一紀錄。
請對它進行深度解析。
以安全的 HTML 片段格式輸出（不需要 html/body 標籤，直接從 <div> 或 <p> 開始即可，可使用強調查如 <strong>、<ul>等，不可包含惡意腳本）。
內容應包含：
1. 事件重點摘要（30 字內）
2. 潛在的根本原因 (Root Cause 推論)
3. 給品保人員與設計單位的改善建議
4. 初步風險評估（高/中/低）與說明

請以繁體中文回答，不需要前後回傳 markdown 區塊控制碼。

原始資料 (JSON):
{raw_data}
"""
        try:
            res = self._generate_with_retry(prompt)
            # 把 markdown 區塊濾掉
            if res.startswith("```html"):
                res = res[7:]
            if res.endswith("```"):
                res = res[:-3]
            return res.strip()
        except Exception as e:
            logger.error(f"Failed to analyze record: {e}")
            return f"<p style='color:red;'>分析失敗：{e}</p>"

# 單一實例導出
ai_service = AIService()
