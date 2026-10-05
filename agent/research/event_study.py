"""Event study: do extracted event directions predict 1/3/5-day excess returns vs the universe?

Decision day T = first trading day whose 07:00 cut-off is after the event's available time.
Excess return over h days = close(T+h-1)/close(T-1) - 1 minus the universe median for the same span
(an investor acting at T can at best capture T's move; we measure from the T-1 close used by
derive-orders). Reports mean excess by direction, sign accuracy and t-stat.

  python agent\\research\\event_study.py --runs sim_runs\\round04\\events_* --out reports\\round04_event_study.csv
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agent.config import ROOT  # noqa: E402
from agent.data.loaders import HistoryStore  # noqa: E402
from agent.sim.calendar import TradingCalendar  # noqa: E402


def decision_day(cal: TradingCalendar, published_at: str) -> str | None:
    d, t = published_at[:10], published_at[11:16]
    if cal.is_trading_day(d) and t <= "07:00":
        return d
    return cal.next(d)


def study(events: pd.DataFrame, store: HistoryStore, horizons=(1, 3, 5)) -> pd.DataFrame:
    cal = TradingCalendar(store.dates("daily_prices"))
    p = store.load("daily_prices")
    c = p.pivot(index="date", columns="ticker", values="close").sort_index().astype(float)
    rows = []
    for e in events.itertuples():
        T = decision_day(cal, e.published_at)
        if T is None or T not in c.index:
            continue
        i = cal.days.index(T)
        prev = cal.days[i - 1] if i > 0 else None
        if prev is None:
            continue
        r = {"event_id": e.event_id, "ticker": e.ticker, "event_type": e.event_type, "direction": e.direction,
             "confidence": e.confidence, "published_at": e.published_at, "decision_day": T}
        for h in horizons:
            if i + h - 1 >= len(cal.days):
                r[f"ex_{h}d"] = np.nan
                continue
            end = cal.days[i + h - 1]
            if end not in c.index or e.ticker not in c.columns:
                r[f"ex_{h}d"] = np.nan
                continue
            span = c.loc[end] / c.loc[prev] - 1
            r[f"ex_{h}d"] = float(span[e.ticker] - span.median())
        rows.append(r)
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame, horizons=(1, 3, 5)) -> pd.DataFrame:
    out = []
    for direction, g in list(df.groupby("direction")) + [("ALL_signed", df)]:
        row = {"direction": direction, "n": len(g)}
        for h in horizons:
            col = f"ex_{h}d"
            x = g[col].dropna()
            if direction == "ALL_signed":
                sign = g.loc[x.index, "direction"].map({"positive": 1, "negative": -1}).fillna(0)
                x = (x * sign)[sign != 0]
            row[f"mean_{h}d"] = float(x.mean()) if len(x) else np.nan
            row[f"t_{h}d"] = float(x.mean() / (x.std() / math.sqrt(len(x)))) if len(x) > 2 and x.std() > 0 else np.nan
            if direction in ("positive", "negative"):
                s = 1 if direction == "positive" else -1
                row[f"sign_acc_{h}d"] = float(((x * s) > 0).mean()) if len(x) else np.nan
        out.append(row)
    return pd.DataFrame(out)


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True, help="sim run dirs with events.json (globs ok)")
    ap.add_argument("--out", default=str(ROOT / "reports" / "round04_event_study.csv"))
    a = ap.parse_args(argv)
    evs = []
    for pat in a.runs:
        for d in glob.glob(pat):
            f = Path(d) / "events.json"
            if f.exists():
                for day in json.loads(f.read_text(encoding="utf-8")):
                    evs += day["events"]
    if not evs:
        print("no events")
        return
    df = pd.DataFrame(evs).drop_duplicates("event_id")
    res = study(df, HistoryStore())
    res.to_csv(a.out, index=False, encoding="utf-8-sig")
    s = summarize(res)
    s.to_csv(a.out.replace(".csv", "_summary.csv"), index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 220)
    print(s.round(4).to_string())
    print(res.groupby(["event_type", "direction"]).size().to_string())


if __name__ == "__main__":
    main()
