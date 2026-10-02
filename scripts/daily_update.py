"""
Daily incremental updater for MSE daily price data.

Price source priority:

1. open.mse.mn
2. members.mse.mn

3. mse.mn/todays-trade, only when its trading-session date is
newer than the latest date already available from the first two.

The Today's Trade fallback tries to use the actual trading date/time
MSE returns. If that metadata can't be found in a given response, it
falls back to the current Ulaanbaatar date/time -- and, either way,
each row is checked against its own PreviousClose against what we
already have on file before being trusted, so a wrong date guess
can't corrupt the series.

Run by .github/workflows/daily_update.yml on a daily cron schedule.

Safe to run manually too:
    python scripts/daily_update.py
"""
import csv
import datetime
import json
import os
import re
import sys
import requests

sys.path.insert(0, os.path.dirname(__file__))

from scraper_lib import (  # noqa: E402
    fetch,
    parse_page,
    parse_financials,
    parse_dividend_announcements,
    fetch_open,
    parse_open_page,
)

# ================================================================
# MSE TODAY'S TRADE
# ================================================================
# This endpoint is a Next.js Server Action.  Its response is RSC
# text, not ordinary JSON.  The exact RSC chunk numbering can vary,
# so do not assume that chunk "1:" is always the trading array.

TODAYS_TRADE_URL = "https://mse.mn/todays-trade"
TODAYS_TRADE_NEXT_ACTION = "6d867ebd99fb6edef2f9537b22668cd0c00a71c2"
TODAYS_TRADE_ROUTER_STATE = (
    '["",{"children":["(navbar)",{"children":["(trade)",'
    '{"children":["todays-trade",{"children":["__PAGE__",{},'
    '"/todays-trade","refresh"]}]}]}]},null,null,true]'
)

TODAYS_TRADE_HEADERS = {
    "Accept": "text/x-component",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "text/plain;charset=UTF-8",
    "Next-Action": TODAYS_TRADE_NEXT_ACTION,
    "Next-Router-State-Tree": TODAYS_TRADE_ROUTER_STATE,
    "Origin": "https://mse.mn",
    "Referer": "https://mse.mn/todays-trade",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36 OPR/135.0.0.0"
    ),
}

TODAYS_TRADE_PAYLOAD = json.dumps(
    [
        {
            "url": "tradingStatus1",
            "parameter": "?lang=mn",
            "config": {"hasToken": False},
        }
    ],
    separators=(",", ":"),
)

# Mongolia is UTC+8 year-round (no DST since 2017). A fixed offset is
# used instead of zoneinfo, which needs a tzdata package not always
# present on Windows.
ULAANBAATAR_TZ = datetime.timezone(datetime.timedelta(hours=8))

# Use Today's Trade only after the official market close.
TODAYS_TRADE_CLOSE_TIME = datetime.time(13, 5)


class MarketStillOpen(Exception):
    """Raised when the daily-close fallback is called before 13:05 UB time."""


def fetch_todays_trade():
    """Fetch the raw RSC response from MSE Today's Trade."""
    response = requests.post(
        TODAYS_TRADE_URL,
        headers=TODAYS_TRADE_HEADERS,
        data=TODAYS_TRADE_PAYLOAD,
        timeout=30,
    )

    print("\n--- TODAY'S TRADE DEBUG ---")
    print("HTTP status:", response.status_code)
    print("Content-Type:", response.headers.get("Content-Type"))
    print("Response length:", len(response.text))
    print("Response preview:")
    print(response.text[:5000])
    print("--- END DEBUG ---\n")

    response.raise_for_status()
    return response.text


def parse_todays_trade_number(value):
    """Convert MSE numeric strings such as '12,345.67' to float."""
    if value is None or value == "":
        return None

    if isinstance(value, (int, float)):
        return float(value)

    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def parse_todays_trade(raw):
    """
    Parse MSE's Next.js RSC Today's Trade response.

    Important: the response is NOT one normal JSON document.  It contains
    several RSC chunks.  Explicit date/time metadata is a nice-to-have,
    not a hard requirement -- if it can't be found (the RSC chunk format
    has changed before, and will again), we fall back to the current
    Ulaanbaatar date/time, since this endpoint represents "today's"
    session by definition. The real protection against a wrong date
    happens later in main(), where each row's PreviousClose is checked
    against what we already have on file before it's trusted.
    """
    if not raw:
        raise ValueError("Empty MSE Today's Trade response")

    # ------------------------------------------------------------
    # Trading session date/time (optional -- see docstring above).
    # ------------------------------------------------------------
    meta_match = re.search(
        r"(?:['\"]?date['\"]?\s*:\s*['\"]?)(\d{4}-\d{2}-\d{2})(?:['\"]?)"
        r".*?"
        r"(?:['\"]?time['\"]?\s*:\s*['\"]?)(\d{2}:\d{2}:\d{2})(?:['\"]?)",
        raw,
        flags=re.DOTALL,
    )

    if meta_match:
        trading_date = meta_match.group(1)
        trading_time = meta_match.group(2)
    else:
        now = datetime.datetime.now(ULAANBAATAR_TZ)
        trading_date = now.strftime("%Y-%m-%d")
        trading_time = now.strftime("%H:%M:%S")
        print(
            "NOTE: no explicit date/time metadata found in MSE Today's "
            f"Trade response; using current Ulaanbaatar time as a guess: "
            f"{trading_date} {trading_time}. Each row's PreviousClose "
            "will be checked against stored data before being trusted."
        )

    # ------------------------------------------------------------
    # Locate the trading array.
    # ------------------------------------------------------------
    # We use JSONDecoder.raw_decode instead of a greedy regex.  This lets
    # us parse a very large array safely even when it contains many records.
    decoder = json.JSONDecoder()
    trading_data = None

    # Every RSC chunk starts with something like "1:" or "2:".
    # Find chunk positions and try to decode a JSON value immediately
    # following the colon.  We only accept an array containing dictionaries
    # with companySymbol, which uniquely identifies the Today's Trade table.
    for match in re.finditer(r"(?m)^\d+:", raw):
        start = match.end()

        # RSC may have whitespace before the JSON value.
        while start < len(raw) and raw[start].isspace():
            start += 1

        if start >= len(raw) or raw[start] != "[":
            continue

        try:
            candidate, _ = decoder.raw_decode(raw[start:])
        except json.JSONDecodeError:
            continue

        if not isinstance(candidate, list) or not candidate:
            continue

        if any(
            isinstance(item, dict) and "companySymbol" in item
            for item in candidate
        ):
            trading_data = candidate
            break

    # Fallback: some RSC formatting may not put every chunk on its own line.
    if trading_data is None:
        for match in re.finditer(r"\[\s*\{\s*\"companySymbol\"", raw):
            try:
                candidate, _ = decoder.raw_decode(raw[match.start():])
            except json.JSONDecodeError:
                continue

            if isinstance(candidate, list) and candidate:
                trading_data = candidate
                break

    if trading_data is None:
        raise ValueError(
            "Could not find trading data array in MSE Today's Trade response"
        )

    rows = []

    for item in trading_data:
        if not isinstance(item, dict):
            continue

        ticker = item.get("companySymbol")
        if not ticker:
            continue

        rows.append(
            {
                "ticker": str(ticker).strip(),
                "code": item.get("code"),
                "open": parse_todays_trade_number(
                    item.get("OpeningPrice")
                ),
                "high": parse_todays_trade_number(
                    item.get("HighPrice")
                ),
                "low": parse_todays_trade_number(
                    item.get("LowPrice")
                ),
                # IMPORTANT: ClosingPrice is the daily close.
                "close": parse_todays_trade_number(
                    item.get("ClosingPrice")
                ),
                "last": parse_todays_trade_number(
                    item.get("LastTradedPrice")
                ),
                "previous_close": parse_todays_trade_number(
                    item.get("PreviousClose")
                ),
                "change": item.get("Changes"),
                "change_pct": item.get("changePercentage"),
                "volume": parse_todays_trade_number(
                    item.get("Volume")
                ),
                "turnover": parse_todays_trade_number(
                    item.get("Turnover")
                ),
                "buy_order_qty": parse_todays_trade_number(
                    item.get("BuyOrderQty")
                ),
                "highest_bid": parse_todays_trade_number(
                    item.get("HighestBidPrice")
                ),
                "sell_order_qty": parse_todays_trade_number(
                    item.get("SellOrderQty")
                ),
                "lowest_offer": parse_todays_trade_number(
                    item.get("LowestOfferPrice")
                ),
            }
        )

    if not rows:
        raise ValueError(
            "MSE Today's Trade response contained no company rows"
        )

    return {
        "date": trading_date,
        "time": trading_time,
        "rows": rows,
    }


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
    # If open/members already have the latest session for a ticker,
    # Today's Trade does nothing for that ticker.
    #
    # If open/members stop at an older date, Today's Trade can fill
    # the missing newer trading session -- but only after each row's
    # PreviousClose is checked against what we already have on file.
    # This protects against inserting a row under a wrong/guessed
    # date, which matters now that date/time metadata is optional.
    #
    # Also repairs rows previously written with a zero/missing close
    # (e.g. from a pre-close run) once a real ClosingPrice is available.
    # ============================================================

    try:

        print("\nChecking MSE Today's Trade...")

        now_ub = datetime.datetime.now(ULAANBAATAR_TZ)
        if now_ub.time() < TODAYS_TRADE_CLOSE_TIME:
            raise MarketStillOpen(
                f"MSE market has not completed closing yet "
                f"({now_ub:%H:%M} Ulaanbaatar time). "
                "Today's Trade fallback skipped."
            )

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
        todays_rejected = 0
        todays_repaired = 0  # FIX: was missing, caused UnboundLocalError

        for row in todays_rows:

            ticker = row.get("ticker")

            if not ticker:
                continue

            # Do not introduce unrelated securities into
            # the existing dataset.
            if ticker not in ticker_ids:
                continue

            # Never write an intraday/unfinished ClosingPrice of 0.
            # LastTradedPrice is deliberately NOT used as a substitute.
            incoming_close = row.get("close")
            if incoming_close is None or incoming_close <= 0:
                print(
                    f"  SKIPPING {ticker}: ClosingPrice={incoming_close}; "
                    "official close is not available."
                )
                todays_rejected += 1
                continue

            # Repair a zero close written by an earlier pre-close run.
            existing_today = master.get((ticker, todays_date))
            if existing_today is not None:
                try:
                    existing_close = float(existing_today.get("close") or 0)
                except (TypeError, ValueError):
                    existing_close = 0.0

                if existing_close <= 0:
                    existing_today.update({
                        "open": row["open"],
                        "high": row["high"],
                        "low": row["low"],
                        "close": incoming_close,
                        "volume": row["volume"],
                        "value": row["turnover"],
                    })
                    todays_repaired += 1
                    price_source_used[ticker] = "mse.mn/todays-trade"
                    print(
                        f"  REPAIRED {ticker} {todays_date}: "
                        f"close {existing_close} -> {incoming_close}"
                    )
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
            # Safety check: if we already have a prior close on
            # file, this row's PreviousClose should match it
            # almost exactly. If it doesn't, either the (possibly
            # guessed) date is wrong or this isn't really the next
            # session -- skip rather than risk a bad row.
            # ----------------------------------------------------

            if latest_date is not None:

                prev_row = master.get((ticker, latest_date))
                stored_close = (
                    float(prev_row["close"])
                    if prev_row and prev_row.get("close") not in (None, "")
                    else None
                )
                reported_prev_close = row.get("previous_close")

                if (
                    stored_close is not None
                    and reported_prev_close is not None
                    and abs(stored_close - reported_prev_close)
                        > 0.01 * max(abs(stored_close), 1)
                ):
                    print(
                        f"  SKIPPING {ticker}: Today's Trade "
                        f"PreviousClose ({reported_prev_close}) doesn't "
                        f"match our stored close for {latest_date} "
                        f"({stored_close}) -- date guess is likely "
                        f"wrong, not inserting."
                    )
                    todays_rejected += 1
                    continue

            # ----------------------------------------------------
            # Today's Trade is newer AND passed the continuity
            # check (or there was nothing to check against).
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
            f"{todays_repaired} zero-close rows repaired, "
            f"{todays_skipped} already up to date, "
            f"{todays_rejected} rejected/skipped"
        )

    except MarketStillOpen as exc:
        print(f"  {exc}")
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