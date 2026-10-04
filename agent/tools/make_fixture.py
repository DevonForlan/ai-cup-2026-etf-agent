"""Generate a SYNTHETIC fixture dataset (seeded) for the 150-stock universe, and synthetic
active-ETF top-10 holdings. Everything produced here is fake and flagged as such.

  python agent\\tools\\make_fixture.py --out tests\\fixtures\\synthetic --start 2025-06-02 --end 2026-11-30
  python agent\\tools\\make_fixture.py --etf-only --history data\\history   # synthetic ETF holdings into real store
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import load_active_etfs, load_universe  # noqa: E402
from agent.data.loaders import HistoryStore  # noqa: E402

# Plausible (NOT real) top-10 template for domestic active ETFs; weights of ETF NAV.
ETF_TEMPLATE = [("2330", 0.20), ("2454", 0.07), ("2317", 0.06), ("2308", 0.05), ("3711", 0.045),
                ("2382", 0.04), ("2345", 0.035), ("6669", 0.035), ("2383", 0.03), ("3017", 0.03)]
ALT_NAMES = ["2303", "3037", "2360", "8299", "5274", "3661", "2059", "6515", "2368", "3653"]


def synthetic_etf_holdings(etfs: list[dict], as_of_date: str, available_at: str, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for i, e in enumerate(etfs):
        name = e["name"]
        if any(k in name for k in ("美國", "全球", "ARK")):
            names = [("AAPL", 0.09), ("MSFT", 0.08), ("NVDA", 0.08), ("AMZN", 0.06), ("META", 0.05),
                     ("GOOGL", 0.05), ("AVGO", 0.04), ("TSLA", 0.04), ("ORCL", 0.03), ("AMD", 0.03)]
        else:
            names = list(ETF_TEMPLATE)
            k = int(rng.integers(0, 4))
            for j in range(k):           # swap a few lower names for variety
                names[9 - j] = (ALT_NAMES[(i + j) % len(ALT_NAMES)], names[9 - j][1])
        for r, (t, w) in enumerate(names, start=1):
            rows.append({"date": as_of_date, "etf": e["etf"], "ticker": t,
                         "weight": round(w * float(rng.uniform(0.85, 1.15)), 4), "rank": r,
                         "available_at": available_at, "synthetic": True})
    return pd.DataFrame(rows)


def weekdays(start: str, end: str) -> list[str]:
    d, e = date.fromisoformat(start), date.fromisoformat(end)
    out = []
    while d <= e:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def make(out: Path, start: str, end: str, seed: int = 42) -> None:
    rng = np.random.default_rng(seed)
    uni = load_universe()
    tickers = sorted(uni)
    days = weekdays(start, end)
    n, T = len(tickers), len(days)
    base = {t: float(rng.uniform(20, 1200)) for t in tickers}
    base["2330"] = 1500.0
    mu = rng.normal(0.0004, 0.0008, n)
    sig = rng.uniform(0.012, 0.035, n)
    mkt = rng.normal(0.0003, 0.009, T)
    rets = mkt[:, None] * rng.uniform(0.6, 1.4, n)[None, :] + rng.normal(mu, sig, (T, n))
    close = np.array([base[t] for t in tickers])[None, :] * np.exp(np.cumsum(rets, axis=0))
    close = np.round(close, 2)
    prows, irows = [], []
    for i, d in enumerate(days):
        for j, t in enumerate(tickers):
            c = float(close[i, j])
            o = round(c * float(rng.uniform(0.98, 1.02)), 2)
            hi = round(max(o, c) * float(rng.uniform(1.0, 1.02)), 2)
            lo = round(min(o, c) * float(rng.uniform(0.98, 1.0)), 2)
            vw = float(rng.uniform(lo, hi))
            vol = int(rng.integers(200, 20000)) * 1000
            amt = int(round(vol * vw))
            prows.append({"date": d, "ticker": t, "market": uni[t]["market"], "open": o, "high": hi, "low": lo,
                          "close": c, "volume": vol, "amount": amt, "vwap": amt / vol,
                          "available_at": f"{d}T15:00:00+08:00"})
            net = int(rng.normal(0, 0.05) * vol) // 1000 * 1000
            irows.append({"date": d, "ticker": t, "foreign_net": net, "trust_net": 0, "dealer_net": 0,
                          "total_net": net, "available_at": f"{d}T17:00:00+08:00"})
    rrows = []
    months = pd.period_range(start=pd.Period(start, "M") - 13, end=pd.Period(end, "M"), freq="M")
    for t in tickers:
        lvl = float(rng.uniform(1e9, 5e10))
        g = float(rng.normal(0.01, 0.02))
        for p in months:
            lvl *= float(np.exp(g + rng.normal(0, 0.08)))
            nxt = p + 1
            rrows.append({"ticker": t, "year": p.year, "month": p.month, "revenue": round(lvl),
                          "available_at": f"{nxt.year:04d}-{nxt.month:02d}-10T23:59:00+08:00"})
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(prows).to_csv(out / "daily_prices.csv", index=False)
    pd.DataFrame(irows).to_csv(out / "institutional.csv", index=False)
    pd.DataFrame(rrows).to_csv(out / "monthly_revenue.csv", index=False)
    synthetic_etf_holdings(load_active_etfs(), start, f"{start}T00:00:00+08:00").to_csv(out / "etf_holdings.csv", index=False)
    pd.DataFrame(columns=["ex_date", "ticker", "cash_dividend", "stock_dividend_per_share", "available_at"]).to_csv(
        out / "corporate_actions.csv", index=False)
    (out / "README.md").write_text("SYNTHETIC fixture data generated by agent/tools/make_fixture.py "
                                   f"(seed={seed}). Not real market data.\n", encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tests/fixtures/synthetic")
    ap.add_argument("--start", default="2025-06-02")
    ap.add_argument("--end", default="2026-11-30")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--etf-only", action="store_true")
    ap.add_argument("--history", default="data/history")
    ap.add_argument("--etf-date", default="2025-01-02")
    a = ap.parse_args(argv)
    if a.etf_only:
        st = HistoryStore(a.history)
        n = st.upsert("etf_holdings", synthetic_etf_holdings(load_active_etfs(), a.etf_date,
                                                             f"{a.etf_date}T00:00:00+08:00"))
        print("synthetic etf holdings rows", n)
        return
    make(Path(a.out), a.start, a.end, a.seed)
    print("fixture written to", a.out)


if __name__ == "__main__":
    main()
