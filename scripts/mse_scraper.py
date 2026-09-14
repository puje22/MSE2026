"""
MSE (Mongolian Stock Exchange) daily OHLCV scraper
===================================================

Scrapes daily trading history (High, Low, Open, Close, Volume, Value, Date)
for a set of target tickers from the legacy site old.mse.mn, which — unlike
the current mse.mn / bdsec.mn sites — renders full history tables as plain
server-side HTML (no JS/API calls needed).

HOW IT WORKS
------------
Each listed company has a page at:
    https://old.mse.mn/en/company/{id}
where {id} is an internal numeric ID (NOT related to the ticker
alphabetically). There's no public ticker->id lookup table, so this script
just crawls a range of ids, reads the ticker off each page's
"CompanyName (TICKER)" header, and keeps only the ones you want.

Empirically, ids for currently-listed companies fall roughly in the 1-700
range (e.g. Tavantolgoi/TTL=458, Gobi/GOV=354). Adjust ID_RANGE below if you
need to widen the search.

USAGE
-----
    pip install requests beautifulsoup4 lxml
    python mse_scraper.py

Output: mse_daily_prices.csv with columns:
    ticker, company_name, date, open, high, low, close, volume, value

Runtime: ~700 requests with a polite delay; expect 10-20 minutes.
Re-running is safe — it skips ids already saved in the cache file.
"""

import re
import csv
import time
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

# ---- Configuration -------------------------------------------------------

TARGET_TICKERS = {
    "KHAN", "TTL", "GLMT", "APU", "AARD", "SBM", "MSE", "TDB", "XAC", "TUM",
    "LEND", "CUMN", "MNDL", "SUU", "INV", "ERDN", "QPAY", "SEND", "UID",
    "MFG", "XOC",
}

BASE_URL = "https://old.mse.mn/en/company/{id}"
ID_RANGE = range(1, 3000)          # widen if some tickers aren't found
REQUEST_DELAY = 0.3               # seconds between requests (politeness)
MAX_WORKERS = 6                   # parallel requests; lower if you get blocked
TIMEOUT = 20

OUT_CSV = "mse_daily_prices.csv"
CACHE_FILE = "mse_scrape_cache.json"   # id -> {ticker, name, rows} or null

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; research-scraper/1.0)"
}

# ---- Parsing ---------------------------------------------------------------

# Marker text that immediately precedes the per-company header+quote block,
# e.g. "...Trading history of Block Trade Tavantolgoi (TTL) 56900 -200 ..."
SECTION_MARKER = "Trading history of Block Trade"

# Header pattern like: "Tavantolgoi (TTL)" or "Gobi (GOV)" -- NOT anchored to
# start/end of the whole page text (that was the bug: ^/$ only match the
# very start/end of the entire string, so it never matched mid-page).
HEADER_RE = re.compile(r"([A-Za-z0-9][\w \-\.,'&]{1,58}?)\s*\(([A-Z0-9]{2,10})\)")

# Data rows in the history table look like (as plain text after "Date" header):
# <num> <high> <low> <open> <close> <volume> <value> <date>
ROW_RE = re.compile(
    r"(\d+)\s+"                      # row number
    r"([\d,]+(?:\.\d+)?)\s+"         # high
    r"([\d,]+(?:\.\d+)?)\s+"         # low
    r"([\d,]+(?:\.\d+)?)\s+"         # open
    r"([\d,]+(?:\.\d+)?)\s+"         # close
    r"([\d,]+(?:\.\d+)?)\s+"         # volume
    r"([\d,]+(?:\.\d+)?)\s+"         # value
    r"(\d{4}-\d{2}-\d{2})"           # date
)


def num(s):
    return float(s.replace(",", ""))


def fetch(company_id):
    url = BASE_URL.format(id=company_id)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException:
        return None
    return resp.text


def parse_page(html):
    """Return (ticker, company_name, rows) or None if not a valid company page."""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)

    idx = text.find(SECTION_MARKER)
    if idx == -1:
        return None  # not a valid/complete company page
    search_text = text[idx + len(SECTION_MARKER):]

    m = HEADER_RE.search(search_text)
    if not m:
        return None

    name, ticker = m.group(1).strip(), m.group(2).strip()

    rows = []
    for rm in ROW_RE.finditer(search_text):
        _, high, low, open_, close, vol, val, date = rm.groups()
        rows.append({
            "date": date,
            "open": num(open_),
            "high": num(high),
            "low": num(low),
            "close": num(close),
            "volume": num(vol),
            "value": num(val),
        })
    return ticker, name, rows


def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)


def main():
    cache = load_cache()
    found_tickers = set()

    ids_to_fetch = [i for i in ID_RANGE if str(i) not in cache]
    print(f"Fetching {len(ids_to_fetch)} company pages "
          f"({len(cache)} already cached)...")

    def worker(cid):
        html = fetch(cid)
        time.sleep(REQUEST_DELAY)
        if html is None:
            return cid, None
        parsed = parse_page(html)
        return cid, parsed

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(worker, cid): cid for cid in ids_to_fetch}
        done_count = 0
        for fut in as_completed(futures):
            cid, parsed = fut.result()
            done_count += 1
            if parsed:
                ticker, name, rows = parsed
                cache[str(cid)] = {"ticker": ticker, "name": name, "rows": rows}
                if ticker in TARGET_TICKERS:
                    found_tickers.add(ticker)
                    print(f"  [{done_count}/{len(ids_to_fetch)}] "
                          f"id={cid}: {ticker} ({name}) - {len(rows)} rows  <-- TARGET")
                else:
                    print(f"  [{done_count}/{len(ids_to_fetch)}] "
                          f"id={cid}: {ticker} ({name}) - {len(rows)} rows")
            else:
                cache[str(cid)] = None

            if done_count % 25 == 0:
                save_cache(cache)

    save_cache(cache)

    missing = TARGET_TICKERS - found_tickers
    if missing:
        print(f"\nWARNING: tickers not found in id range {ID_RANGE}: {sorted(missing)}")
        print("Try widening ID_RANGE (e.g. range(1, 1200)) and re-run.")

    # Write combined CSV
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ticker", "company_name", "date", "open", "high",
                          "low", "close", "volume", "value"])
        for cid, entry in cache.items():
            if not entry:
                continue
            ticker = entry["ticker"]
            if ticker not in TARGET_TICKERS:
                continue
            name = entry["name"]
            for row in entry["rows"]:
                writer.writerow([
                    ticker, name, row["date"], row["open"], row["high"],
                    row["low"], row["close"], row["volume"], row["value"],
                ])

    print(f"\nDone. Wrote {OUT_CSV}")


if __name__ == "__main__":
    main()