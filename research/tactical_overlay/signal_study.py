"""RESEARCH ONLY (Issue #14). Horizon study, revenue-signal decay, stock- and market-level signal evidence and the
current-regime snapshot (PRE_REGISTRATION.md §4, §7). Writes results/*.csv|json."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
import lab as L  # noqa: E402
from lab import spearmanr  # noqa: E402

OUT = HERE / "results"
RUNS = L.ROOT / "runtime" / "tactical_bt"


def horizon(data: L.Data) -> pd.DataFrame:
    rows = []
    for name in ("DENSE24", "H60", "H120"):
        df = pd.read_csv(OUT / f"frozen_{name}.csv")
        for r in df.itertuples():
            days = pd.read_csv(RUNS / r.run_id / "daily.csv", encoding="utf-8-sig")["date"].astype(str).tolist()
            ew = L.ew_universe(days, data)
            rp_x = L.random_portfolios(days, data, exit_cost=True)
            rp_n = L.random_portfolios(days, data, exit_cost=False)
            rows.append({"set": name, "start": r.start, "period": r.period, "days": len(days), "ret": r.ret, "mdd": r.mdd,
                         "turnover": r.turnover, "cost_pct": r.cost / L.INIT, "ew_ret": ew, "excess": r.ret - ew,
                         "pctile_exitcost": L.percentile(r.ret, rp_x), "pctile_nav": L.percentile(r.ret, rp_n),
                         "rp_p90_nav": float(np.quantile(rp_n, 0.9)), "violations": r.violations})
    h = pd.DataFrame(rows)
    h.to_csv(OUT / "horizon_windows.csv", index=False)
    return h


def horizon_summary(h: pd.DataFrame) -> dict:
    out = {}
    for name, g in h.groupby("set"):
        n = int(g["days"].median())
        out[name] = {"windows": len(g), "days": n, "mean_ret": g["ret"].mean(), "median_ret": g["ret"].median(),
                     "mean_excess": g["excess"].mean(), "median_excess": g["excess"].median(),
                     "excess_per_day": g["excess"].mean() / n, "hit_rate": float((g["excess"] > 0).mean()),
                     "mean_mdd": g["mdd"].mean(), "worst_ret": g["ret"].min(), "std_ret": g["ret"].std(),
                     "mean_turnover": g["turnover"].mean(), "mean_cost_pct": g["cost_pct"].mean(),
                     "mean_pctile_exitcost": g["pctile_exitcost"].mean(), "mean_pctile_nav": g["pctile_nav"].mean(),
                     "top_decile_nav": float((g["pctile_nav"] >= 90).mean()), "top_quartile_nav": float((g["pctile_nav"] >= 75).mean()),
                     "bottom_quartile_nav": float((g["pctile_nav"] < 25).mean()),
                     "oos_mean_excess": g[g["period"] == "OOS"]["excess"].mean(), "disc_mean_excess": g[g["period"] == "DISCOVERY"]["excess"].mean()}
    d24, e60, e120 = out["DENSE24"], out["H60"]["excess_per_day"], out["H120"]["excess_per_day"]
    hit, pd24 = d24["hit_rate"], d24["excess_per_day"]
    if hit < 0.55 and max(e60, e120) >= 1.5 * pd24:
        hm = "HIGH"
    elif hit >= 0.60 and pd24 >= 0.8 * max(e60, e120):
        hm = "LOW"
    else:
        hm = "MEDIUM"
    out["HORIZON_MISMATCH"] = hm
    out["rule_inputs"] = {"dense24_hit_rate": hit, "per_day_excess_24": pd24, "per_day_excess_60": e60, "per_day_excess_120": e120}
    return out


def revenue_score(data: L.Data, rev: pd.DataFrame, t: str) -> pd.Series:
    from agent.features.revenue import revenue_features
    cut = pd.Timestamp(t) + pd.Timedelta(hours=7)
    r = rev[pd.to_datetime(rev["available_at"].astype(str).str[:19]) <= cut]
    f = revenue_features(r, list(data.close.columns))
    sc = 0.7 * f["revenue_yoy"].astype(float).rank(pct=True) + 0.3 * f["revenue_mom"].astype(float).rank(pct=True)
    return sc.dropna()


def fwd(data: L.Data, t: str, h: int) -> pd.Series | None:
    i = data.dates.index(t)
    if i == 0 or i - 1 + h >= len(data.dates):
        return None
    return (data.close.loc[data.dates[i - 1 + h]] / data.close.loc[data.dates[i - 1]] - 1).dropna()


def ic_study(data: L.Data, starts: list[str]) -> pd.DataFrame:
    from agent.data.loaders import HistoryStore
    rev = HistoryStore(L.ROOT / "data" / "history").load("monthly_revenue")
    rev = rev.assign(ticker=rev["ticker"].astype(str))
    rows = []
    for t in starts:
        sc = revenue_score(data, rev, t)
        top50 = set(sc.sort_values().index[-50:])
        for h in (5, 24, 60, 120):
            f = fwd(data, t, h)
            if f is None:
                continue
            j = sc.index.intersection(f.index)
            rows.append({"start": t, "signal": "revenue_score", "h": h, "pool": "all",
                         "ic": spearmanr(sc[j], f[j]).statistic})
        f24 = fwd(data, t, 24)
        if f24 is None:
            continue
        for col, sign in (("mom20", 1), ("mom60", 1), ("flow20", 1), ("flow5", 1), ("vol20", -1)):
            s = data.sig[col].loc[t].dropna() * sign
            for pool, idx in (("all", s.index), ("top50_revenue", s.index.intersection(list(top50)))):
                j = idx.intersection(f24.index)
                if len(j) >= 15:
                    rows.append({"start": t, "signal": col if sign > 0 else f"low_{col}", "h": 24, "pool": pool,
                                 "ic": spearmanr(s[j], f24[j]).statistic})
    d = pd.DataFrame(rows)
    d["period"] = np.where(d["start"] < "2025-07-01", "DISCOVERY", "OOS")
    d.to_csv(OUT / "ic_study.csv", index=False)
    return d


def market_signals(data: L.Data, h: pd.DataFrame) -> pd.DataFrame:
    """Market-level signal at the window start vs next-24D EW universe return and frozen excess.
    p-values from 5000 permutations on the NON-overlapping NOV23 starts (DENSE24 overlap would overstate n)."""
    mk = data.sig["market"]
    nov = json.loads((L.ROOT / "research" / "factor_research" / "results" / "windows.json").read_text(encoding="utf-8"))
    d24 = h[h["set"] == "DENSE24"].set_index("start")
    cols = ["breadth", "ew_trend20", "ew_vol20", "ew_dd60", "SOX_20", "NDX_20", "SPX_20", "TSM_5", "USDTWD_20",
            "DGS10_chg20", "DCOILWTICO_chg20", "DTWEXBGS_chg20", "VIXCLS_lvl"]
    ov = pd.read_csv(OUT / "overlay_windows.csv") if (OUT / "overlay_windows.csv").exists() else None
    base = ov[(ov["set"] == "NOV23") & (ov["variant"] == "BASE")].set_index("start") if ov is not None else None
    rng = np.random.default_rng(14)
    rows = []
    for c in cols:
        for target in ("ew_ret", "excess"):
            for period in ("DISCOVERY", "OOS"):
                st = [w["start"] for w in nov if (w["period"] == "DISCOVERY") == (period == "DISCOVERY")]
                x = mk.reindex(st)[c].to_numpy(dtype=float)
                if target == "ew_ret":
                    y = np.array([base.loc[s, "ew_ret"] if base is not None and s in base.index else np.nan for s in st])
                else:
                    y = np.array([base.loc[s, "ret"] - base.loc[s, "ew_ret"] if base is not None and s in base.index else np.nan for s in st])
                ok = ~(np.isnan(x) | np.isnan(y))
                if ok.sum() < 5:
                    rows.append({"signal": c, "target": target, "period": period, "n": int(ok.sum()), "rho": np.nan, "p": np.nan})
                    continue
                rho = spearmanr(x[ok], y[ok]).statistic
                perm = np.array([spearmanr(x[ok], rng.permutation(y[ok])).statistic for _ in range(5000)])
                p = float((np.abs(perm) >= abs(rho)).mean())
                dx = d24.reindex([s for s in d24.index if (s < "2025-07-01") == (period == "DISCOVERY")])
                xx = mk.reindex(dx.index)[c].to_numpy(dtype=float)
                yy = (dx["ew_ret"] if target == "ew_ret" else dx["excess"]).to_numpy(dtype=float)
                ok2 = ~(np.isnan(xx) | np.isnan(yy))
                rho_d = spearmanr(xx[ok2], yy[ok2]).statistic if ok2.sum() >= 5 else np.nan
                rows.append({"signal": c, "target": target, "period": period, "n": int(ok.sum()), "rho": rho, "p": p,
                             "rho_dense24": rho_d, "n_dense24": int(ok2.sum())})
    d = pd.DataFrame(rows)
    d.to_csv(OUT / "market_signals.csv", index=False)
    return d


def regime_snapshot(data: L.Data) -> dict:
    mk = data.sig["market"]
    last = data.dates[-1]
    snap = {"as_of_decision_date_after": last}
    nxt = mk.copy()
    # the decision for the next trade date uses data through `last`: recompute that row's values
    c = data.close
    ew = data.ret.median(axis=1)
    idx = (1 + ew.fillna(0)).cumprod()
    snap["breadth_through_last_close"] = float((c > c.rolling(20, min_periods=15).mean()).astype(float).iloc[-1].mean())
    snap["ew_trend20"] = float(idx.iloc[-1] / idx.iloc[-21] - 1)
    snap["ew_vol20_ann"] = float(ew.iloc[-20:].std() * np.sqrt(252))
    snap["ew_dd60"] = float(idx.iloc[-1] / idx.iloc[-60:].max() - 1)
    hist = pd.DataFrame({"vol": ew.rolling(20).std() * np.sqrt(252), "trend": idx / idx.shift(20) - 1})
    snap["ew_vol20_pctile_hist"] = float((hist["vol"].dropna() < snap["ew_vol20_ann"]).mean() * 100)
    snap["ew_trend20_pctile_hist"] = float((hist["trend"].dropna() < snap["ew_trend20"]).mean() * 100)
    m = data.overnight
    for sym in ("SOX", "NDX", "SPX", "TSM", "USDTWD"):
        g = m[m["symbol"] == sym].sort_values("date")
        g = g[g["date"] <= "2026-10-23"]
        cl = g["close"].astype(float).to_numpy()
        r = np.diff(np.log(cl))
        snap[f"{sym}_last_date"] = str(g["date"].iloc[-1])
        snap[f"{sym}_ret20"] = float(cl[-1] / cl[-21] - 1)
        snap[f"{sym}_vol20_ann"] = float(r[-20:].std() * np.sqrt(252))
        snap[f"{sym}_vol20_pctile_hist"] = float((pd.Series(r).rolling(20).std().dropna() * np.sqrt(252) < snap[f"{sym}_vol20_ann"]).mean() * 100)
    for s, ser in data.fred.items():
        snap[f"{s}_last"] = [str(ser.index[-1]), float(ser.iloc[-1])]
        snap[f"{s}_chg20obs"] = float(ser.iloc[-1] - ser.iloc[-21])
    snap["events_in_competition_month_us_dates"] = {
        "FOMC": [d for d in L.FOMC if "2026-10-27" <= d <= "2026-11-27"],
        "note": "CPI / payroll / mega-cap earnings dates for Nov 2026 must be verified from official calendars; "
                "US midterm election 2026-11-03 falls inside the window"}
    (OUT / "regime_snapshot.json").write_text(json.dumps(snap, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return snap


def main() -> int:
    data = L.Data()
    h = horizon(data)
    hs = horizon_summary(h)
    (OUT / "horizon_summary.json").write_text(json.dumps(hs, indent=1, default=float), encoding="utf-8")
    print("HORIZON_MISMATCH", hs["HORIZON_MISMATCH"], json.dumps(hs["rule_inputs"], default=float))
    starts = h[h["set"] == "DENSE24"]["start"].tolist()
    ic = ic_study(data, starts)
    print(ic.groupby(["signal", "pool", "h", "period"])["ic"].agg(["mean", "count"]).round(4).to_string())
    ms = market_signals(data, h)
    print(ms[ms["p"] < 0.10].to_string())
    print(json.dumps(regime_snapshot(data), ensure_ascii=False, indent=1, default=str)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
