#!/usr/bin/env python3
"""One-time/resumable historical MSE EOD order-book backfill.

Run from repository root:
    python scripts/backfill_orderbook.py

Optional test/limited run:
    python scripts/backfill_orderbook.py --max-dates 100

Progress is checkpointed to data/mse_daily_orderbook.csv and
 data/mse_orderbook_checked_dates.csv, so rerunning resumes automatically.
"""
import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from daily_update import (  # noqa: E402
    ULAANBAATAR_TZ,
    fetch_daily_orderbook,
    load_master,
    load_orderbook,
    load_orderbook_checked_dates,
    load_ticker_ids,
    parse_daily_orderbook,
    save_orderbook,
    save_orderbook_checked_dates,
)


def checkpoint(orderbook, checked):
    save_orderbook(orderbook)
    save_orderbook_checked_dates(checked)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--max-dates", type=int, default=None,
        help="Maximum unchecked dates to process this run; default = all remaining.",
    )
    parser.add_argument(
        "--checkpoint-every", type=int, default=25,
        help="Persist progress after this many processed dates (default: 25).",
    )
    args = parser.parse_args()

    ticker_ids = load_ticker_ids()
    master = load_master()
    orderbook = load_orderbook()
    checked = load_orderbook_checked_dates()

    # Bootstrap from any snapshots written before the checked-date ledger existed.
    for _, stored_date in orderbook:
        checked.setdefault(stored_date, "existing_orderbook")

    price_dates = sorted(
        {date for (ticker, date) in master if ticker in ticker_ids and date},
        reverse=True,
    )
    pending = [date for date in price_dates if date not in checked]
    if args.max_dates is not None:
        pending = pending[: max(args.max_dates, 0)]

    print(f"Historical order-book backfill: {len(pending)} dates to process this run.")
    print(f"Existing order-book rows: {len(orderbook)}; checked dates: {len(checked)}")

    today_ub = datetime.datetime.now(ULAANBAATAR_TZ).date().isoformat()
    processed = with_data = no_data = nonweekday = failed = 0

    for date in pending:
        # Weekend dates can occur in the price master because of source anomalies;
        # they are conclusively not normal MSE trading sessions.
        try:
            weekday = datetime.date.fromisoformat(date).weekday()
        except ValueError:
            failed += 1
            print(f"  WARNING {date}: invalid date; left unchecked")
            continue

        if weekday >= 5:
            checked[date] = "non_weekday"
            nonweekday += 1
            processed += 1
            print(f"  {date}: non-weekday; marked checked")
        else:
            try:
                raw = fetch_daily_orderbook(date)
                if raw is None:
                    raise ValueError("empty response after retries")
                try:
                    rows = parse_daily_orderbook(raw, date)
                except ValueError as exc:
                    if date < today_ub and "Could not find company data array" in str(exc):
                        checked[date] = "no_data"
                        no_data += 1
                        processed += 1
                        print(f"  {date}: no historical order-book data; marked checked")
                        rows = None
                    else:
                        raise

                if rows is not None:
                    target_rows = [r for r in rows if r["ticker"] in ticker_ids]
                    if target_rows:
                        for row in target_rows:
                            orderbook[(row["ticker"], date)] = row
                        checked[date] = "historical_data"
                        with_data += 1
                        print(f"  {date}: {len(target_rows)} target snapshots")
                    else:
                        checked[date] = "no_target_rows"
                        no_data += 1
                        print(f"  {date}: no target snapshots; marked checked")
                    processed += 1
            except Exception as exc:
                # Do not mark transient/request/parser failures checked.
                failed += 1
                print(f"  WARNING {date}: {exc}; left unchecked for retry")

        if processed and processed % max(args.checkpoint_every, 1) == 0:
            checkpoint(orderbook, checked)
            print(f"  CHECKPOINT: {processed} dates processed, {len(orderbook)} rows saved")

    checkpoint(orderbook, checked)
    remaining = sum(1 for date in price_dates if date not in checked)
    print("\nBackfill complete for this run.")
    print(f"  processed: {processed}")
    print(f"  dates with data: {with_data}")
    print(f"  no-data/no-target: {no_data}")
    print(f"  non-weekday: {nonweekday}")
    print(f"  retryable failures: {failed}")
    print(f"  order-book rows now: {len(orderbook)}")
    print(f"  dates still unchecked: {remaining}")


if __name__ == "__main__":
    main()
