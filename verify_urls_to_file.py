import urllib.request
import re
import ssl

context = ssl._create_unverified_context()

STANDARD_URLS = {
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
}

with open("mismatches.txt", "w", encoding="utf-8") as f:
    for key, url in STANDARD_URLS.items():
        if not url:
            continue
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            html = urllib.request.urlopen(req, context=context, timeout=10).read().decode('utf-8', errors='ignore')
            title_match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
            title = title_match.group(1).strip() if title_match else ""
            key_num = key.split(" ")[1] if " " in key else key
            # basic check: does the number appear in the title?
            if key_num.split(":")[0] not in title:
                f.write(f"{key}\t{url}\t{title}\n")
        except Exception as e:
            f.write(f"{key}\t{url}\tERROR: {e}\n")
