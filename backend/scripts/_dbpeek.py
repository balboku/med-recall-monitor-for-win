import sqlite3, json
from pathlib import Path
db = Path(__file__).resolve().parent.parent / "data" / "monitor.db"
c = sqlite3.connect(str(db)); c.row_factory = sqlite3.Row
print("=== 先前受污染的 id 現況 ===")
for i in (74, 78, 86, 19, 22, 51, 41):
    r = c.execute("SELECT id,title,notes FROM standards WHERE id=?", (i,)).fetchone()
    if r:
        print(f" id={r['id']:>3} title={r['title']!r:<20} notes={r['notes']!r}")
print("\n=== 目前分類(notes)分布 ===")
cats = [dict(r) for r in c.execute(
    "SELECT notes, COUNT(*) n FROM standards GROUP BY notes ORDER BY n DESC")]
print(json.dumps(cats, ensure_ascii=False, indent=1))
print("\n含查核失敗的筆數:",
      c.execute("SELECT COUNT(*) FROM standards WHERE notes LIKE '%查核失敗%'").fetchone()[0])
