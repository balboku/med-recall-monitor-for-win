"""
一次性資料匯入腳本：將外來文件清單.xlsx 中的所有法規標準匯入 standards 資料庫表格。
使用方式：在 backend 目錄下執行 python scripts/import_standards_excel.py
"""
import sys
import os
from pathlib import Path
import io

# 強制 stdout 使用 UTF-8，避免 Windows cp950 環境的 emoji 編碼錯誤
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 確保 backend 目錄在路徑中
sys.path.insert(0, str(Path(__file__).parent.parent))

import openpyxl
from database import get_db
from datetime import datetime

# -----------------------------------------------------------------
# 標準版本對應：法規標準名稱 -> 版本年份（從標準名稱解析出的目前版本）
# -----------------------------------------------------------------
def _extract_version_from_name(standard_name: str) -> str:
    """從法規標準名稱中嘗試解析版本年份，例如 'ISO 13485:2016' -> '2016'"""
    import re
    # 比對最後一個年份（例如 :2016, :2024, -2023 等）
    match = re.search(r'[:\-](\d{4})(?:\+|$|\s|/)', standard_name + ' ')
    if match:
        return match.group(1)
    # 有些標準格式含括號，例如 ASTM F1980-21，提取最後兩碼年份
    match2 = re.search(r'-(\d{2})(?:[a-zA-Z]*)?$', standard_name.strip())
    if match2:
        yr = int(match2.group(1))
        return str(2000 + yr if yr < 90 else 1900 + yr)
    return ""


# -----------------------------------------------------------------
# Source URL 對應表：把常見的標準代號對應到官方查詢頁面
# -----------------------------------------------------------------
STANDARD_URLS = {
    # ISO
    "ISO 13485": "https://www.iso.org/standard/59752.html",
    "ISO 14971": "https://www.iso.org/standard/72704.html",
    "ISO 2859-1": "https://www.iso.org/standard/19588.html",
    "ISO 10993-1": "https://www.iso.org/standard/68936.html",
    "ISO 15223-1": "https://www.iso.org/standard/77326.html",
    "ISO 11135": "https://www.iso.org/standard/56137.html",
    "ISO 11137-1": "https://www.iso.org/standard/56137.html",
    "ISO 11737-1": "https://www.iso.org/standard/66457.html",
    "ISO 11737-2": "https://www.iso.org/standard/68208.html",
    "ISO 11737-3": "https://www.iso.org/standard/79140.html",
    "ISO 17664-1": "https://www.iso.org/standard/67416.html",
    "ISO 17664-2": "https://www.iso.org/standard/80075.html",
    "ISO 17665": "https://www.iso.org/standard/72820.html",
    "ISO 11607-1": "https://www.iso.org/standard/74956.html",
    "ISO 11607-2": "https://www.iso.org/standard/74957.html",
    "ISO 15225": "https://www.iso.org/standard/65047.html",
    "ISO 3166-1": "https://www.iso.org/standard/72482.html",
    "ISO 8601-1": "https://www.iso.org/standard/70907.html",
    "ISO 10555-1": "https://www.iso.org/standard/56471.html",
    "ISO 11070": "https://www.iso.org/standard/74946.html",
    "ISO 80601-2-55": "https://www.iso.org/standard/80200.html",
    "ISO 10993-10": "https://www.iso.org/standard/76063.html",
    "ISO 10993-14": "https://www.iso.org/standard/32338.html",
    "ISO 10993-17": "https://www.iso.org/standard/74649.html",
    "ISO 10993-13": "https://www.iso.org/standard/44626.html",
    "ISO 10993-15": "https://www.iso.org/standard/72051.html",
    "ISO 10993-11": "https://www.iso.org/standard/60153.html",
    "ISO 10993-18": "https://www.iso.org/standard/72059.html",
    "ISO 10993-12": "https://www.iso.org/standard/77402.html",
    # IEC
    "IEC 60601-1": "https://webstore.iec.ch/en/publication/2606",
    "IEC 60601-2-2": "https://webstore.iec.ch/en/publication/62893",
    "IEC 60601-1-2": "https://webstore.iec.ch/en/publication/22410",
    "IEC 60601-1-6": "https://webstore.iec.ch/en/publication/25407",
    "IEC 60601-1-8": "https://webstore.iec.ch/en/publication/25410",
    "IEC 62304": "https://webstore.iec.ch/en/publication/6793",
    "IEC 62366-1": "https://webstore.iec.ch/en/publication/21863",
    "IEC 62133-2": "https://webstore.iec.ch/en/publication/30985",
    "IEC 60529": "https://webstore.iec.ch/en/publication/2726",
    "IEC 60417": "https://webstore.iec.ch/en/publication/23429",
    "IEC 61847": "https://webstore.iec.ch/en/publication/20181",
    "IEC/TR 80002-1": "https://webstore.iec.ch/en/publication/7556",
    "IEC/TS 60601-4-2": "https://webstore.iec.ch/en/publication/68592",
    # 台灣法規 (全國法規資料庫)
    "醫療器材管理法": "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0030106",
    "醫療器材管理法施行細則": "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0030117",
    "醫療器材分類分級管理辦法": "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0030110",
    "醫療器材品質管理系統準則": "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0030129",
    "醫療器材安全監視管理辦法": "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0030140",
    "醫療器材回收處理辦法": "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0030141",
    "個人資料保護法": "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=I0050021",
    "個人資料保護法施行細則": "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=I0050022",
    # FDA / eCFR
    "21 CFR Part 820": "https://www.ecfr.gov/current/title-21/chapter-I/subchapter-H/part-820",
    # MDCG (EU)
    "Regulation (EU) 2017/745": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02017R0745-20230320",
    # ASTM
    "ASTM F88": "https://www.astm.org/f0088_f0088m-23.html",
    "ASTM F1980": "https://www.astm.org/f1980-21.html",
    "ASTM F1140M": "https://www.astm.org/f1140_f1140m-13r20e01.html",
    "ASTM F1929": "https://www.astm.org/f1929-23.html",
    "ASTM F1608": "https://www.astm.org/f1608-21.html",
    "ASTM D4169": "https://www.astm.org/d4169-23.html",
    "ASTM D4332": "https://www.astm.org/d4332-22.html",
}

def get_source_url(standard_name: str) -> str:
    """根據法規標準名稱，從對應表中找到最適合的官方網址"""
    # 按照長度遞減排序，確保長字串（如 ISO 10993-10）優先比對
    sorted_keys = sorted(STANDARD_URLS.keys(), key=len, reverse=True)
    for key in sorted_keys:
        if standard_name.startswith(key):
            # 確保不會發生 `ISO 10993-1` 錯誤匹配到 `ISO 10993-10` 的情況
            # 也就是 key 的下個字元不能是數字
            next_char = standard_name[len(key):len(key)+1]
            if not next_char or not next_char.isdigit():
                return STANDARD_URLS[key]
    return ""

def get_category(company_code: str) -> str:
    """根據公司編號前綴判斷來源類別"""
    prefix_map = {
        "R101": "ISO",
        "R102": "EN ISO / EN",
        "R103": "BS EN",
        "R200": "IEC",
        "R301": "EU Regulation",
        "R302": "MDCG Guidance",
        "R401": "FDA / USP",
        "R402": "FDA Guidance",
        "R500": "ASTM / AAMI",
        "R601": "Taiwan TFDA",
        "R602": "Taiwan TFDA Announcement",
        "R000": "International / Other",
    }
    for prefix, category in prefix_map.items():
        if company_code.startswith(prefix):
            return category
    return "Other"


def import_standards(excel_path: str, dry_run: bool = False):
    wb = openpyxl.load_workbook(excel_path)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    # 找到標頭列（含「法規標準名稱」欄位的那列）
    header_row_idx = None
    for i, row in enumerate(rows):
        if any('法規標準名稱' in str(c) for c in row if c):
            header_row_idx = i
            break

    if header_row_idx is None:
        print("❌ 找不到欄位標頭（法規標準名稱），請確認 Excel 格式。")
        return

    headers = rows[header_row_idx]
    col_code = None
    col_name = None
    for j, h in enumerate(headers):
        if h and '公司編號' in str(h):
            col_code = j
        if h and '法規標準名稱' in str(h):
            col_name = j

    if col_code is None or col_name is None:
        print("❌ 找不到「公司編號」或「法規標準名稱」欄位。")
        return

    data_rows = rows[header_row_idx + 1:]
    standards_to_import = []
    for row in data_rows:
        if not any(row):
            continue
        code = str(row[col_code]).strip() if row[col_code] else ""
        name = str(row[col_name]).strip() if row[col_name] else ""
        if not code or not name or code == 'None' or name == 'None':
            continue

        version = _extract_version_from_name(name)
        source_url = get_source_url(name)
        category = get_category(code)

        standards_to_import.append({
            "standard_number": code,
            "title": name,
            "current_version": version,
            "source_url": source_url,
            "notes": category,
        })

    print(f"📋 共讀取到 {len(standards_to_import)} 筆法規標準資料。")
    if dry_run:
        for s in standards_to_import:
            print(f"  [{s['standard_number']}] {s['title']} (版本: {s['current_version'] or 'N/A'}, URL: {s['source_url'][:50] + '...' if len(s['source_url']) > 50 else s['source_url'] or '(待補)'})")
        print("ℹ️  Dry-run 模式，未實際寫入資料庫。")
        return

    conn = get_db()
    inserted = 0
    updated = 0
    skipped = 0
    try:
        for s in standards_to_import:
            existing = conn.execute(
                "SELECT id, source_url FROM standards WHERE standard_number = ?",
                (s["standard_number"],)
            ).fetchone()

            if existing:
                # 若已存在但沒有 source_url，則補充 URL
                if not existing["source_url"] and s["source_url"]:
                    conn.execute(
                        "UPDATE standards SET source_url = ?, title = ?, updated_at = ? WHERE standard_number = ?",
                        (s["source_url"], s["title"], datetime.now().isoformat(), s["standard_number"])
                    )
                    updated += 1
                else:
                    skipped += 1
            else:
                conn.execute("""
                    INSERT INTO standards (standard_number, title, current_version, source_url, notes, status)
                    VALUES (?, ?, ?, ?, ?, 'active')
                """, (s["standard_number"], s["title"], s["current_version"],
                      s["source_url"], s["notes"]))
                inserted += 1

        conn.commit()
        print(f"✅ 匯入完成：新增 {inserted} 筆，更新 {updated} 筆，略過 {skipped} 筆。")
    except Exception as e:
        print(f"❌ 匯入時發生錯誤：{e}")
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="匯入外來文件清單到 standards 資料庫")
    parser.add_argument("--excel", default="外來文件清單.xlsx",
                        help="Excel 檔案路徑（預設：外來文件清單.xlsx）")
    parser.add_argument("--dry-run", action="store_true",
                        help="僅列印將匯入的資料，不實際寫入資料庫")
    args = parser.parse_args()

    # 解析 Excel 路徑（相對於根目錄）
    backend_dir = Path(__file__).parent.parent
    root_dir = backend_dir.parent
    excel_path = Path(args.excel) if Path(args.excel).is_absolute() else root_dir / args.excel

    if not excel_path.exists():
        print(f"❌ 找不到 Excel 檔案：{excel_path}")
        sys.exit(1)

    import_standards(str(excel_path), dry_run=args.dry_run)
