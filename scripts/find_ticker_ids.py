"""
Standalone ticker-ID finder — use this if you no longer have the original
mse_scrape_cache.json from the first full crawl.

Scans old.mse.mn/en/company/{id} across ID_RANGE, keeps only pages matching
your target tickers, and writes ticker_ids.json directly. Run this from
inside the scripts/ folder (it imports scraper_lib.py, which lives here).

Usage:
    cd scripts
    python find_ticker_ids.py
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from scraper_lib import fetch, parse_page

TARGET_TICKERS = {
    "KHAN", "TTL", "GLMT", "APU", "AARD", "SBM", "MSE", "TDB", "XAC", "TUM",
    "LEND", "CUMN", "MNDL", "SUU", "INV", "ERDN", "QPAY", "SEND", "UID",
    "MFG", "XOC",
}

ID_RANGE = range(1, 3000)
MAX_WORKERS = 6
OUT_FILE = "ticker_ids.json"


def worker(cid):
    html = fetch(cid, delay=0.2)
    if html is None:
        return cid, None
    parsed = parse_page(html)
    return cid, parsed


def main():
    found = {}
    print(f"Scanning {len(ID_RANGE)} ids for {len(TARGET_TICKERS)} target tickers...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(worker, cid): cid for cid in ID_RANGE}
        done = 0
        for fut in as_completed(futures):
            cid, parsed = fut.result()
            done += 1
            if parsed:
                ticker, name, rows = parsed
                if ticker in TARGET_TICKERS and ticker not in found:
                    found[ticker] = cid
                    print(f"  [{done}/{len(ID_RANGE)}] Found {ticker} "
                          f"({name}) at id={cid}")
            if done % 200 == 0:
                print(f"  ...{done}/{len(ID_RANGE)} scanned, "
                      f"{len(found)}/{len(TARGET_TICKERS)} tickers found so far")
            if len(found) == len(TARGET_TICKERS):
                # Found everything early -- still let already-submitted
                # futures drain, but no need to keep waiting deliberately.
                pass

    missing = TARGET_TICKERS - set(found)
    if missing:
        print(f"\nWARNING: still missing: {sorted(missing)}")
        print("These may use a different URL pattern (e.g. funds under "
              "/en/fund/{id} instead of /en/company/{id}).")

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(found, f, indent=2, sort_keys=True)

    print(f"\nWrote {OUT_FILE} with {len(found)} tickers.")


if __name__ == "__main__":
    main()
