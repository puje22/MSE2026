from scraper_lib import fetch_open

for cid in range(1, 1000):
    html = fetch_open(cid, delay=0.05)

    if html and "AARD" in html.upper():
        print("AARD appears in ID:", cid)