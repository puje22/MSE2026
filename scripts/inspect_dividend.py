"""
Checks whether a company page has any dividend-related data, and prints the
surrounding text so we can see the exact format if it does.

Usage (from scripts/ folder):
    python inspect_dividend.py TTL
"""

import sys
import json
from bs4 import BeautifulSoup
from scraper_lib import fetch

ticker = sys.argv[1] if len(sys.argv) > 1 else "TTL"
ids = json.load(open("ticker_ids.json"))
cid = ids[ticker]

html = fetch(cid)
soup = BeautifulSoup(html, "lxml")
text = soup.get_text(" ", strip=True)

# Look for any dividend-related keywords (case-insensitive)
keywords = ["dividend", "Dividend", "DIVIDEND", "ногдол ашиг"]  # last one is Mongolian for "dividend"
found_any = False
for kw in keywords:
    idx = text.find(kw)
    if idx != -1:
        found_any = True
        print(f"Found '{kw}' at position {idx}:")
        print(text[max(0, idx - 100):idx + 400])
        print("---")

if not found_any:
    print("No dividend-related text found anywhere on this page.")

# Also print the full list of nav/section links text near the top of the
# page, in case dividend info lives on a SEPARATE page we haven't found yet.
print()
print("=== First 2000 chars of page (to spot nav links to other sections) ===")
print(text[:2000])
