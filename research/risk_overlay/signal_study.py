"""RESEARCH ONLY. Regime-signal study on the EXPLOITABLE horizon and window classification.

A 07:00 decision on T trades at T's VWAP, so the overnight gap (close T-1 -> VWAP T) cannot be avoided. For each
signal we compare the EW universe return VWAP(T) -> close(T+h-1) when the vote / trigger is ON vs OFF.
Outputs results/signal_votes.csv, signal_triggers.csv, window_types.csv, signals_daily.csv.
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
warnings.filterwarnings("ignore")
import overlay_lab as L  # noqa: E402
from agent.data.loaders import HistoryStore  # noqa: E402

OUT = HERE / "results"
PER = {"DISCOVERY": ("2024-07-01", "2025-07-31"), "VALIDATION": ("2025-08-01", "2026-03-10"),
       "HOLDOUT": ("2026-03-11", "2026-10-15")}       # date ranges follow the window periods (R01-R11 / R12-R17 / R18-)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    store = HistoryStore()
    s = L.build_signals(store)
    v = L.votes(s)
    S = L.candidate_states(s)
    uni = set(pd.read_csv(ROOT / "config" / "universe_150.csv", dtype=str, encoding="utf-8-sig")["ticker"])
    px = store.load("daily_prices")
    px = px[px["ticker"].astype(str).isin(uni)]
    close = px.pivot_table(index="date", columns="ticker", values="close").sort_index()
    vwap = px.pivot_table(index="date", columns="ticker", values="vwap").sort_index().reindex(close.index)
    dates = list(close.index)
    fwd = {}
    for h in (1, 5):
        fut = close.shift(-(h - 1))
        fwd[h] = (fut / vwap - 1).mean(axis=1)            # EW: VWAP(T) -> close(T+h-1)
    gap = (vwap / close.shift(1) - 1).mean(axis=1)        # unavoidable part: close(T-1) -> VWAP(T)
    cc1 = (close / close.shift(1) - 1).mean(axis=1)
    d = pd.DataFrame({"fwd1": fwd[1], "fwd5": fwd[5], "gap": gap, "cc1": cc1}).reindex(s.index)
    lab = pd.Series(index=s.index, dtype=object)
    for k, (a, b) in PER.items():
        lab[(s.index >= a) & (s.index <= b)] = k
    d["period"] = lab
    d["crash5"] = d["fwd5"] <= -0.04
    d = d[d.period.notna()]
    rows = []
    for name, on in [(k, v[k]) for k in L.VOTES] + [(f"STATE_{k}", S[k] != "NORMAL") for k in S]:
        on = on.reindex(d.index).fillna(False)
        for per in ("DISCOVERY", "VALIDATION", "HOLDOUT", "ALL"):
            m = d.period.notna() if per == "ALL" else (d.period == per)
            x, o = d[m], on[m]
            r = {"signal": name, "period": per, "n": int(m.sum()), "on_days": int(o.sum()), "on_share": float(o.mean())}
            for c in ("fwd1", "fwd5", "gap", "cc1"):
                r[f"{c}_on"] = float(x.loc[o, c].mean()) if o.any() else np.nan
                r[f"{c}_off"] = float(x.loc[~o, c].mean())
            r["fwd5_diff"] = r["fwd5_on"] - r["fwd5_off"]
            r["fwd1_diff"] = r["fwd1_on"] - r["fwd1_off"]
            ev = x["crash5"]
            r["crash5_events"] = int(ev.sum())
            r["crash5_recall"] = float((o & ev).sum() / ev.sum()) if ev.sum() else np.nan
            r["crash5_precision"] = float((o & ev).sum() / o.sum()) if o.sum() else np.nan
            rows.append(r)
    pd.DataFrame(rows).to_csv(OUT / "signal_study.csv", index=False)
    # window types on the median index (same index as the signals; strategy-independent)
    med = (close / close.shift(1) - 1).median(axis=1)
    W = json.loads((ROOT / "research" / "factor_research" / "results" / "windows.json").read_text(encoding="utf-8"))
    wt = []
    for w in W:
        r = med[(med.index >= w["start"]) & (med.index <= w["end"])]
        nav = pd.concat([pd.Series([1.0]), (1 + r).cumprod().reset_index(drop=True)])
        ret, mdd = float(nav.iloc[-1] - 1), float((1 - nav / nav.cummax()).max())
        ew_mean = (close / close.shift(1) - 1).mean(axis=1)
        re = ew_mean[(ew_mean.index >= w["start"]) & (ew_mean.index <= w["end"])]
        typ = "CRASH" if (ret <= -0.05 or mdd >= 0.08) else ("BULL" if ret >= 0.05 else "SIDEWAYS")
        wt.append({**w, "idx_ret": ret, "idx_mdd": mdd, "ew_mean_ret": float((1 + re).prod() - 1), "type": typ})
    pd.DataFrame(wt).to_csv(OUT / "window_types.csv", index=False)
    out = pd.concat([s[[c for c in s.columns if not c.endswith("_ts")]], v, S.add_prefix("state_")], axis=1)
    out.to_csv(OUT / "signals_daily.csv")
    print(pd.DataFrame(wt)[["wid", "period", "idx_ret", "idx_mdd", "ew_mean_ret", "type"]].round(4).to_string())
    t = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    print(t[t.period != "ALL"].pivot(index="signal", columns="period", values="fwd5_diff").mul(100).round(2).to_string())
    print(t[t.period == "ALL"][["signal", "on_share", "fwd1_diff", "fwd5_diff", "gap_on", "gap_off", "crash5_events", "crash5_recall", "crash5_precision"]].round(4).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
