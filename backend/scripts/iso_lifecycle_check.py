"""
ISO 標準 Life cycle 版本檢查 — 手動命令列工具
============================================================

模擬「到 ISO 官網搜尋法規名稱 → 進入該法規頁面 → 查看 Life cycle 區塊」的流程，
判斷現行版本落在什麼位置（Now / Previously），以及是否已有新版本發行或公告
（Revised by / Will be replaced by / New version available）。若有新版本則判定「有更新」。

實際的取得與解析邏輯集中於 crawlers/iso_browser.py（後端 API、爬蟲共用），本檔僅為
可手動執行的命令列包裝。www.iso.org 受 Cloudflare 防護，預設以純 HTTP（curl_cffi 模擬
Chrome TLS 指紋，見 crawlers/iso_http.py）取得，失敗才退回 nodriver + 本機 Chrome。

使用方式（於 backend 目錄下）：
    python scripts/iso_lifecycle_check.py "ISO 10993-1"
    python scripts/iso_lifecycle_check.py "ISO 10993-1" --current 2018
    set ISO_HTTP_DISABLE=1 && python scripts/iso_lifecycle_check.py "ISO 13485"     # 強制走瀏覽器
    set ISO_BROWSER_HEADLESS=1 && python scripts/iso_lifecycle_check.py "ISO 13485"  # 瀏覽器嘗試無頭

    --current  指定目前手上／追蹤的版本年份（例如 2018），用於與官網現行版比對判定有無更新。
"""
import sys
import argparse
from pathlib import Path

# 讓腳本可在 backend 目錄外執行：將 backend 目錄加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crawlers import iso_browser  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="ISO 標準 Life cycle 版本檢查")
    ap.add_argument("standard_name", help="法規名稱／編號，例如 'ISO 10993-1'")
    ap.add_argument("--current", default="", help="目前追蹤的版本年份，例如 2018")
    args = ap.parse_args()

    print(f"🔎 ISO 官網搜尋：{args.standard_name}")
    res = iso_browser.resolve_source_url_sync(args.standard_name, args.current)

    if not res.get("ok"):
        print(f"❌ {res.get('error', '未知錯誤')}")
        for c in res.get("candidates", []):
            print(f"     - {c}")
        return

    print(f"➡️  進入標準頁：{res['found_title']}  [{res['source_url']}]")
    print("\n========== Life cycle ==========")
    if res["previously"]:
        print("Previously（先前版本）:")
        for p in res["previously"]:
            print(f"   - [{p['status'] or '?'}] {p['title']}")
    print(f"Now（現行）: [{res['now_status'] or '?'}] {res['now_title']}"
          + (f"  (Stage: {res['now_stage']})" if res["now_stage"] else ""))
    if res["newer_title"]:
        print(f"{res['newer_kind']}（新版/取代）: {res['newer_title']}"
              + (f"  [{res['newer_url']}]" if res["newer_url"] else ""))
    print("================================\n")

    print("🟥 判定：有更新" if res["has_update"]
          else "🟩 判定：無更新（現行版即為最新，且無新版公告）")
    for r in res["reasons"]:
        print(f"   • {r}")


if __name__ == "__main__":
    main()
