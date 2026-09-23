"""
Shared parsing logic for scraping old.mse.mn company pages.

This is the validated parser from the original full-range crawl (confirmed
working against real MSE data as of Sep 2026) — kept here so both the
one-time ticker-map builder and the daily updater use identical logic.
"""

import re
import time
import requests

BASE_URL = "https://members.mse.mn/en/company/{id}"
BASE_URL_OPEN = "https://open.mse.mn/securities/{id}/tab/tradeinfo"
TIMEOUT = 20
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; research-scraper/1.0)"
}

# NOTE: internal company IDs differ between sources. members.mse.mn IDs are
# NOT the same as old.mse.mn IDs (e.g. TTL was 458 on old.mse.mn, 510 on
# members.mse.mn). open.mse.mn appears to reuse the OLD old.mse.mn ID scheme
# (TTL is 458 there too) but don't assume this holds for every ticker —
# always verify with find_ticker_ids_open.py rather than reusing IDs blindly.

SECTION_MARKER = "Trading history of Block Trade"

HEADER_RE = re.compile(r"([A-Za-z0-9][\w \-\.,'&]{1,58}?)\s*\(([A-Z0-9]{2,10})\)")

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

# open.mse.mn's ISIN reliably embeds the ticker: "MN00TTL04580" -> "TTL"
ISIN_TICKER_RE = re.compile(r"ISIN\s+MN00([A-Z]+)\d+")

# open.mse.mn row format is DIFFERENT from members.mse.mn's:
# # Date Open Close Low-High(as "low - high") Volume Value Transactions
# e.g. "1 2026-09-22 59,900.00 60,000.00 59,650.00 - 60,000.00 397 23,785,300.00 30"
OPEN_ROW_RE = re.compile(
    r"(\d+)\s+"                          # row number
    r"(\d{4}-\d{2}-\d{2})\s+"            # date
    r"([\d,]+\.\d{2})\s+"                # open
    r"([\d,]+\.\d{2})\s+"                # close
    r"([\d,]+\.\d{2})\s*-\s*"            # low (first half of range)
    r"([\d,]+\.\d{2})\s+"                # high (second half of range)
    r"([\d,]+)\s+"                       # volume
    r"([\d,]+\.\d{2})\s+"                # value
    r"(\d+)"                             # transaction count
)


def num(s):
    return float(s.replace(",", ""))


def fetch_url(url, delay=0.3, retries=3, retry_backoff=2.0):
    last_exc = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            time.sleep(delay)
            return resp.text
        except requests.RequestException as e:
            last_exc = e
            if attempt < retries - 1:
                time.sleep(retry_backoff * (attempt + 1))  # 2s, 4s, ...
    # All retries exhausted
    return None


def fetch(company_id, delay=0.3, retries=3, retry_backoff=2.0):
    """Fetch a members.mse.mn company page (used for company name, financials, dividends)."""
    return fetch_url(BASE_URL.format(id=company_id), delay, retries, retry_backoff)


def fetch_open(company_id, delay=0.3, retries=3, retry_backoff=2.0):
    """Fetch an open.mse.mn tradeinfo page (used for current, non-lagging price history)."""
    return fetch_url(BASE_URL_OPEN.format(id=company_id), delay, retries, retry_backoff)


def parse_open_page(html):
    """
    Parse an open.mse.mn /securities/{id}/tab/tradeinfo page.
    Returns (ticker, rows) or None if unparseable. rows is a list of
    {date, open, high, low, close, volume, value, transactions} dicts,
    newest first (matching the page's own order).
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)

    m = ISIN_TICKER_RE.search(text)
    if not m:
        return None
    ticker = m.group(1)

    rows = []
    for rm in OPEN_ROW_RE.finditer(text):
        _, date, open_, close, low, high, vol, val, txns = rm.groups()
        rows.append({
            "date": date,
            "open": num(open_),
            "high": num(high),
            "low": num(low),
            "close": num(close),
            "volume": num(vol),
            "value": num(val),
            "transactions": int(txns),
        })
    if not rows:
        return None
    return ticker, rows


FINANCIALS_MARKER = "Summary of Financials"

YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

FINANCIAL_BLOCK_RE = re.compile(
    r"Balance sheet\s+"
    r"Total assets\s+([\d,]+)\s+"
    r"Total liabilities\s+([\d,]+)\s+"
    r"Total owner`s equity\s+([\d,]+)\s+"
    r"Issued shares\s+([\d,]+)\s+"
    r"Income statement\s+"
    r"Sales revenue\s+([\d,]+)\s+"
    r"Cost of sales\s+([\d,]+)\s+"
    r"Gross profit\s+([\d,]+)\s+"
    r"Net income\s+([\d,]+)\s+"
    r"Book value per share\s+([\d,]+)\s+"
    r"Ratios\s+"
    r"Return on Assets /ROA/\s*([\d.]+)?\s*"
    r"Return on Equity /ROE/\s*([\d.]+)?\s*"
    r"Return on Total Assets /ROTA/\s*([\d.]+)?\s*"
    r"Earnings per share /EPS/\s+([\d.\-]+)\s+"
    r"Price earnings ratio \(P/E Ratio\)\s+([\d.\-]+)"
)


def _optional_num(s):
    return num(s) if s else None


def parse_financials(html):
    """
    Return a list of dicts, one per fiscal year, newest first:
        {year, total_assets, total_liabilities, total_equity, issued_shares,
         sales_revenue, cost_of_sales, gross_profit, net_income,
         book_value_per_share, roa, roe, rota, eps, pe_ratio}
    Years with no filed data (all-zero block) are skipped entirely.
    Returns [] if the page has no financials section.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)

    idx = text.find(FINANCIALS_MARKER)
    if idx == -1:
        return []
    section = text[idx:]

    # Years list sits between "Financial Report" and the first "Balance sheet"
    report_idx = section.find("Financial Report")
    first_block_idx = section.find("Balance sheet")
    if report_idx == -1 or first_block_idx == -1:
        return []
    years_text = section[report_idx + len("Financial Report"):first_block_idx]
    years = [int(m.group(0)) for m in YEAR_RE.finditer(years_text)]

    blocks = list(FINANCIAL_BLOCK_RE.finditer(section))

    results = []
    for year, m in zip(years, blocks):
        (total_assets, total_liab, total_equity, issued_shares,
         sales_rev, cost_of_sales, gross_profit, net_income, bvps,
         roa, roe, rota, eps, pe) = m.groups()

        total_assets_v = num(total_assets)
        net_income_v = num(net_income)
        eps_v = num(eps)
        # An all-zero block means "no data filed for this year", not a real zero
        if total_assets_v == 0 and net_income_v == 0 and eps_v == 0:
            continue

        results.append({
            "year": year,
            "total_assets": total_assets_v,
            "total_liabilities": num(total_liab),
            "total_equity": num(total_equity),
            "issued_shares": num(issued_shares),
            "sales_revenue": num(sales_rev),
            "cost_of_sales": num(cost_of_sales),
            "gross_profit": num(gross_profit),
            "net_income": net_income_v,
            "book_value_per_share": num(bvps),
            "roa": _optional_num(roa),
            "roe": _optional_num(roe),
            "rota": _optional_num(rota),
            "eps": eps_v,
            "pe_ratio": num(pe),
        })
    return results


ANNOUNCEMENT_RE = re.compile(
    r"(\d+)\s+([A-Z][A-Za-z0-9 '\"\u201c\u201d,\.\-]{5,150}?)\s+"
    r"(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}"
)


def parse_dividend_announcements(html):
    """
    Best-effort extraction of dividend-related announcement headlines and
    dates from the page's news/announcements feed. Returns a list of
    {headline, date} dicts, newest first. This gives DECLARATION DATES only —
    the announcement text on MSE's site has the actual per-share amount,
    which isn't available here in structured form.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)

    results = []
    for m in ANNOUNCEMENT_RE.finditer(text):
        _, headline, date = m.groups()
        if "DIVIDEND" in headline.upper():
            results.append({"headline": headline.strip(), "date": date})
    return results


def parse_page(html):
    """Return (ticker, company_name, rows) or None if not a valid company page."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)

    idx = text.find(SECTION_MARKER)
    if idx == -1:
        return None
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
