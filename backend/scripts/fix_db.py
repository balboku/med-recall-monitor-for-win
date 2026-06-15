import sqlite3
c = sqlite3.connect('backend/data/monitor.db')

# Wipe out the wrong URL
c.execute("UPDATE standards SET source_url = '' WHERE standard_number LIKE '%2859%'")

# Change the ISO 8601-1 URL if it's incorrect, wait, ISO 8601-1 is already in DB? Yes, we saw ISO 8601-1:2019 there with ID R101-something or we didn't?
# Wait, user said "ISO 8601-1:2019+Amd 1:2022，網站點開是對的". So the URL is correct! And the importer has: "ISO 8601-1": "https://www.iso.org/standard/70907.html", which is correct!

c.commit()
print("Fixed ISO 2859-1 URL in database.")
