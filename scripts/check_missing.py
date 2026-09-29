import json
from pathlib import Path

from scraper_lib import fetch, parse_page

SCRIPT_DIR = Path(__file__).resolve().parent
with (SCRIPT_DIR / "ticker_ids.json").open("r", encoding="utf-8") as f:
    ids = json.load(f)

for t in ["TUM", "XAC", "XOC"]:
    cid = ids.get(t)
    print(f"{t}: id={cid}")
    if cid is None:
        print("  NOT IN ticker_ids.json")
        continue

    html = fetch(cid)
    if html is None:
        print("  FETCH FAILED (network error or non-200 response)")
        continue
    print(f"  fetch OK, {len(html)} bytes")

    parsed = parse_page(html)
    if parsed is None:
        print("  PARSE FAILED (page structure didn't match expected format)")
    else:
        ticker, name, rows = parsed
        print(f"  parsed OK: ticker={ticker}, name={name}, rows={len(rows)}")
    print()
