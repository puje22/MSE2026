"""
Quick targeted check for the tickers find_ticker_ids_open.py couldn't find.

Rather than a slow full re-scan, this tries each missing ticker's KNOWN
members.mse.mn id directly against open.mse.mn, in case open.mse.mn reuses
that numbering for some securities (migrations aren't always consistent).

Usage (from scripts/ folder):
    python check_missing_open_ids.py
"""

import json
from scraper_lib import fetch_open, parse_open_page

MISSING = ["AARD", "CUMN", "ERDN", "GLMT", "KHAN", "LEND", "MNDL", "QPAY", "SEND"]

members_ids = json.load(open("ticker_ids.json"))
open_ids = json.load(open("ticker_ids_open.json")) if __import__("os").path.exists("ticker_ids_open.json") else {}

found_new = {}

for ticker in MISSING:
    members_cid = members_ids.get(ticker)
    if members_cid is None:
        print(f"{ticker}: no members.mse.mn id on file either, skipping")
        continue

    html = fetch_open(members_cid, delay=0.2)
    if html is None:
        print(f"{ticker}: fetch failed at members-id={members_cid}")
        continue

    parsed = parse_open_page(html)
    if parsed is None:
        print(f"{ticker}: members-id={members_cid} -> no ISIN/rows match on open.mse.mn")
        continue

    found_ticker, rows = parsed
    if found_ticker == ticker:
        print(f"{ticker}: MATCH at members-id={members_cid} "
              f"({len(rows)} rows, latest {rows[0]['date']})")
        found_new[ticker] = members_cid
    else:
        print(f"{ticker}: members-id={members_cid} on open.mse.mn is actually "
              f"'{found_ticker}' (different security, false lead)")

if found_new:
    open_ids.update(found_new)
    with open("ticker_ids_open.json", "w", encoding="utf-8") as f:
        json.dump(open_ids, f, indent=2, sort_keys=True)
    print(f"\nUpdated ticker_ids_open.json with {len(found_new)} new match(es).")

still_missing = [t for t in MISSING if t not in found_new]
if still_missing:
    print(f"\nStill missing (need the wider scan): {still_missing}")
