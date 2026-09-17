"""
Test the dividend-announcement extractor before it gets wired into the
daily pipeline.

Usage (from scripts/ folder):
    python test_dividend_announcements.py TTL
"""

import sys
import json
from scraper_lib import fetch, parse_dividend_announcements

ticker = sys.argv[1] if len(sys.argv) > 1 else "TTL"
ids = json.load(open("ticker_ids.json"))
cid = ids[ticker]

html = fetch(cid)
results = parse_dividend_announcements(html)

if not results:
    print(f"No dividend announcements found for {ticker}.")
else:
    print(f"Found {len(results)} dividend announcement(s) for {ticker}:")
    for r in results:
        print(f"  {r['date']}  —  {r['headline']}")
