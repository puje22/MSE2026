import json
import re
import requests


URL = "https://mse.mn/todays-trade"

NEXT_ACTION = "6d867ebd99fb6edef2f9537b22668cd0c00a71c2"

ROUTER_STATE = (
    '["",{"children":["(navbar)",{"children":["(trade)",'
    '{"children":["todays-trade",{"children":["__PAGE__",{},'
    '"/todays-trade","refresh"]}]}]}]},null,null,true]'
)


HEADERS = {
    "Accept": "text/x-component",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "text/plain;charset=UTF-8",
    "Next-Action": NEXT_ACTION,
    "Next-Router-State-Tree": ROUTER_STATE,
    "Origin": "https://mse.mn",
    "Referer": "https://mse.mn/todays-trade",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36 OPR/135.0.0.0"
    ),
}


PAYLOAD = json.dumps([
    {
        "url": "tradingStatus1",
        "parameter": "?lang=mn",
        "config": {
            "hasToken": False
        }
    }
], separators=(",", ":"))


def fetch_todays_trade():
    response = requests.post(
        URL,
        headers=HEADERS,
        data=PAYLOAD,
        timeout=30,
    )

    response.raise_for_status()

    return response.text


def parse_todays_trade(text):
    """
    Parse MSE's Next.js / React Server Component response.

    Returns a list of dictionaries containing the current trading data.
    """

    # The useful record starts with:
    #
    # 1:[{...},{...}]
    #
    match = re.search(r"(?m)^1:(\[.*\])", text)

    if not match:
        raise ValueError(
            "Could not find trading-data array in MSE response."
        )

    data = json.loads(match.group(1))

    results = []

    for row in data:
        results.append({
            "ticker": row.get("companySymbol"),
            "code": row.get("code"),
            "open": parse_number(row.get("OpeningPrice")),
            "high": parse_number(row.get("HighPrice")),
            "low": parse_number(row.get("LowPrice")),
            "last": parse_number(row.get("LastTradedPrice")),
            "previous_close": parse_number(row.get("PreviousClose")),
            "close": parse_number(row.get("ClosingPrice")),
            "change": row.get("Changes"),
            "change_pct": row.get("changePercentage"),
            "volume": parse_number(row.get("Volume")),
            "turnover": parse_number(row.get("Turnover")),
            "buy_order_qty": parse_number(row.get("BuyOrderQty")),
            "highest_bid": parse_number(row.get("HighestBidPrice")),
            "sell_order_qty": parse_number(row.get("SellOrderQty")),
            "lowest_offer": parse_number(row.get("LowestOfferPrice")),
        })

    return results


def parse_number(value):
    if value is None or value == "":
        return None

    if isinstance(value, (int, float)):
        return float(value)

    return float(str(value).replace(",", ""))


def main():
    print("Fetching MSE Today's Trade...")

    raw = fetch_todays_trade()

    print("Response length:", len(raw))

    data = parse_todays_trade(raw)

    print("Rows:", len(data))
    print()

    for row in data:
        print(
            f"{row['ticker']:6} "
            f"code={row['code']} "
            f"close={row['close']} "
            f"volume={row['volume']} "
            f"turnover={row['turnover']}"
        )


if __name__ == "__main__":
    main()