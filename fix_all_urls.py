import re
import sqlite3

mismatched_keys = []
with open("mismatches.txt", "r", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            key = line.split("\t")[0].strip()
            mismatched_keys.append(key)

print("Keys to fix:", mismatched_keys)

# 1. Update backend/scripts/import_standards_excel.py
with open(r"backend\scripts\import_standards_excel.py", "r", encoding="utf-8") as f:
    content = f.read()

for key in mismatched_keys:
    # find lines like: "ISO 11137-1": "https://www.iso.org/standard/56137.html",
    pattern = rf'("{key}":\s*)"https://[^"]+"'
    content = re.sub(pattern, r'\1""', content)

with open(r"backend\scripts\import_standards_excel.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Updated python import script.")

# 2. Update backend/data/monitor.db
c = sqlite3.connect(r"backend\data\monitor.db")
for key in mismatched_keys:
    c.execute("UPDATE standards SET source_url = '' WHERE standard_number LIKE ?", ('%' + key + '%',))
c.commit()
c.close()

print("Updated database records successfully.")
