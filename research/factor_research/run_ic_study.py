"""RESEARCH ONLY. Standalone + incremental Rank-IC study of candidate factors (point-in-time panels from
agent/research/factor_lab.py). Periods are fixed BEFORE looking at results (chronological):
  DISCOVERY  2024-07-01 .. 2025-06-30   (sign / weight choices may use only this period)
  VALIDATION 2025-07-01 .. 2026-01-31
  HOLDOUT    2026-02-01 .. last date with a 10D forward return
Outputs: research/factor_research/results/ic_*.csv, correlation.csv, regime_timing.csv
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

from agent.data.loaders import HistoryStore  # noqa: E402
from agent.research.factor_lab import (FACTORS, base_score, build_panels, daily_ic,  # noqa: E402
                                        forward_returns, incremental_ic)

OUT = ROOT / "research" / "factor_research" / "results"
PERIODS = {"DISCOVERY": ("2024-07-01", "2025-06-30"), "VALIDATION": ("2025-07-01", "2026-01-31"),
           "HOLDOUT": ("2026-02-01", "2099-12-31")}
HORIZONS = (1, 5, 10)


def tstat(s: pd.Series, h: int) -> float:
    """t-stat on non-overlapping observations (every h-th day) to avoid overlap inflation."""
    s = s.dropna().iloc[::h]
    return float(s.mean() / s.std() * np.sqrt(len(s))) if len(s) > 5 and s.std() > 0 else float("nan")


def top_quintile_hit(f: pd.DataFrame, fwd: pd.DataFrame, elig: pd.DataFrame, dates) -> float:
    hits = []
    for d in dates:
        ok = elig.loc[d] & f.loc[d].notna() & fwd.loc[d].notna()
        if ok.sum() < 30:
            continue
        x, y = f.loc[d][ok], fwd.loc[d][ok]
        top = x >= x.quantile(0.8)
        hits.append(float((y[top] > y.median()).mean()))
    return float(np.mean(hits)) if hits else float("nan")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    val = ROOT / "data" / "research" / "valuation_daily.parquet"
    P, aux = build_panels(HistoryStore(), val if val.exists() else None)
    close, elig, ew = aux["close"], aux["eligible"], aux["ew"]
    fwd = {h: forward_returns(close, h) for h in HORIZONS}
    last = fwd[10].dropna(how="all").index.max()
    dates = [d for d in close.index if "2024-07-01" <= d <= last]
    per = {k: [d for d in dates if a <= d <= b] for k, (a, b) in PERIODS.items()}
    # regime: EW universe 20D trend (from closes through T-1)
    ew_idx = (1 + ew.fillna(0)).cumprod()
    trend = (ew_idx / ew_idx.shift(20) - 1).shift(1)
    regime = {d: ("UP" if trend.get(d, np.nan) > 0 else "DOWN") for d in dates}
    names = [f.name for f in FACTORS if f.name in P]
    rows, inc_rows = [], []
    for name in names:
        f = P[name]
        r = {"factor": name, "family": next(x.family for x in FACTORS if x.name == name),
             "pit": next(x.pit for x in FACTORS if x.name == name), "coverage": float(f.loc[dates].notna().mean().mean())}
        for h in HORIZONS:
            ic = daily_ic(f.loc[dates], fwd[h], elig)
            r[f"ic{h}_mean"], r[f"ic{h}_median"], r[f"ic{h}_std"] = ic.mean(), ic.median(), ic.std()
            r[f"ic{h}_t"], r[f"ic{h}_pos_share"] = tstat(ic, h), float((ic > 0).mean())
            for pk, pd_ in per.items():
                s = ic.reindex(pd_).dropna()
                r[f"ic{h}_{pk}"] = s.mean() if len(s) else np.nan
            if h == 5:
                for rg in ("UP", "DOWN"):
                    r[f"ic5_regime_{rg}"] = ic[[d for d in ic.index if regime.get(d) == rg]].mean()
        r["hit_top_quintile_5d"] = top_quintile_hit(f, fwd[5], elig, dates[::5])
        rows.append(r)
        # incremental: sign decided on DISCOVERY 5D IC only; weight 0.2 on top of base (0.7/0.3)
        sign = 1 if r["ic5_DISCOVERY"] >= 0 else -1
        for pk, pd_ in per.items():
            inc = incremental_ic(P, name, sign, 0.2, fwd[5], elig, pd_[::1])
            inc_rows.append({"factor": name, "period": pk, "sign_from_discovery": sign, **inc})
    pd.DataFrame(rows).to_csv(OUT / "ic_standalone.csv", index=False)
    pd.DataFrame(inc_rows).to_csv(OUT / "ic_incremental.csv", index=False)
    # base score standalone (frozen v1 composite)
    bs = pd.DataFrame({d: base_score(P, d) for d in dates}).T
    base = {}
    for h in HORIZONS:
        ic = daily_ic(bs, fwd[h], elig)
        base[f"ic{h}_mean"], base[f"ic{h}_t"] = ic.mean(), tstat(ic, h)
        for pk, pd_ in per.items():
            base[f"ic{h}_{pk}"] = ic.reindex(pd_).dropna().mean()
    (OUT / "ic_base_v1.json").write_text(json.dumps(base, indent=1, default=float), encoding="utf-8")
    # correlation: mean daily cross-sectional Spearman between factors (sampled every 5 days), incl. base
    sample = dates[::5]
    allf = {"BASE_V1": bs, **{n: P[n] for n in names}}
    keys = list(allf)
    C = pd.DataFrame(np.nan, index=keys, columns=keys)
    for i, a in enumerate(keys):
        for b in keys[i:]:
            v = []
            for d in sample:
                x, y = allf[a].loc[d], allf[b].loc[d]
                ok = elig.loc[d] & x.notna() & y.notna()
                if ok.sum() >= 30:
                    v.append(x[ok].rank().corr(y[ok].rank()))
            C.loc[a, b] = C.loc[b, a] = np.mean(v) if v else np.nan
    C.to_csv(OUT / "correlation.csv")
    # regime / overnight signals: time-series Spearman vs NEXT EW universe return (risk / cash use, not selection)
    store = HistoryStore()
    m = store.load("market_overnight")
    m["ts"] = pd.to_datetime(m["available_at"].astype(str).str[:19])
    above = (close > close.rolling(20, min_periods=15).mean()).where(close.notna())
    sig = pd.DataFrame(index=dates)
    sig["breadth_ma20"] = above.mean(axis=1).shift(1).reindex(dates)
    sig["ew_trend_20"] = trend.reindex(dates)
    sig["ew_drawdown_60"] = (ew_idx / ew_idx.rolling(60, min_periods=20).max() - 1).shift(1).reindex(dates)
    sig["ew_vol_20"] = ew.rolling(20).std().shift(1).reindex(dates)
    dec = pd.DataFrame({"decision": pd.to_datetime(pd.Series(dates)) + pd.Timedelta(hours=7)})
    for sym in ("SOX", "NDX", "SPX", "TSM", "TXF_NIGHT", "USDTWD"):
        g = m[m["symbol"] == sym].sort_values("ts")[["ts", "ret"]]
        sig[f"overnight_{sym}"] = pd.merge_asof(dec, g, left_on="decision", right_on="ts")["ret"].to_numpy()
    ewfwd = {h: ((1 + ew.fillna(0)).cumprod().shift(-(h - 1)) / (1 + ew.fillna(0)).cumprod().shift(1) - 1).reindex(dates)
             for h in HORIZONS}
    trows = []
    for c in sig.columns:
        r = {"signal": c}
        for h in HORIZONS:
            for pk, pd_ in per.items():
                x, y = sig.loc[pd_, c], ewfwd[h].reindex(pd_)
                ok = x.notna() & y.notna()
                r[f"ts_corr{h}_{pk}"] = x[ok].rank().corr(y[ok].rank()) if ok.sum() > 20 else np.nan
        trows.append(r)
    pd.DataFrame(trows).to_csv(OUT / "regime_timing.csv", index=False)
    meta = {"dates": [dates[0], dates[-1]], "n_dates": len(dates), "periods": {k: [v[0], v[-1], len(v)] for k, v in per.items()},
            "factors_tested": names, "valuation_included": val.exists()}
    (OUT / "ic_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps(meta)[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
