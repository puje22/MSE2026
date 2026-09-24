"""
Shared parsing logic for scraping MSE company pages.

Supports:
- members.mse.mn company pages
- open.mse.mn tradeinfo pages

The open.mse.mn parser uses the structured `data-trading-histories`
JSON embedded in the page rather than relying on rendered table text.
"""

import json
import re
import time

import requests


BASE_URL = "https://members.mse.mn/en/company/{id}"
BASE_URL_OPEN = "https://open.mse.mn/securities/{id}/tab/tradeinfo"

TIMEOUT = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; research-scraper/1.0)"
}


# ============================================================
# MEMBERS.MSE.MN PARSING
# ============================================================

SECTION_MARKER = "Trading history of Block Trade"

HEADER_RE = re.compile(
    r"([A-Za-z0-9][\w \-\.,'&]{1,58}?)\s*\(([A-Z0-9]{2,10})\)"
)

ROW_RE = re.compile(
    r"(\d+)\s+"
    r"([\d,]+(?:\.\d+)?)\s+"
    r"([\d,]+(?:\.\d+)?)\s+"
    r"([\d,]+(?:\.\d+)?)\s+"
    r"([\d,]+(?:\.\d+)?)\s+"
    r"([\d,]+(?:\.\d+)?)\s+"
    r"([\d,]+(?:\.\d+)?)\s+"
    r"(\d{4}-\d{2}-\d{2})"
)


# ============================================================
# OPEN.MSE.MN
# ============================================================

# Kept for compatibility with any code that imports this regex.
ISIN_TICKER_RE = re.compile(
    r"ISIN\s+MN0([A-Z]+)\d+"
)

# Kept for compatibility with existing code/tests.
OPEN_ROW_RE = re.compile(
    r"(\d+)\s+"
    r"(\d{4}-\d{2}-\d{2})\s+"
    r"([\d,]+\.\d{2})\s+"
    r"([\d,]+\.\d{2})\s+"
    r"([\d,]+\.\d{2})\s*-\s*"
    r"([\d,]+\.\d{2})\s+"
    r"([\d,]+)\s+"
    r"([\d,]+\.\d{2})\s+"
    r"(\d+)"
)


# ============================================================
# FINANCIALS
# ============================================================

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


# ============================================================
# ANNOUNCEMENTS / DIVIDENDS
# ============================================================

ANNOUNCEMENT_RE = re.compile(
    r"(\d+)\s+([A-Z][A-Za-z0-9 '\"\u201c\u201d,\.\-]{5,150}?)\s+"
    r"(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}"
)


# ============================================================
# HELPERS
# ============================================================

def num(s):
    """Convert a numeric string to float."""
    return float(str(s).replace(",", ""))


def _optional_num(s):
    return num(s) if s else None


# ============================================================
# FETCHING
# ============================================================

def fetch_url(url, delay=0.3, retries=3, retry_backoff=2.0):
    last_exc = None

    for attempt in range(retries):
        try:
            resp = requests.get(
                url,
                headers=HEADERS,
                timeout=TIMEOUT,
            )

            resp.raise_for_status()

            time.sleep(delay)

            return resp.text

        except requests.RequestException as e:
            last_exc = e

            if attempt < retries - 1:
                time.sleep(
                    retry_backoff * (attempt + 1)
                )

    return None


def fetch(company_id, delay=0.3, retries=3, retry_backoff=2.0):
    """
    Fetch a members.mse.mn company page.

    Used for:
    - company name
    - financials
    - dividends
    """
    return fetch_url(
        BASE_URL.format(id=company_id),
        delay,
        retries,
        retry_backoff,
    )


def fetch_open(company_id, delay=0.3, retries=3, retry_backoff=2.0):
    """
    Fetch an open.mse.mn tradeinfo page.

    Used for current, non-lagging price history.
    """
    return fetch_url(
        BASE_URL_OPEN.format(id=company_id),
        delay,
        retries,
        retry_backoff,
    )


# ============================================================
# OPEN.MSE.MN TRADE HISTORY PARSER
# ============================================================

def parse_open_page(html):
    """
    Parse an open.mse.mn /securities/{id}/tab/tradeinfo page.

    Returns:
        (ticker, rows)

    or:
        None

    rows contain:

        {
            "date": str,
            "open": float,
            "high": float,
            "low": float,
            "close": float,
            "volume": float,
            "value": float,
            "transactions": int
        }

    Rows are sorted newest first.
    """

    if not html:
        return None

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")

    # --------------------------------------------------------
    # Find structured historical data
    # --------------------------------------------------------

    chart = soup.find(
        "div",
        id="chart-data",
    )

    if not chart:
        return None

    raw = chart.get(
        "data-trading-histories"
    )

    if not raw:
        return None

    # --------------------------------------------------------
    # Decode JSON
    # --------------------------------------------------------

    try:
        data = json.loads(raw)

    except (
        json.JSONDecodeError,
        TypeError,
    ):
        return None

    if not isinstance(data, list) or not data:
        return None

    # --------------------------------------------------------
    # Extract ticker
    #
    # Example:
    #
    # CUMN-O-0000 -> CUMN
    # GLMT-O-0000 -> GLMT
    # KHAN-O-0000 -> KHAN
    # --------------------------------------------------------

    ticker = None

    for item in data:

        if not isinstance(item, dict):
            continue

        symbol = item.get("Symbol")

        if symbol:
            ticker = symbol.split("-")[0].strip()

            if ticker:
                break

    # --------------------------------------------------------
    # Fallback: extract ticker from ISIN if necessary
    # --------------------------------------------------------

    if not ticker:

        text = soup.get_text(
            " ",
            strip=True,
        )

        m = ISIN_TICKER_RE.search(text)

        if m:
            ticker = m.group(1)

    if not ticker:
        return None

    # --------------------------------------------------------
    # Convert structured MSE records into our standard format
    # --------------------------------------------------------

    rows = []

    for item in data:

        if not isinstance(item, dict):
            continue

        date = item.get("dates")

        if not date:
            continue

        try:
            open_price = float(
                item.get("OpeningPrice") or 0
            )

            close_price = float(
                item.get("ClosingPrice") or 0
            )

            high_price = float(
                item.get("HighPrice") or 0
            )

            low_price = float(
                item.get("LowPrice") or 0
            )

            volume = float(
                item.get("Volume") or 0
            )

            turnover = float(
                item.get("Turnover") or 0
            )

            trades = int(
                item.get("Trades") or 0
            )

        except (
            TypeError,
            ValueError,
        ):
            continue

        rows.append(
            {
                "date": date,
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": volume,
                "value": turnover,
                "transactions": trades,
            }
        )

    if not rows:
        return None

    # --------------------------------------------------------
    # Ensure newest first
    # --------------------------------------------------------

    rows.sort(
        key=lambda x: x["date"],
        reverse=True,
    )

    return ticker, rows


# ============================================================
# FINANCIAL PARSER
# ============================================================

def parse_financials(html):
    """
    Return a list of dicts, one per fiscal year, newest first:

        {
            year,
            total_assets,
            total_liabilities,
            total_equity,
            issued_shares,
            sales_revenue,
            cost_of_sales,
            gross_profit,
            net_income,
            book_value_per_share,
            roa,
            roe,
            rota,
            eps,
            pe_ratio
        }

    Years with no filed data are skipped.
    Returns [] if the page has no financials section.
    """

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(
        html,
        "lxml",
    )

    text = soup.get_text(
        " ",
        strip=True,
    )

    idx = text.find(
        FINANCIALS_MARKER
    )

    if idx == -1:
        return []

    section = text[idx:]

    report_idx = section.find(
        "Financial Report"
    )

    first_block_idx = section.find(
        "Balance sheet"
    )

    if (
        report_idx == -1
        or first_block_idx == -1
    ):
        return []

    years_text = section[
        report_idx
        + len("Financial Report"):
        first_block_idx
    ]

    years = [
        int(m.group(0))
        for m in YEAR_RE.finditer(
            years_text
        )
    ]

    blocks = list(
        FINANCIAL_BLOCK_RE.finditer(
            section
        )
    )

    results = []

    for year, m in zip(
        years,
        blocks,
    ):

        (
            total_assets,
            total_liab,
            total_equity,
            issued_shares,
            sales_rev,
            cost_of_sales,
            gross_profit,
            net_income,
            bvps,
            roa,
            roe,
            rota,
            eps,
            pe,
        ) = m.groups()

        total_assets_v = num(
            total_assets
        )

        net_income_v = num(
            net_income
        )

        eps_v = num(eps)

        # An all-zero block means no data filed.
        if (
            total_assets_v == 0
            and net_income_v == 0
            and eps_v == 0
        ):
            continue

        results.append(
            {
                "year": year,
                "total_assets": total_assets_v,
                "total_liabilities": num(
                    total_liab
                ),
                "total_equity": num(
                    total_equity
                ),
                "issued_shares": num(
                    issued_shares
                ),
                "sales_revenue": num(
                    sales_rev
                ),
                "cost_of_sales": num(
                    cost_of_sales
                ),
                "gross_profit": num(
                    gross_profit
                ),
                "net_income": net_income_v,
                "book_value_per_share": num(
                    bvps
                ),
                "roa": _optional_num(roa),
                "roe": _optional_num(roe),
                "rota": _optional_num(rota),
                "eps": eps_v,
                "pe_ratio": num(pe),
            }
        )

    return results


# ============================================================
# DIVIDEND ANNOUNCEMENTS
# ============================================================

def parse_dividend_announcements(html):
    """
    Extract dividend-related announcement headlines and dates.

    Returns declaration dates only.
    """

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(
        html,
        "lxml",
    )

    text = soup.get_text(
        " ",
        strip=True,
    )

    results = []

    for m in ANNOUNCEMENT_RE.finditer(
        text
    ):

        _, headline, date = m.groups()

        if "DIVIDEND" in headline.upper():

            results.append(
                {
                    "headline": headline.strip(),
                    "date": date,
                }
            )

    return results


# ============================================================
# MEMBERS.MSE.MN COMPANY PAGE PARSER
# ============================================================

def parse_page(html):
    """
    Return:

        (ticker, company_name, rows)

    or None if not a valid company page.
    """

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(
        html,
        "lxml",
    )

    text = soup.get_text(
        " ",
        strip=True,
    )

    idx = text.find(
        SECTION_MARKER
    )

    if idx == -1:
        return None

    search_text = text[
        idx + len(SECTION_MARKER):
    ]

    m = HEADER_RE.search(
        search_text
    )

    if not m:
        return None

    name = m.group(1).strip()
    ticker = m.group(2).strip()

    rows = []

    for rm in ROW_RE.finditer(
        search_text
    ):

        (
            _,
            high,
            low,
            open_,
            close,
            vol,
            val,
            date,
        ) = rm.groups()

        rows.append(
            {
                "date": date,
                "open": num(open_),
                "high": num(high),
                "low": num(low),
                "close": num(close),
                "volume": num(vol),
                "value": num(val),
            }
        )

    return (
        ticker,
        name,
        rows,
    )