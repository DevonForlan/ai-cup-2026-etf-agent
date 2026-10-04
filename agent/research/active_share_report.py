"""Active Share: REAL issuer holdings vs SYNTHETIC template, on a simulated run's settled portfolios.

  python agent\\research\\active_share_report.py --run sim_runs\\round03\\main2\\H10_full__W5__official

Writes reports/active_share_<run>.csv: per day, per mode minimum, closest ETF, gap to 20%.
Benchmarks = official 30 ETFs' top-10 visible at the decision time of that day (PIT).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT, D  # noqa: E402
from agent.data.loaders import HistoryStore  # noqa: E402
from agent.data.pit import PITView  # noqa: E402
from agent.engine.active_share import compute_active_share  # noqa: E402
from agent.engine.rules import load_rulebook  # noqa: E402
from agent.pipeline import as_of_weights  # noqa: E402


def holdings_top10(view: PITView, real: bool) -> tuple[dict, dict]:
    df = view.etf_holdings()
    df = df[df["synthetic"] != real]
    if len(df) == 0:
        return {}, {}
    last = df.groupby("etf")["date"].transform("max")
    df = df[(df["date"] == last) & df["weight"].notna()].sort_values(["etf", "weight"], ascending=[True, False])
    top = df.groupby("etf").head(10)
    out: dict = {}
    for e, t, w in zip(top["etf"], top["ticker"], top["weight"]):
        out.setdefault(e, {})[t] = D(round(float(w), 6))
    return out, top.groupby("etf")["date"].max().to_dict()


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    a = ap.parse_args(argv)
    run = Path(a.run)
    rb = load_rulebook()
    st = HistoryStore()
    rows = []
    for p in sorted((run / "settlement").glob("*.json")):
        s = json.loads(p.read_text(encoding="utf-8"))
        d = s["date"]
        w = as_of_weights({k: int(v) for k, v in s["holdings"].items()}, {k: D(v) for k, v in s["closes"].items()},
                          D(s["cash"]))
        view = PITView(st, f"{d}T07:00:00+08:00")
        for label, real in (("real", True), ("synthetic", False)):
            h, dates = holdings_top10(view, real)
            if not h:
                rows.append({"date": d, "benchmarks": label, "n_etf": 0})
                continue
            res = compute_active_share(w, h, rb.active_etfs, "UNKNOWN")
            per_mode_etf = {m: min(((v[m], e) for e, v in res.per_etf.items()), default=(None, None))
                            for m in res.min_by_mode}
            rows.append({"date": d, "benchmarks": label, "n_etf": len(h),
                         "min_active_share": float(res.minimum_active_share), "closest_etf": res.benchmark_ticker,
                         "gap_to_20pct": float(res.minimum_active_share) - 0.20,
                         **{f"min_{m}": float(v[0]) for m, v in per_mode_etf.items() if v[0] is not None},
                         **{f"etf_{m}": v[1] for m, v in per_mode_etf.items()},
                         "oldest_benchmark_date": min(dates.values()) if dates else None})
    df = pd.DataFrame(rows)
    out = ROOT / "reports" / f"active_share_{run.name}.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 250)
    print(df.to_string())
    print("wrote", out)


if __name__ == "__main__":
    main()
