import urllib.request
import re

url = "https://html.duckduckgo.com/html/?q=site:iso.org+%22ISO+2859-1:1999%22"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
html = urllib.request.urlopen(req).read().decode('utf-8')
urls = re.findall(r'https://www\.iso\.org/standard/\d+\.html', html)
for u in set(urls):
    print(u)
