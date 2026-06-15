import urllib.request
import re
import time
import ssl

context = ssl._create_unverified_context()

STANDARD_URLS = {
    "ISO 13485": "https://www.iso.org/standard/59752.html",
    "ISO 14971": "https://www.iso.org/standard/72704.html",
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
    "IEC/TS 60601-4-2": "https://webstore.iec.ch/en/publication/68592"
}

mismatches = []
for key, url in STANDARD_URLS.items():
    if not url:
        continue
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        html = urllib.request.urlopen(req, context=context, timeout=10).read().decode('utf-8', errors='ignore')
        
        # basic pattern
        title_match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
        title = title_match.group(1).strip() if title_match else ""
        
        # normalize for checking: remove spaces and non-alphanumeric just to be safe
        key_norm = key.replace(" ", "").replace("-", "").replace("/", "").lower()
        title_norm = title.replace(" ", "").replace("-", "").replace("/", "").lower()
        
        if key_norm not in title_norm:
            print(f"MISMATCH! [Wanted]: {key} => [Actual Title]: '{title}' ({url})")
            mismatches.append((key, url, title))
        else:
            print(f"OK: {key}")
    except Exception as e:
        print(f"ERROR: {key} ({url}) => {e}")
    time.sleep(0.5)

print("\n--- Summary of Mismatches ---")
for key, url, title in mismatches:
    print(f"Wanted: {key} but got Web Title: '{title}' from {url}")
