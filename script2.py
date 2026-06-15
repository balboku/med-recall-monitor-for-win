import urllib.request
import urllib.parse
import re
import json

query = "site:iso.org ISO 2859-1:1999"
url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'})
try:
    html = urllib.request.urlopen(req).read().decode('utf-8')
    urls = re.findall(r'https://www\.iso\.org/standard/\d+\.html', html)
    print("Found urls:", set(urls))
except Exception as e:
    print(e)
