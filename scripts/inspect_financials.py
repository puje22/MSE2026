"""
Run this once to print the raw "Summary of Financials" section for one
company, so we can see its exact text layout and build a precise parser.

Usage (from the scripts/ folder):
    python inspect_financials.py TTL
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

idx = text.find("Summary of Financials")
if idx == -1:
    print("Couldn't find 'Summary of Financials' section on this page.")
else:
    # Print the next ~3000 characters after that heading
    print(text[idx:idx + 3000])
