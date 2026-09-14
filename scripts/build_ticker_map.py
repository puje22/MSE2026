"""
Run this ONCE, locally, in the same folder where your original
`mse_scrape_cache.json` (from the full 1-3000 ID crawl) lives.

It extracts just the {ticker: company_id} pairs for your target tickers and
writes ticker_ids.json — this is what the daily GitHub Action will use so it
never has to brute-force scan thousands of IDs again.

Usage:
    python build_ticker_map.py
"""

import json
import os

TARGET_TICKERS = {
    "KHAN", "TTL", "GLMT", "APU", "AARD", "SBM", "MSE", "TDB", "XAC", "TUM",
    "LEND", "CUMN", "MNDL", "SUU", "INV", "ERDN", "QPAY", "SEND", "UID",
    "MFG", "XOC",
}

CACHE_FILE = "mse_scrape_cache.json"
OUT_FILE = "ticker_ids.json"


def main():
    if not os.path.exists(CACHE_FILE):
        print(f"ERROR: {CACHE_FILE} not found in this folder.")
        return

    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        cache = json.load(f)

    ticker_ids = {}
    for cid, entry in cache.items():
        if not entry:
            continue
        ticker = entry.get("ticker")
        if ticker in TARGET_TICKERS:
            ticker_ids[ticker] = int(cid)

    missing = TARGET_TICKERS - set(ticker_ids)
    if missing:
        print(f"WARNING: still missing from cache: {sorted(missing)}")
        print("These weren't found even in the widened 1-3000 crawl.")

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(ticker_ids, f, indent=2, sort_keys=True)

    print(f"Wrote {OUT_FILE} with {len(ticker_ids)} tickers:")
    for t, i in sorted(ticker_ids.items()):
        print(f"  {t}: {i}")
    print("\nCommit this file into your GitHub repo at "
          "scripts/ticker_ids.json (or wherever daily_update.py expects it).")


if __name__ == "__main__":
    main()
