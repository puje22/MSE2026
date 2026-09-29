"""
Test the dividend-announcement extractor before it gets wired into the
daily pipeline.

Usage (from scripts/ folder):
    python test_dividend_announcements.py TTL
"""

import sys
import json
from pathlib import Path

from scraper_lib import fetch, parse_dividend_announcements

SCRIPT_DIR = Path(__file__).resolve().parent


def main():
    with (SCRIPT_DIR / "ticker_ids.json").open("r", encoding="utf-8") as f:
        ids = json.load(f)

    ticker = "TTL"
    for arg in sys.argv[1:]:
        if arg.startswith("-"):
            continue
        ticker = arg
        break

    cid = ids[ticker]
    html = fetch(cid)
    results = parse_dividend_announcements(html)

    if not results:
        print(f"No dividend announcements found for {ticker}.")
    else:
        print(f"Found {len(results)} dividend announcement(s) for {ticker}:")
        for r in results:
            print(f"  {r['date']}  —  {r['headline']}")


if __name__ == "__main__":
    main()
