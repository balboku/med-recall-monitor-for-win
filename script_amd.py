import urllib.request
from bs4 import BeautifulSoup
import re

url = "https://www.iso.org/standard/70907.html"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
html = urllib.request.urlopen(req).read().decode('utf-8')
soup = BeautifulSoup(html, "html.parser")

amd_texts = []
for el in soup.find_all(string=re.compile(r"Amd", re.IGNORECASE)):
    amd_texts.append(str(el).strip())
    print("Found text:", str(el).strip())

# Check for Amendment blocks
for h in soup.find_all(re.compile('^h[1-6]$'), string=re.compile(r"Amendments", re.IGNORECASE)):
    container = h.find_parent("div", class_="card") or h.find_parent("div")
    if container:
        print("Amendment container found.")
        print(container.get_text(strip=True))

