import requests

url = "https://old.mse.mn/en/company/458"  # known-good: Tavantolgoi (TTL)
headers = {"User-Agent": "Mozilla/5.0 (compatible; research-scraper/1.0)"}

try:
    resp = requests.get(url, headers=headers, timeout=20)
    print("STATUS CODE:", resp.status_code)
    print("FINAL URL:", resp.url)
    print("CONTENT LENGTH:", len(resp.text))
    print()
    print("--- First 1000 chars of response ---")
    print(resp.text[:1000])
    print()
    print("--- Does it contain our marker text? ---")
    print("Trading history of Block Trade" in resp.text)
except requests.RequestException as e:
    print("REQUEST FAILED WITH EXCEPTION:")
    print(repr(e))