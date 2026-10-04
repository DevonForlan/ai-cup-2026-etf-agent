"""FinMind fetcher (vendor, backup). Free tier: non-commercial, ~300 calls/hour.
Used here for monthly revenue history; prices only as fallback."""
from __future__ import annotations

from agent.data import normalizers as N
from agent.data.http import get_bytes
from agent.data.manifest import save_raw

AUTHORITY = "vendor"


def fetch_monthly_revenue(session, cfg: dict, ticker: str, start: str, end: str,
                          snapshot_date: str) -> list[dict]:
    url = cfg["endpoints"]["finmind"]
    params = {"dataset": "TaiwanStockMonthRevenue", "data_id": ticker, "start_date": start, "end_date": end}
    b, fetched = get_bytes(session, url, params=params, min_interval=1.5,
                           timeout=cfg["http"]["timeout_sec"], retries=cfg["http"]["retries"])
    save_raw(snapshot_date, "finmind_revenue", f"{ticker}.json", b,
             url=f"{url}?dataset=TaiwanStockMonthRevenue&data_id={ticker}&start_date={start}&end_date={end}",
             fetched_at=fetched.isoformat(), content_as_of=fetched.isoformat(),
             available_at=fetched.isoformat(), authority=AUTHORITY, parser_version=N.PARSER_VERSION)
    return N.parse_finmind_revenue(b)


def fetch_prices(session, cfg: dict, ticker: str, start: str, end: str, market_of: dict,
                 snapshot_date: str) -> list[dict]:
    url = cfg["endpoints"]["finmind"]
    params = {"dataset": "TaiwanStockPrice", "data_id": ticker, "start_date": start, "end_date": end}
    b, fetched = get_bytes(session, url, params=params, min_interval=1.5,
                           timeout=cfg["http"]["timeout_sec"], retries=cfg["http"]["retries"])
    save_raw(snapshot_date, "finmind_price", f"{ticker}.json", b,
             url=f"{url}?dataset=TaiwanStockPrice&data_id={ticker}&start_date={start}&end_date={end}",
             fetched_at=fetched.isoformat(), content_as_of=fetched.isoformat(),
             available_at=fetched.isoformat(), authority=AUTHORITY, parser_version=N.PARSER_VERSION)
    return N.parse_finmind_price(b, market_of)
