import sqlite3, json
from pathlib import Path
db = Path(__file__).resolve().parent.parent / "data" / "monitor.db"
c = sqlite3.connect(str(db)); c.row_factory = sqlite3.Row
rows = [dict(r) for r in c.execute(
    "SELECT id, standard_number, title, notes, last_checked, updated_at "
    "FROM standards WHERE notes LIKE '%查核失敗%' ORDER BY updated_at DESC")]
print(f"=== 目前受污染筆數: {len(rows)} ===")
for r in rows[:30]:
    print(f" id={r['id']:>3} {r['title']!r:<20} notes={r['notes']!r}")
    print(f"        last_checked={r['last_checked']}  updated_at={r['updated_at']}")
print("\n=== 目前分類分布 ===")
for r in c.execute("SELECT notes, COUNT(*) n FROM standards GROUP BY notes ORDER BY n DESC"):
    print(f" {r['n']:>3}  {r['notes']!r}")
