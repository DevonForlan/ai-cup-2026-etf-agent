"""Historical backfill into data/history (+ raw snapshots in data/raw/YYYYMMDD).

Usage:
  python agent\\tools\\backfill.py --start 2025-09-01 --end 2026-10-02 [--skip-insti] [--revenue]
Resumable: dates already present in daily_prices are skipped.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import load_data_sources, load_universe  # noqa: E402
from agent.data.fetchers import finmind, tpex, twse  # noqa: E402
from agent.data.http import make_session  # noqa: E402
from agent.data.loaders import HistoryStore  # noqa: E402


def weekdays(start: str, end: str):
    d, e = date.fromisoformat(start), date.fromisoformat(end)
    while d <= e:
        if d.weekday() < 5:
            yield d.isoformat()
        d += timedelta(days=1)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--skip-insti", action="store_true")
    ap.add_argument("--revenue", action="store_true", help="also fetch FinMind monthly revenue")
    ap.add_argument("--revenue-only", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_data_sources()
    av = cfg["availability"]
    uni = load_universe()
    useti = {t for t, v in uni.items() if v["market"] == "TWSE"}
    otc = {t for t, v in uni.items() if v["market"] == "TPEx"}
    store = HistoryStore()
    s = make_session(cfg["http"]["relax_x509_strict"])

    if not args.revenue_only:
        have = set(store.dates("daily_prices"))
        have_i = set(store.dates("institutional"))
        for d in weekdays(args.start, args.end):
            if d in have and (args.skip_insti or d in have_i):
                continue
            try:
                rows, _ = twse.fetch_daily_quotes(s, cfg, d, useti, av["daily_prices"])
                if not rows:
                    print(d, "TWSE: no data (holiday?)", flush=True)
                    continue
                rows2, _ = tpex.fetch_daily_quotes(s, cfg, d, otc, av["daily_prices"])
                n = store.upsert("daily_prices", [dict(r, available_at=f"{d}T{av['daily_prices']}:00+08:00") for r in rows + rows2])
                msg = f"{d} prices {n}"
                if not args.skip_insti:
                    i1, _ = twse.fetch_institutional(s, cfg, d, useti, av["institutional"])
                    i2, _ = tpex.fetch_institutional(s, cfg, d, otc, av["institutional"])
                    m = store.upsert("institutional", [dict(r, available_at=f"{d}T{av['institutional']}:00+08:00") for r in i1 + i2])
                    msg += f" insti {m}"
                print(msg, flush=True)
            except Exception as e:  # noqa: BLE001
                print(d, "ERROR", e, flush=True)

    if args.revenue or args.revenue_only:
        rstart = (date.fromisoformat(args.start) - timedelta(days=400)).isoformat()
        snap = args.end.replace("-", "")
        rday, rtime = int(av["monthly_revenue_day"]), av["monthly_revenue_time"]
        for t in sorted(uni):
            try:
                rows = finmind.fetch_monthly_revenue(s, cfg, t, rstart, args.end, snap)
                out = []
                for r in rows:
                    y, m = (r["year"], r["month"] + 1) if r["month"] < 12 else (r["year"] + 1, 1)
                    out.append(dict(r, available_at=f"{y:04d}-{m:02d}-{rday:02d}T{rtime}:00+08:00"))
                store.upsert("monthly_revenue", out)
                print("revenue", t, len(out), flush=True)
            except Exception as e:  # noqa: BLE001
                print("revenue", t, "ERROR", e, flush=True)


if __name__ == "__main__":
    main()
