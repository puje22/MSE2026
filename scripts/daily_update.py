"""
Daily incremental updater for MSE daily price data.

Fetches each ticker's page (only the ~21 known company IDs — fast, no
brute-force ID scanning), re-parses the FULL history table (the site
doesn't support a "since date" query, so this is unavoidable per ticker),
and merges/dedupes into the master CSV.

Run by .github/workflows/daily_update.yml on a daily cron schedule.
Safe to run manually too:
    python scripts/daily_update.py
"""

import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from scraper_lib import fetch, parse_page, parse_financials  # noqa: E402

TICKER_IDS_FILE = os.path.join(os.path.dirname(__file__), "ticker_ids.json")
MASTER_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "mse_daily_prices.csv")
FINANCIALS_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "mse_financials.csv")

FIELDNAMES = ["ticker", "company_name", "date", "open", "high", "low",
              "close", "volume", "value"]

FINANCIALS_FIELDNAMES = [
    "ticker", "company_name", "year", "total_assets", "total_liabilities",
    "total_equity", "issued_shares", "sales_revenue", "cost_of_sales",
    "gross_profit", "net_income", "book_value_per_share", "roa", "roe",
    "rota", "eps", "pe_ratio",
]


def load_ticker_ids():
    with open(TICKER_IDS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_master():
    """Return dict of (ticker, date) -> row dict."""
    rows = {}
    if os.path.exists(MASTER_CSV):
        with open(MASTER_CSV, "r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows[(row["ticker"], row["date"])] = row
    return rows


def save_master(rows):
    os.makedirs(os.path.dirname(MASTER_CSV), exist_ok=True)
    ordered = sorted(rows.values(), key=lambda r: (r["ticker"], r["date"]))
    with open(MASTER_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in ordered:
            writer.writerow(row)


def load_financials():
    """Return dict of (ticker, year) -> row dict."""
    rows = {}
    if os.path.exists(FINANCIALS_CSV):
        with open(FINANCIALS_CSV, "r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows[(row["ticker"], row["year"])] = row
    return rows


def save_financials(rows):
    os.makedirs(os.path.dirname(FINANCIALS_CSV), exist_ok=True)
    ordered = sorted(rows.values(), key=lambda r: (r["ticker"], r["year"]))
    with open(FINANCIALS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FINANCIALS_FIELDNAMES)
        writer.writeheader()
        for row in ordered:
            writer.writerow(row)


def main():
    ticker_ids = load_ticker_ids()
    master = load_master()
    financials = load_financials()
    before_count = len(master)
    financials_before_count = len(financials)

    failures = []
    added_per_ticker = {}
    financials_added_per_ticker = {}

    for ticker, cid in sorted(ticker_ids.items()):
        html = fetch(cid)
        if html is None:
            failures.append(ticker)
            continue

        parsed = parse_page(html)
        if not parsed:
            failures.append(ticker)
            continue

        parsed_ticker, name, rows = parsed
        if parsed_ticker != ticker:
            # id->ticker drifted (site restructured); flag it, still use
            # the ticker we expected so downstream data stays consistent
            print(f"NOTE: id {cid} now reports ticker '{parsed_ticker}', "
                  f"expected '{ticker}'. Using expected ticker.")

        added = 0
        for row in rows:
            key = (ticker, row["date"])
            if key not in master:
                added += 1
            master[key] = {
                "ticker": ticker,
                "company_name": name,
                "date": row["date"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
                "value": row["value"],
            }
        added_per_ticker[ticker] = added

        # Financials come from the SAME page — no extra network request.
        fin_rows = parse_financials(html)
        fin_added = 0
        for fr in fin_rows:
            key = (ticker, str(fr["year"]))
            if key not in financials:
                fin_added += 1
            financials[key] = {
                "ticker": ticker,
                "company_name": name,
                "year": str(fr["year"]),
                "total_assets": fr["total_assets"],
                "total_liabilities": fr["total_liabilities"],
                "total_equity": fr["total_equity"],
                "issued_shares": fr["issued_shares"],
                "sales_revenue": fr["sales_revenue"],
                "cost_of_sales": fr["cost_of_sales"],
                "gross_profit": fr["gross_profit"],
                "net_income": fr["net_income"],
                "book_value_per_share": fr["book_value_per_share"],
                "roa": fr["roa"],
                "roe": fr["roe"],
                "rota": fr["rota"],
                "eps": fr["eps"],
                "pe_ratio": fr["pe_ratio"],
            }
        financials_added_per_ticker[ticker] = fin_added

    save_master(master)
    save_financials(financials)

    print(f"Master rows before: {before_count}, after: {len(master)}")
    for ticker, added in added_per_ticker.items():
        print(f"  {ticker}: +{added} new rows")

    print(f"Financials rows before: {financials_before_count}, "
          f"after: {len(financials)}")
    for ticker, added in financials_added_per_ticker.items():
        if added:
            print(f"  {ticker}: +{added} new/updated financial years")

    if failures:
        print(f"WARNING: failed to fetch/parse: {failures}")
        # Don't hard-fail the whole job over one flaky ticker; but do fail
        # the job if EVERYTHING failed (likely a site outage/change).
        if len(failures) == len(ticker_ids):
            print("ERROR: all tickers failed. Exiting with error status.")
            sys.exit(1)


if __name__ == "__main__":
    main()
