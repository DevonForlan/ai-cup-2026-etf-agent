"""Market-data COVERAGE gate (P-2, after the 2026-10-16 incident: TWSE quotes failed, TPEx stored -> the date
"existed" but 100 of 150 tickers had no price; the evaluation only noticed at NAV reconciliation).

"Some rows exist for date D" is NOT "market data for D is complete". A date is COMPLETE only when
  A. every required ticker (current holdings: valid close > 0; tickers with orders: also vwap > 0 and volume > 0)
     has a row for exactly that date, and
  B. every market of the universe (TWSE and TPEx) is present and covers >= market_coverage.min_market_share of its
     universe tickers.
Status: COMPLETE | INCOMPLETE (rows exist but A or B fails) | MISSING (no row for D at all).
Callers turn INCOMPLETE / MISSING into MARKET_DATA_INCOMPLETE / MARKET_DATA_NOT_AVAILABLE (BLOCK). Read-only.
"""
from __future__ import annotations

from collections.abc import Iterable

DEFAULTS = {"min_market_share": 0.95}


def _params(ops_cfg: dict | None) -> dict:
    return {**DEFAULTS, **((ops_cfg or {}).get("market_coverage") or {})}


def _universe_markets() -> dict[str, str]:
    from agent.config import load_universe
    return {t: v["market"] for t, v in load_universe().items()}


def day_coverage(store, date: str, holdings: Iterable[str] = (), order_tickers: Iterable[str] = (),
                 ops_cfg: dict | None = None, universe: dict[str, str] | None = None) -> dict:
    p = _params(ops_cfg)
    uni = universe or _universe_markets()
    px = store.load("daily_prices")
    rows = px[px["date"] == date]
    out = {"date": date, "status": "COMPLETE", "problems": [], "by_market": {}, "missing_holdings": [],
           "missing_order_prices": []}
    if not len(rows):
        out.update(status="MISSING", problems=[f"no price rows for {date}"])
        return out
    rows = rows.drop_duplicates("ticker", keep="last")
    rows = rows.set_index(rows["ticker"].astype(str))

    def ok(t, col):
        if t not in rows.index:
            return False
        v = rows.at[t, col]
        try:
            return v is not None and float(v) > 0
        except (TypeError, ValueError):
            return False

    for m in sorted(set(uni.values())):
        want = [t for t, mk in uni.items() if mk == m]
        have = sum(1 for t in want if ok(t, "close"))
        share = have / len(want) if want else 1.0
        out["by_market"][m] = {"have": have, "expected": len(want), "share": round(share, 4)}
        if share < p["min_market_share"]:
            out["problems"].append(f"{m}: {have}/{len(want)} universe tickers priced (< {p['min_market_share']:.0%})")
    out["missing_holdings"] = sorted(t for t in {str(x) for x in holdings} if not ok(t, "close"))
    if out["missing_holdings"]:
        out["problems"].append(f"holdings without a valid {date} close: {out['missing_holdings'][:20]}")
    need = {str(x) for x in order_tickers}
    out["missing_order_prices"] = sorted(t for t in need if not (ok(t, "vwap") and ok(t, "volume")))
    if out["missing_order_prices"]:
        out["problems"].append(f"order tickers without a valid {date} vwap/volume: {out['missing_order_prices'][:20]}")
    if out["problems"]:
        out["status"] = "INCOMPLETE"
    return out


def summary_line(c: dict) -> str:
    mk = ", ".join(f"{m} {v['have']}/{v['expected']}" for m, v in c["by_market"].items())
    return f"{c['date']} {c['status']} ({mk or 'no rows'})" + ("; " + "; ".join(c["problems"])[:300] if c["problems"] else "")


def incomplete_days(store, dates: Iterable[str], ops_cfg: dict | None = None) -> list[str]:
    """Dates (already in the store) whose universe coverage is INCOMPLETE -> to be re-fetched like a missing day."""
    uni = _universe_markets()
    return [d for d in dates if day_coverage(store, d, ops_cfg=ops_cfg, universe=uni)["status"] == "INCOMPLETE"]


def coverage_check(store, date: str, holdings: Iterable[str] = (), ops_cfg: dict | None = None):
    """preflight Check: BLOCK unless COMPLETE (both modes: an incomplete day gives wrong decisions in any mode)."""
    from agent.ops.common import BLOCK, PASS, Check
    c = day_coverage(store, date, holdings=holdings, ops_cfg=ops_cfg)
    reason = "" if c["status"] == "COMPLETE" else ("MARKET_DATA_INCOMPLETE: " if c["status"] == "INCOMPLETE"
                                                   else "MARKET_DATA_NOT_AVAILABLE: ")
    return Check("market_coverage", PASS if c["status"] == "COMPLETE" else BLOCK, reason + summary_line(c))
