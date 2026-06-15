import urllib.request
import re

url = "https://www.iso.org/standard/70907.html"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
html = urllib.request.urlopen(req).read().decode('utf-8')

amd_matches = re.findall(r'ISO [^<]+Amd[^<]+', html, re.IGNORECASE)
print("Found AMDs:", amd_matches)

# also search for general Amd inside anchor tags
anchors = re.findall(r'<a[^>]+>([^<]+Amd[^<]+)</a>', html, re.IGNORECASE)
print("Found inside anchors:", anchors)
