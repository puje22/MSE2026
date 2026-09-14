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
TIMEOUT = 20
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; research-scraper/1.0)"
}

# NOTE: internal company IDs on members.mse.mn are DIFFERENT from the old
# old.mse.mn IDs (e.g. TTL was 458 on old.mse.mn, but is 510 here). Any
# previously-built ticker_ids.json must be regenerated against this domain.

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


def num(s):
    return float(s.replace(",", ""))


def fetch(company_id, delay=0.3):
    url = BASE_URL.format(id=company_id)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException:
        return None
    finally:
        time.sleep(delay)
    return resp.text


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
