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

# Model 設定 - 使用具備更高額度 (500 RPD) 的 3.1 系列模型
MODEL_NAME = "gemini-3.1-flash-lite-preview"


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
            raise ValueError("未定義 API Key，請檢查 .env 設定。")

        max_retries = len(KEYS) * 2
        retries = 0
        last_error = ""

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
                return response.text or ""
            except Exception as e:
                last_error = str(e)
                err_str = last_error.lower()
                # 判斷是否為配額限制或 429
                if "429" in err_str or "quota" in err_str or "exhausted" in err_str:
                    reason = "TPM (Tokens)" if "token_count" in err_str else "RPM/RPD (Requests)"
                    # 實作 Exponential Backoff with Jitter ( Phase 3 )
                    import random
                    base_delay = 5.0
                    delay = (base_delay * (2 ** retries)) + random.uniform(0.5, 2.5)
                    logger.warning(f"⚠️ [Retry {retries+1}] 觸發 {reason} 限制或 429 Error。將等待 {delay:.2f} 秒後切換金鑰重試: {e}")
                    time.sleep(delay)
                    self._rotate_key()
                    retries += 1
                else:
                    # 其他預期外錯誤 (如 400 Bad Request, 500 等) 直接拋出
                    logger.error(f"❌ [AI Service] 遭遇不可恢復之錯誤: {e}")
                    raise e
                    
        raise RuntimeError(f"所有 API Key 皆已觸發速率限制或失效。最後錯誤：{last_error}")

    def analyze_batch(self, batch_data: str) -> str:
        """
        Map 階段：對單一分次批次進行初步分析
        """
        prompt = f"""
你是一位品保專家。請分析以下這組醫療器材紀錄（約 500 筆），並提供一個簡短的「風險摘要」。
摘要必須包含：
1. 數量統計（死亡、傷害、故障）。
2. 這批次中最嚴重的 2-3 個問題點或失效模式。
3. **品牌/型號識別**：從 `brand_name` 或 `product_description` 中識別出具體的子型號或不同品牌，並摘要其分佈情況。
4. 任何異常的集中的傾向。

原始資料 (JSON):
{batch_data}

請以繁體中文回答，僅輸出摘要內容，不要包含 Markdown 標籤。
"""
        try:
            return self._generate_with_retry(prompt).strip()
        except Exception as e:
            logger.error(f"Batch analysis failed: {e}")
            return f"此批次分析失敗：{e}"

    def generate_product_report(self, product_name: str, start_date: str, end_date: str, 
                                batch_summaries: list, total_stats: dict) -> Tuple[str, str]:
        """
        Reduce 階段：將所有分批摘要彙總為最終報告
        """
        summaries_text = "\n\n".join([f"--- 分批摘要 {i+1} ---\n{s}" for i, s in enumerate(batch_summaries)])
        
        # 專業報表樣式與圖表組件
        report_style = """
<style>
    .qa-report { font-family: 'Segoe UI', Arial, sans-serif; color: #333; line-height: 1.6; max-width: 1000px; margin: auto; padding: 30px; background: #fff; border: 1px solid #eee; }
    .qa-header { border-bottom: 3px solid #2c3e50; padding-bottom: 15px; margin-bottom: 25px; }
    .qa-title { color: #2c3e50; font-size: 28px; margin: 0; }
    .section-title { color: #2980b9; border-left: 6px solid #2980b9; padding-left: 12px; margin: 35px 0 15px; font-size: 22px; font-weight: bold; }
    
    /* 統計卡片 */
    .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 20px; margin-bottom: 30px; }
    .stat-box { background: #fdfdfd; padding: 20px; border-radius: 8px; text-align: center; border: 1px solid #e1e8ed; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .stat-val { font-size: 24px; font-weight: bold; color: #e67e22; margin-bottom: 5px; }
    .stat-label { font-size: 13px; color: #7f8c8d; font-weight: 600; }
    
    /* 長條圖樣式 (CSS Bar Chart) */
    .chart-container { margin: 20px 0; background: #fafafa; padding: 20px; border-radius: 8px; }
    .chart-title { font-size: 16px; font-weight: bold; margin-bottom: 15px; color: #444; text-align: center; }
    .bar-row { display: flex; align-items: center; margin-bottom: 12px; }
    .bar-label { width: 150px; font-size: 12px; color: #555; text-align: right; padding-right: 15px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .bar-wrapper { flex-grow: 1; background: #eee; height: 14px; border-radius: 7px; overflow: hidden; position: relative; }
    .bar { height: 100%; background: linear-gradient(90deg, #3498db, #2980b9); border-radius: 7px; transition: width 1s ease-in-out; }
    .bar-value { width: 40px; font-size: 12px; font-weight: bold; color: #2c3e50; padding-left: 10px; }
    .bar-red { background: linear-gradient(90deg, #e74c3c, #c0392b); }

    /* 表格樣式 */
    .risk-matrix { width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 14px; }
    .risk-matrix th, .risk-matrix td { border: 1px solid #dfe6e9; padding: 12px; text-align: center; }
    .risk-matrix th { background-color: #f8f9fa; color: #2d3436; }
    .risk-high { color: #d63031; font-weight: bold; }
    
    .capa-box { background: #fffdf0; border-right: 4px solid #f1c40f; border-left: 4px solid #f1c40f; padding: 20px; border-radius: 4px; margin: 20px 0; }
    .sub-section { margin-top: 20px; padding-left: 15px; border-left: 2px solid #ecf0f1; }
    .regulatory-tag { display: inline-block; background: #e74c3c; color: #fff; padding: 2px 8px; border-radius: 4px; font-size: 10px; margin-right: 5px; }
</style>
"""

        prompt = f"""
你是一位擁有 20 年經驗的醫療器材技術長 (CTO) 與法規事務副總 (VP of RA/QA)，精通 ISO 14971 風險管理、MDR/IVDR 法規與 21 CFR Part 803。
請根據以下數據產出「深度專家級分類統計與視覺化」執行報告。

產品名稱：{product_name}
分析期間：{start_date} 到 {end_date}

總體統計基準 (REAL TOTALS):
{json.dumps(total_stats, ensure_ascii=False, indent=2)}

各分批原始數據摘要 (包含個別事件中的品牌與故障代碼關鍵字):
{summaries_text}

請嚴格執行以下深度分析任務，並產出結構化 HTML：

1. **產品/品牌分類統計 (Product/Brand Analysis)**：
   - 使用我提供的 `brand_distribution` 數據進行深度對比。
   - 繪製 **A) 子產品/型號統計圖**。

2. **故障模式深度解析 (Technical Failure Mode Deep Dive)**：
   - 使用我提供的 `failure_modes` 數據。
   - 繪製 **B) 故障模式排行圖**。
   - **[新增]**：針對 Top 3 故障模式進行「技術根本原因推論」，從物理、機械或軟體邏輯角度分析。

3. **視覺化圖表生成 (Embedded Charts)**：
   - 必須產出兩組圖表，且數據必須完全一致。
   - 標籤與數值需清晰。

4. **專業報告章節 (HTML)**：
   - **a) 執行摘要** (ID: `section-summary`)。
   - **b) 分類統計圖表區** (ID: `section-stats`)：包含上述兩組圖表。
   - **c) ISO 14971 風險深度矩陣** (ID: `section-risk`)。
   - **d) 法規影響與合規評估** (ID: `section-regulatory`)：分析對 MDR/FDA 合規性的潛在威脅。
   - **e) CAPA 具體行動建議** (ID: `section-capa`)：包含短期(糾正)、中期(預防)、長期(設計更改)建議。

要求：
- 每個主要章節標題必須包含對應的 ID 屬性（如 <h2 id="section-summary" class="section-title">...</h2>）。
- 內容必須極度專業、詳細且具備前瞻性建議。
- 全程使用繁體中文。

請確保輸出為 JSON 物件，包含 report_html 與 stats_json。
"""
        schema = {
            "type": "OBJECT",
            "properties": {
                "report_html": {"type": "STRING"},
                "stats_json": {
                    "type": "OBJECT",
                    "properties": {
                        "total_recalls": {"type": "INTEGER"},
                        "total_events": {"type": "INTEGER"},
                        "top_issues": {"type": "ARRAY", "items": {"type": "STRING"}},
                        "critical_warnings": {"type": "INTEGER"},
                        "fsca_recommended": {"type": "BOOLEAN"},
                        "max_risk_level": {"type": "STRING"}
                    },
                    "required": ["total_recalls", "total_events", "top_issues",
                                 "critical_warnings", "fsca_recommended", "max_risk_level"]
                }
            },
            "required": ["report_html", "stats_json"]
        }

        try:
            response_text = self._generate_with_retry(prompt, schema=schema)
            if response_text.startswith("```json"):
                response_text = response_text[7:]
                if response_text.endswith("```"):
                    response_text = response_text[:-3]
            
            result = json.loads(response_text.strip())
            report_html = result.get("report_html", "<p>沒有產出報告內容</p>")
            
            # 串接樣式與內容
            full_html = f"{report_style}\n<div class='qa-report'>\n{report_html}\n</div>"
            
            stats_json = json.dumps(result.get("stats_json", {}))
            return full_html, stats_json
        except Exception as e:
            logger.error(f"Failed to final report: {e}")
            return f"<p style='color:red;'>最終彙整報告失敗：{e}</p>", "{}"

    def analyze_single_record(self, record_type: str, raw_data: str) -> str:
        """
        P3-1: 針對單筆紀錄進行深度專家級解析（含 ISO 14971 風險矩陣與 FSCA 判斷）
        :return: HTML 格式字串
        """
        type_str = "FDA 產品召回記錄" if record_type == "recall" else "FDA MAUDE 不良事件報告"

        prompt = f"""
你是一位專業的醫療器材法規與品保專家，熟悉 ISO 14971、ISO 13485、MDR 2017/745 與 21 CFR Part 803。
這裡有一筆 {type_str} 的單一紀錄。
請依下列法規框架進行深度解析，以安全的 HTML 片段格式輸出
（不需要 html/body 標籤，直接從 <div> 或 <p> 開始，可使用 <strong>、<ul>、<table> 等，不可包含惡意腳本）。

解析內容必須包含：
1. **事件重點摘要**（30 字內）
2. **根本原因推論**（Root Cause Analysis）：推論可能的技術或系統根本原因
3. **ISO 14971 風險評估**：
   - 嚴重性 (Severity): S1(忽略)/S2(輕微)/S3(單一大)/S4(死亡)
   - 發生機率 (Probability): P1(極低)/P2(低)/P3(中)/P4(高)/P5(幾乎必發生)
   - 風險等級評定（低/中/高）與說明
4. **FSCA 判斷**：是否達到 Field Safety Corrective Action 啟動門檻
5. **給品保人員與設計單位的改善建議**（可行動作清單）

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

