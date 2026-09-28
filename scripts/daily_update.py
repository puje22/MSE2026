"""
Daily incremental updater for MSE daily price data.

Price source priority:
1. open.mse.mn
2. members.mse.mn
3. mse.mn/todays-trade, only when its trading-session date is
   newer than the latest date already available from the first two.

The Today's Trade fallback uses the actual trading date returned by MSE,
not the computer's calendar date.

Run by .github/workflows/daily_update.yml on a daily cron schedule.
Safe to run manually too:
    python scripts/daily_update.py
"""

import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from scraper_lib import (  # noqa: E402
    fetch,
    parse_page,
    parse_financials,
    parse_dividend_announcements,
    fetch_open,
    parse_open_page,
    fetch_todays_trade,
    parse_todays_trade,
)


TICKER_IDS_FILE = os.path.join(
    os.path.dirname(__file__),
    "ticker_ids.json",
)

TICKER_IDS_OPEN_FILE = os.path.join(
    os.path.dirname(__file__),
    "ticker_ids_open.json",
)

MASTER_CSV = os.path.join(
    os.path.dirname(__file__),
    "..",
    "data",
    "mse_daily_prices.csv",
)

FINANCIALS_CSV = os.path.join(
    os.path.dirname(__file__),
    "..",
    "data",
    "mse_financials.csv",
)

DIVIDENDS_CSV = os.path.join(
    os.path.dirname(__file__),
    "..",
    "data",
    "mse_dividends.csv",
)


FIELDNAMES = [
    "ticker",
    "company_name",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "value",
]


FINANCIALS_FIELDNAMES = [
    "ticker",
    "company_name",
    "year",
    "total_assets",
    "total_liabilities",
    "total_equity",
    "issued_shares",
    "sales_revenue",
    "cost_of_sales",
    "gross_profit",
    "net_income",
    "book_value_per_share",
    "roa",
    "roe",
    "rota",
    "eps",
    "pe_ratio",
]


DIVIDENDS_FIELDNAMES = [
    "ticker",
    "company_name",
    "date",
    "headline",
]


def load_ticker_ids():
    with open(TICKER_IDS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_ticker_ids_open():
    """
    open.mse.mn IDs are optional.

    If the file does not exist yet, every ticker falls back to
    members.mse.mn price data.
    """
    if os.path.exists(TICKER_IDS_OPEN_FILE):
        with open(TICKER_IDS_OPEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    return {}


def load_master():
    """Return dict of (ticker, date) -> row dict."""
    rows = {}

    if os.path.exists(MASTER_CSV):
        with open(
            MASTER_CSV,
            "r",
            newline="",
            encoding="utf-8",
        ) as f:
            for row in csv.DictReader(f):
                rows[(row["ticker"], row["date"])] = row

    return rows


def save_master(rows):
    os.makedirs(
        os.path.dirname(MASTER_CSV),
        exist_ok=True,
    )

    ordered = sorted(
        rows.values(),
        key=lambda r: (r["ticker"], r["date"]),
    )

    with open(
        MASTER_CSV,
        "w",
        newline="",
        encoding="utf-8",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=FIELDNAMES,
        )

        writer.writeheader()

        for row in ordered:
            writer.writerow(row)


def load_financials():
    """Return dict of (ticker, year) -> row dict."""
    rows = {}

    if os.path.exists(FINANCIALS_CSV):
        with open(
            FINANCIALS_CSV,
            "r",
            newline="",
            encoding="utf-8",
        ) as f:
            for row in csv.DictReader(f):
                rows[(row["ticker"], row["year"])] = row

    return rows


def save_financials(rows):
    os.makedirs(
        os.path.dirname(FINANCIALS_CSV),
        exist_ok=True,
    )

    ordered = sorted(
        rows.values(),
        key=lambda r: (r["ticker"], r["year"]),
    )

    with open(
        FINANCIALS_CSV,
        "w",
        newline="",
        encoding="utf-8",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=FINANCIALS_FIELDNAMES,
        )

        writer.writeheader()

        for row in ordered:
            writer.writerow(row)


def load_dividends():
    """Return dict of (ticker, date) -> row dict."""
    rows = {}

    if os.path.exists(DIVIDENDS_CSV):
        with open(
            DIVIDENDS_CSV,
            "r",
            newline="",
            encoding="utf-8",
        ) as f:
            for row in csv.DictReader(f):
                rows[(row["ticker"], row["date"])] = row

    return rows


def save_dividends(rows):
    os.makedirs(
        os.path.dirname(DIVIDENDS_CSV),
        exist_ok=True,
    )

    ordered = sorted(
        rows.values(),
        key=lambda r: (r["ticker"], r["date"]),
        reverse=True,
    )

    with open(
        DIVIDENDS_CSV,
        "w",
        newline="",
        encoding="utf-8",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=DIVIDENDS_FIELDNAMES,
        )

        writer.writeheader()

        for row in ordered:
            writer.writerow(row)


def latest_master_date(master, ticker):
    """
    Return the latest YYYY-MM-DD date stored for a ticker.

    Returns None if no price history exists for the ticker.
    """
    dates = [
        date
        for (row_ticker, date) in master
        if row_ticker == ticker and date
    ]

    return max(dates) if dates else None


def main():
    ticker_ids = load_ticker_ids()
    ticker_ids_open = load_ticker_ids_open()

    master = load_master()
    financials = load_financials()
    dividends = load_dividends()

    before_count = len(master)
    financials_before_count = len(financials)
    dividends_before_count = len(dividends)

    failures = []
    added_per_ticker = {}
    financials_added_per_ticker = {}
    price_source_used = {}

    # ============================================================
    # PRIMARY PRICE SOURCES
    #
    # For every ticker:
    #   1. Fetch members.mse.mn
    #   2. Try open.mse.mn
    #   3. Prefer open.mse.mn when available
    #
    # Today's Trade is handled AFTER this loop as a fallback.
    # ============================================================

    for ticker, cid in sorted(ticker_ids.items()):

        html = fetch(cid)

        if html is None:
            failures.append(ticker)
            continue

        parsed = parse_page(html)

        if not parsed:
            failures.append(ticker)
            continue

        parsed_ticker, name, members_rows = parsed

        if parsed_ticker != ticker:
            print(
                f"NOTE: id {cid} now reports ticker "
                f"'{parsed_ticker}', expected '{ticker}'. "
                f"Using expected ticker."
            )

        # --------------------------------------------------------
        # Price data:
        # Prefer open.mse.mn.
        # Fall back to members.mse.mn.
        # --------------------------------------------------------

        price_rows = members_rows
        source = "members.mse.mn"

        open_cid = ticker_ids_open.get(ticker)

        if open_cid is not None:

            open_html = fetch_open(open_cid)

            if open_html is not None:

                open_parsed = parse_open_page(open_html)

                if open_parsed is not None:

                    open_ticker, open_rows = open_parsed

                    # open.mse.mn may still identify AARD by
                    # its historical ticker JIV.
                    if open_ticker == "JIV":
                        open_ticker = "AARD"

                    if (
                        open_ticker == ticker
                        and open_rows
                    ):
                        price_rows = open_rows
                        source = "open.mse.mn"

        price_source_used[ticker] = source

        added = 0

        for row in price_rows:

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

        # --------------------------------------------------------
        # Financials come from the SAME members.mse.mn page.
        # --------------------------------------------------------

        fin_rows = parse_financials(html)

        fin_added = 0

        for fr in fin_rows:

            key = (
                ticker,
                str(fr["year"]),
            )

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
                "book_value_per_share": fr[
                    "book_value_per_share"
                ],
                "roa": fr["roa"],
                "roe": fr["roe"],
                "rota": fr["rota"],
                "eps": fr["eps"],
                "pe_ratio": fr["pe_ratio"],
            }

        financials_added_per_ticker[ticker] = fin_added

        # --------------------------------------------------------
        # Dividend announcements also come from members.mse.mn.
        # --------------------------------------------------------

        div_rows = parse_dividend_announcements(html)

        for dr in div_rows:

            key = (
                ticker,
                dr["date"],
            )

            dividends[key] = {
                "ticker": ticker,
                "company_name": name,
                "date": dr["date"],
                "headline": dr["headline"],
            }

    # ============================================================
    # TODAY'S TRADE FALLBACK
    #
    # This is intentionally AFTER the normal source pass.
    #
    # MSE itself provides:
    #     date: 2026-09-25
    #     time: 18:59:06
    #
    # We use that date instead of datetime.today().
    #
    # If open/members already have that date, Today's Trade does
    # nothing.
    #
    # If open/members stop at an older date, Today's Trade fills
    # the missing newer trading session.
    # ============================================================

    try:

        print("\nChecking MSE Today's Trade...")

        todays_raw = fetch_todays_trade()

        todays_result = parse_todays_trade(
            todays_raw
        )

        todays_date = todays_result["date"]
        todays_time = todays_result["time"]
        todays_rows = todays_result["rows"]

        print(
            f"  MSE trading session: "
            f"{todays_date} {todays_time}"
        )

        print(
            f"  Securities returned: "
            f"{len(todays_rows)}"
        )

        todays_added = 0
        todays_skipped = 0

        for row in todays_rows:

            ticker = row.get("ticker")

            if not ticker:
                continue

            # Do not introduce unrelated securities into
            # the existing dataset.
            if ticker not in ticker_ids:
                continue

            latest_date = latest_master_date(
                master,
                ticker,
            )

            # ----------------------------------------------------
            # Already up to date.
            #
            # Example:
            # existing = 2026-09-25
            # today's   = 2026-09-25
            #
            # Do nothing.
            # ----------------------------------------------------

            if (
                latest_date is not None
                and todays_date <= latest_date
            ):
                todays_skipped += 1
                continue

            # ----------------------------------------------------
            # Today's Trade is newer.
            #
            # Example:
            # existing = 2026-09-24
            # today's   = 2026-09-25
            #
            # Add the new trading session.
            # ----------------------------------------------------

            key = (
                ticker,
                todays_date,
            )

            # Preserve the company name from the most recent
            # existing record when available.
            company_name = ticker

            if latest_date is not None:

                previous_key = (
                    ticker,
                    latest_date,
                )

                previous_row = master.get(
                    previous_key
                )

                if previous_row:
                    company_name = previous_row.get(
                        "company_name",
                        ticker,
                    )

            master[key] = {
                "ticker": ticker,
                "company_name": company_name,
                "date": todays_date,

                "open": row["open"],
                "high": row["high"],
                "low": row["low"],

                # IMPORTANT:
                # ClosingPrice from MSE is the daily close.
                "close": row["close"],

                "volume": row["volume"],

                # Today's Trade calls this Turnover.
                # Our master CSV calls the field "value".
                "value": row["turnover"],
            }

            todays_added += 1

            price_source_used[ticker] = (
                "mse.mn/todays-trade"
            )

        print(
            f"  Today's Trade: "
            f"+{todays_added} new rows, "
            f"{todays_skipped} already up to date"
        )

    except Exception as exc:

        # Today's Trade is only a fallback.
        # If it fails, the normal open/members data
        # remains valid.
        print(
            f"WARNING: Today's Trade fallback failed: "
            f"{exc}"
        )

    # ============================================================
    # SAVE
    # ============================================================

    save_master(master)
    save_financials(financials)
    save_dividends(dividends)

    print(
        f"\nMaster rows before: {before_count}, "
        f"after: {len(master)}"
    )

    for ticker, added in added_per_ticker.items():

        src = price_source_used.get(
            ticker,
            "?",
        )

        print(
            f"  {ticker}: "
            f"+{added} new rows "
            f"(price source: {src})"
        )

    print(
        f"Financials rows before: "
        f"{financials_before_count}, "
        f"after: {len(financials)}"
    )

    for ticker, added in financials_added_per_ticker.items():

        if added:
            print(
                f"  {ticker}: "
                f"+{added} new/updated financial years"
            )

    print(
        f"Dividend announcement rows before: "
        f"{dividends_before_count}, "
        f"after: {len(dividends)}"
    )

    if failures:

        print(
            f"WARNING: failed to fetch/parse: "
            f"{failures}"
        )

        # Don't hard-fail the whole job over one flaky ticker;
        # fail only if everything failed.
        if len(failures) == len(ticker_ids):

            print(
                "ERROR: all tickers failed. "
                "Exiting with error status."
            )

            sys.exit(1)


if __name__ == "__main__":
    main()
