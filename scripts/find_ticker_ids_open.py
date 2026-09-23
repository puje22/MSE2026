"""
Finds ticker -> company_id mapping for open.mse.mn (the fresher, non-lagging
price source). This ID scheme APPEARS to match the old old.mse.mn IDs (e.g.
TTL=458 in both), but that's not guaranteed for every ticker, so this does a
full scan rather than assuming.

Usage:
    cd scripts
    python find_ticker_ids_open.py
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from scraper_lib import fetch_open, parse_open_page

TARGET_TICKERS = {
    "KHAN", "TTL", "GLMT", "APU", "AARD", "SBM", "MSE", "TDB", "XAC", "TUM",
    "LEND", "CUMN", "MNDL", "SUU", "INV", "ERDN", "QPAY", "SEND", "UID",
    "MFG", "XOC",
}

ID_RANGE = range(1, 3000)
MAX_WORKERS = 6
OUT_FILE = "ticker_ids_open.json"


def worker(cid):
    html = fetch_open(cid, delay=0.2)
    if html is None:
        return cid, None
    parsed = parse_open_page(html)
    return cid, parsed


def main():
    found = {}
    print(f"Scanning {len(ID_RANGE)} ids on open.mse.mn for "
          f"{len(TARGET_TICKERS)} target tickers...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(worker, cid): cid for cid in ID_RANGE}
        done = 0
        for fut in as_completed(futures):
            cid, parsed = fut.result()
            done += 1
            if parsed:
                ticker, rows = parsed
                if ticker in TARGET_TICKERS and ticker not in found:
                    found[ticker] = cid
                    print(f"  [{done}/{len(ID_RANGE)}] Found {ticker} "
                          f"at id={cid} ({len(rows)} rows, latest date "
                          f"{rows[0]['date']})")
            if done % 200 == 0:
                print(f"  ...{done}/{len(ID_RANGE)} scanned, "
                      f"{len(found)}/{len(TARGET_TICKERS)} found so far")

    missing = TARGET_TICKERS - set(found)
    if missing:
        print(f"\nWARNING: still missing: {sorted(missing)}")

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(found, f, indent=2, sort_keys=True)

    print(f"\nWrote {OUT_FILE} with {len(found)} tickers.")


if __name__ == "__main__":
    main()
