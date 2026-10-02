import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from daily_update import parse_todays_trade


RAW = """
1:{date:'2026-09-25',time:'18:59:06'}
2:[{"companySymbol":"AARD","OpeningPrice":"123.45","HighPrice":"125.00","LowPrice":"120.00","ClosingPrice":"124.00","Volume":"1000","Turnover":"123450","BuyOrderQty":"10","HighestBidPrice":"123.50","SellOrderQty":"11","LowestOfferPrice":"124.50"}]
"""


def test_parse_todays_trade_accepts_single_quoted_metadata():
    result = parse_todays_trade(RAW)

    assert result["date"] == "2026-09-25"
    assert result["time"] == "18:59:06"
    assert result["rows"][0]["ticker"] == "AARD"
