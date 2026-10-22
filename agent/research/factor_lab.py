"""RESEARCH ONLY (Factor Research / Quant Candidate v2). Not imported by production code.

Point-in-time candidate factor panels: panel[name] is a DataFrame (index = decision date T, columns = ticker)
whose value at T uses only information visible at T 07:00 (the decision time of the frozen pipeline):
price / volume / institutional rows of dates < T, monthly revenue and valuation rows with available_at <= T 07:00,
MOPS announcements published before T 07:00. Direction convention: every factor is defined so that its
HYPOTHESISED good side is high (e.g. lowvol = -volatility); the sign actually used in a candidate is chosen on the
Discovery period only.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class FactorDef:
    name: str
    family: str
    description: str
    pit: str                 # PIT_SAFE / PIT_CONDITIONAL / PIT_UNSAFE / DATA_UNAVAILABLE
    in_v1_features: bool = False   # True -> already a column of the frozen feature set (tested in Round 03)


FACTORS: list[FactorDef] = [
    # revenue quality
    FactorDef("rev_yoy", "revenue", "monthly revenue YoY (v1 base)", "PIT_SAFE", True),
    FactorDef("rev_mom", "revenue", "monthly revenue MoM (v1 base)", "PIT_SAFE", True),
    FactorDef("rev_yoy_accel", "revenue", "YoY(m) - YoY(m-1)", "PIT_SAFE"),
    FactorDef("rev_mom_accel", "revenue", "MoM(m) - MoM(m-1)", "PIT_SAFE"),
    FactorDef("rev_consec_yoy_pos", "revenue", "consecutive months with YoY > 0 (cap 12)", "PIT_SAFE"),
    FactorDef("rev_yoy_slope6", "revenue", "OLS slope of last 6 monthly YoY values", "PIT_SAFE"),
    FactorDef("rev_yoy_stab6", "revenue", "-std of last 6 monthly YoY values", "PIT_SAFE"),
    FactorDef("rev_3m_yoy", "revenue", "last 3 months revenue vs same 3 months a year earlier", "PIT_SAFE"),
    FactorDef("rev_ttm_yoy", "revenue", "trailing-12-month revenue growth", "PIT_SAFE"),
    FactorDef("rev_yoy_vs_trend", "revenue", "YoY minus mean of previous 6 YoY (self-surprise proxy)", "PIT_SAFE"),
    # institutional flow (net shares / 20D volume)
    FactorDef("foreign_5", "institutional", "foreign net 5D / volume 20D", "PIT_SAFE"),
    FactorDef("foreign_20", "institutional", "foreign net 20D / volume 20D", "PIT_SAFE"),
    FactorDef("trust_5", "institutional", "investment-trust net 5D / volume 20D", "PIT_SAFE"),
    FactorDef("trust_20", "institutional", "investment-trust net 20D / volume 20D", "PIT_SAFE"),
    FactorDef("dealer_20", "institutional", "dealer net 20D / volume 20D", "PIT_SAFE"),
    FactorDef("inst_total_20", "institutional", "three-institution net 20D / volume 20D", "PIT_SAFE", True),
    FactorDef("foreign_accel", "institutional", "foreign 5D pace minus 20D pace", "PIT_SAFE"),
    # price trend
    FactorDef("mom_20", "trend", "20D return (rank-identical to 20D relative strength)", "PIT_SAFE", True),
    FactorDef("mom_60", "trend", "60D return", "PIT_SAFE", True),
    FactorDef("mom_60_skip5", "trend", "60D return excluding last 5 days", "PIT_SAFE"),
    FactorDef("reversal_5", "trend", "-5D return (short-term reversal)", "PIT_SAFE", True),
    FactorDef("dist_52w_high", "trend", "close / 250D high - 1", "PIT_SAFE", True),
    FactorDef("ma60_dist", "trend", "close / MA60 - 1", "PIT_SAFE"),
    FactorDef("trend_consistency", "trend", "share of up days in last 20", "PIT_SAFE"),
    # risk
    FactorDef("lowvol_20", "risk", "-20D volatility", "PIT_SAFE", True),
    FactorDef("low_downside_vol", "risk", "-20D downside deviation", "PIT_SAFE"),
    FactorDef("low_beta_60", "risk", "-60D beta vs EW universe", "PIT_SAFE"),
    FactorDef("low_idio_vol_60", "risk", "-60D idiosyncratic volatility", "PIT_SAFE"),
    FactorDef("low_mdd_60", "risk", "-60D rolling max drawdown", "PIT_SAFE"),
    # liquidity
    FactorDef("size_value_20", "liquidity", "log average traded value 20D (size proxy)", "PIT_SAFE"),
    FactorDef("illiquidity", "liquidity", "Amihud |ret|/value 20D", "PIT_SAFE"),
    FactorDef("abnormal_volume", "liquidity", "volume 5D / volume 60D", "PIT_SAFE"),
    # valuation / profitability (TWSE BWIBBU_d + TPEx peQryDate daily snapshots, published after close)
    FactorDef("earnings_yield", "valuation", "1 / PE (PE > 0)", "PIT_SAFE"),
    FactorDef("book_to_price", "valuation", "1 / PB", "PIT_SAFE"),
    FactorDef("div_yield", "valuation", "dividend yield", "PIT_SAFE"),
    FactorDef("roe_proxy", "quality", "PB / PE = TTM EPS / book value per share", "PIT_SAFE"),
    FactorDef("eps_ttm_growth", "quality", "TTM EPS change at the latest reported quarter vs previous quarter", "PIT_SAFE"),
    # events
    FactorDef("mops_count_5", "event", "MOPS material announcements in last 5 calendar days (from 2025-02 only)",
              "PIT_CONDITIONAL"),
]
NOT_AVAILABLE = {
    "gross_margin / operating_margin / net_margin / ROA / operating income growth / quality consistency":
        "quarterly statements not stored; MOPS XBRL is public but not collected (DATA_UNAVAILABLE)",
    "PEG / EV/EBITDA / FCF yield": "need EPS forecasts / debt / cash-flow statements (DATA_UNAVAILABLE)",
    "revenue surprise / earnings surprise": "need consensus estimates; no legal free PIT source (DATA_UNAVAILABLE)",
    "share turnover (volume / shares outstanding)": "shares outstanding history not stored (DATA_UNAVAILABLE)",
}


def _wide(df: pd.DataFrame, col: str) -> pd.DataFrame:
    return df.pivot(index="date", columns="ticker", values=col).sort_index().astype(float)


def build_panels(store, valuation_path: Path | None = None, universe: list[str] | None = None) -> tuple[dict, dict]:
    """Returns (panels, aux). aux: close, ret, eligible mask, decision dates."""
    uni = universe or sorted(pd.read_csv(ROOT / "config" / "universe_150.csv", dtype=str, encoding="utf-8-sig")["ticker"])
    p = store.load("daily_prices")
    p = p[p["ticker"].isin(uni)]
    close, vol, amt = _wide(p, "close"), _wide(p, "volume"), _wide(p, "amount")
    days = list(close.index)
    ret = close.pct_change(fill_method=None)
    ew = ret.median(axis=1)
    P: dict[str, pd.DataFrame] = {}
    # ---- computed THROUGH day d, then shifted one trading day -> value for decision date T uses <= T-1
    raw: dict[str, pd.DataFrame] = {}
    raw["mom_20"] = close / close.shift(20) - 1
    raw["mom_60"] = close / close.shift(60) - 1
    raw["mom_60_skip5"] = close.shift(5) / close.shift(60) - 1
    raw["reversal_5"] = -(close / close.shift(5) - 1)
    raw["dist_52w_high"] = close / close.rolling(250, min_periods=60).max() - 1
    raw["ma60_dist"] = close / close.rolling(60, min_periods=40).mean() - 1
    raw["trend_consistency"] = (ret > 0).astype(float).where(ret.notna()).rolling(20, min_periods=15).mean()
    raw["lowvol_20"] = -ret.rolling(20, min_periods=15).std()
    raw["low_downside_vol"] = -np.sqrt((ret.clip(upper=0) ** 2).rolling(20, min_periods=15).mean())
    var = ew.rolling(60, min_periods=40).var()
    beta = ret.apply(lambda s: s.rolling(60, min_periods=40).cov(ew)).div(var, axis=0)
    raw["low_beta_60"] = -beta
    resid = ret - beta.mul(ew, axis=0)
    raw["low_idio_vol_60"] = -resid.rolling(60, min_periods=40).std()
    roll_max = close.rolling(60, min_periods=40).max()
    raw["low_mdd_60"] = -(1 - close / roll_max).rolling(60, min_periods=40).max()
    raw["size_value_20"] = np.log(amt.rolling(20, min_periods=15).mean())
    raw["illiquidity"] = (ret.abs() / amt).rolling(20, min_periods=15).mean() * 1e9
    raw["abnormal_volume"] = vol.rolling(5, min_periods=4).mean() / vol.rolling(60, min_periods=40).mean()
    ins = store.load("institutional")
    ins = ins[ins["ticker"].isin(uni)]
    v20 = vol.rolling(20, min_periods=15).sum()
    for col, short in (("foreign_net", "foreign"), ("trust_net", "trust"), ("dealer_net", "dealer"),
                       ("total_net", "inst_total")):
        w = _wide(ins, col).reindex(index=close.index, columns=close.columns)
        raw[f"{short}_5"] = w.rolling(5, min_periods=4).sum() / v20
        raw[f"{short}_20"] = w.rolling(20, min_periods=15).sum() / v20
    raw["foreign_accel"] = raw["foreign_5"] / 5 - raw["foreign_20"] / 20
    for k in raw:
        if k not in ("dealer_5", "inst_total_5"):         # not in the candidate list
            P[k] = raw[k].shift(1)
    # eligibility like the frozen scorer: >= 21 observations and 20D average value >= 5e7 (through T-1)
    elig = (close.notna().cumsum() >= 21) & (amt.rolling(20, min_periods=15).mean() >= 5e7)
    aux = {"close": close, "ret": ret, "ew": ew, "eligible": elig.shift(1).fillna(False).astype(bool), "days": days}
    # ---- revenue (monthly; availability = available_at)
    P.update(_revenue_panels(store, close.index, uni))
    # ---- valuation
    if valuation_path and Path(valuation_path).exists():
        P.update(_valuation_panels(pd.read_parquet(valuation_path), close))
    # ---- events
    P["mops_count_5"] = _mops_panel(store, close.index, uni)
    return P, aux


def _asof_daily(rows: pd.DataFrame, value_cols: list[str], dates: pd.Index, uni: list[str]) -> dict[str, pd.DataFrame]:
    """rows: ticker, available_ts (Timestamp), value cols -> for each decision date T (07:00) the latest row per
    ticker with available_ts <= T 07:00."""
    out = {c: pd.DataFrame(np.nan, index=dates, columns=uni) for c in value_cols}
    dec = pd.DataFrame({"decision": pd.to_datetime(pd.Series(dates)) + pd.Timedelta(hours=7)})
    for t, g in rows.groupby("ticker"):
        if t not in uni:
            continue
        g = g.sort_values("available_ts")
        m = pd.merge_asof(dec, g, left_on="decision", right_on="available_ts", direction="backward")
        for c in value_cols:
            out[c][t] = m[c].to_numpy()
    return out


def _revenue_panels(store, dates: pd.Index, uni: list[str]) -> dict[str, pd.DataFrame]:
    r = store.load("monthly_revenue").copy()
    r["year"], r["month"] = r["year"].astype(int), r["month"].astype(int)
    r["period"] = r["year"] * 12 + r["month"]
    r = r.sort_values(["ticker", "period"])
    rows = []
    for t, g in r.groupby("ticker"):
        s = g.set_index("period")["revenue"].astype(float)
        yoy = s / s.reindex(s.index - 12).to_numpy() - 1
        mom = s / s.reindex(s.index - 1).to_numpy() - 1
        yoy = pd.Series(yoy.to_numpy(), index=s.index)
        mom = pd.Series(mom.to_numpy(), index=s.index)
        d = pd.DataFrame({"ticker": t, "period": s.index, "rev_yoy": yoy.values, "rev_mom": mom.values})
        d["rev_yoy_accel"] = yoy.values - yoy.reindex(s.index - 1).to_numpy()
        d["rev_mom_accel"] = mom.values - mom.reindex(s.index - 1).to_numpy()
        pos = (yoy > 0).astype(int).where(yoy.notna())
        consec, c = [], 0
        for v in pos.to_numpy():
            c = c + 1 if v == 1 else 0
            consec.append(min(c, 12))
        d["rev_consec_yoy_pos"] = consec
        hist = [yoy.reindex(s.index - k).to_numpy() for k in range(0, 6)]
        H = np.vstack(hist).T                                         # col k = YoY k months ago
        x = -np.arange(6)
        with np.errstate(all="ignore"):
            ok = (~np.isnan(H)).sum(axis=1) >= 4
            xm = np.nanmean(np.where(np.isnan(H), np.nan, x), axis=1)
            ym = np.nanmean(H, axis=1)
            slope = np.nansum((x - xm[:, None]) * (H - ym[:, None]), axis=1) / np.nansum(
                np.where(np.isnan(H), np.nan, (x - xm[:, None]) ** 2), axis=1)
            d["rev_yoy_slope6"] = np.where(ok, slope, np.nan)
            d["rev_yoy_stab6"] = np.where(ok, -np.nanstd(H, axis=1), np.nan)
            prev6 = np.vstack([yoy.reindex(s.index - k).to_numpy() for k in range(1, 7)]).T
            d["rev_yoy_vs_trend"] = yoy.values - np.where((~np.isnan(prev6)).sum(axis=1) >= 4, np.nanmean(prev6, axis=1), np.nan)
        s3 = pd.Series([s.reindex(range(p - 2, p + 1)).sum(min_count=3) for p in s.index], index=s.index)
        s3l = pd.Series([s.reindex(range(p - 14, p - 11)).sum(min_count=3) for p in s.index], index=s.index)
        d["rev_3m_yoy"] = (s3 / s3l - 1).to_numpy()
        s12 = pd.Series([s.reindex(range(p - 11, p + 1)).sum(min_count=12) for p in s.index], index=s.index)
        s12l = pd.Series([s.reindex(range(p - 23, p - 11)).sum(min_count=12) for p in s.index], index=s.index)
        d["rev_ttm_yoy"] = (s12 / s12l - 1).to_numpy()
        d["available_ts"] = pd.to_datetime(g["available_at"].astype(str).str[:19]).to_numpy()
        rows.append(d)
    R = pd.concat(rows, ignore_index=True)
    R["available_ts"] = pd.to_datetime(R["available_ts"])
    cols = ["rev_yoy", "rev_mom", "rev_yoy_accel", "rev_mom_accel", "rev_consec_yoy_pos", "rev_yoy_slope6",
            "rev_yoy_stab6", "rev_3m_yoy", "rev_ttm_yoy", "rev_yoy_vs_trend"]
    R = R.replace([np.inf, -np.inf], np.nan)
    # latest PERIOD among rows visible at T (a late filer cannot pull an older month over a newer one)
    R = R.sort_values(["ticker", "available_ts", "period"])
    R["period_max"] = R.groupby("ticker")["period"].cummax()
    R = R[R["period"] == R["period_max"]]
    return _asof_daily(R, cols, dates, uni)


def _valuation_panels(v: pd.DataFrame, close: pd.DataFrame) -> dict[str, pd.DataFrame]:
    v = v.copy()
    ey = np.where((v["pe"] > 0), 1 / v["pe"], np.nan)
    v["earnings_yield"] = ey
    v["book_to_price"] = np.where(v["pb"] > 0, 1 / v["pb"], np.nan)
    v["roe_proxy"] = np.where((v["pe"] > 0) & (v["pb"] > 0), v["pb"] / v["pe"], np.nan)
    v["div_yield"] = v["div_yield"]
    # TTM EPS = close / PE; growth when the reported quarter changes (published-at-date snapshot)
    pc = close.stack().rename("close").reset_index()
    v = v.merge(pc, on=["date", "ticker"], how="left")
    v["eps_ttm"] = np.where(v["pe"] > 0, v["close"] / v["pe"], np.nan)
    v = v.sort_values(["ticker", "date"])
    out_g = []
    for t, g in v.groupby("ticker"):
        q = g.groupby("fin_quarter", sort=False)["eps_ttm"].first()
        qg = (q / q.shift(1) - 1).replace([np.inf, -np.inf], np.nan)
        out_g.append(g["fin_quarter"].map(qg))
    v["eps_ttm_growth"] = pd.concat(out_g)
    P = {}
    for c in ("earnings_yield", "book_to_price", "div_yield", "roe_proxy", "eps_ttm_growth"):
        w = v.pivot(index="date", columns="ticker", values=c).reindex(index=close.index, columns=close.columns)
        P[c] = w.astype(float).shift(1)                    # published after close of d -> usable from d+1
    return P


def _mops_panel(store, dates: pd.Index, uni: list[str]) -> pd.DataFrame:
    m = store.load("material_info")
    m = m[m["ticker"].isin(uni)].copy()
    m["ts"] = pd.to_datetime(m["published_at"].astype(str).str[:19])
    out = pd.DataFrame(np.nan, index=dates, columns=uni)
    first = m["ts"].min()
    for d in dates:
        dec = pd.Timestamp(d) + pd.Timedelta(hours=7)
        if pd.isna(first) or dec - pd.Timedelta(days=5) < first:
            continue                                         # no coverage -> NaN, not zero
        w = m[(m["ts"] < dec) & (m["ts"] >= dec - pd.Timedelta(days=5))]
        cnt = w.groupby("ticker").size()
        out.loc[d] = 0.0
        out.loc[d, cnt.index] = cnt.values
    return out


# ----------------------------------------------------------------------------- IC
def forward_returns(close: pd.DataFrame, h: int) -> pd.DataFrame:
    """Return from close(T-1) to close(T+h-1), indexed by decision date T."""
    return close.shift(-(h - 1)) / close.shift(1) - 1


def daily_ic(f: pd.DataFrame, fwd: pd.DataFrame, elig: pd.DataFrame, min_n: int = 30) -> pd.Series:
    out = {}
    for d in f.index:
        if d not in fwd.index:
            continue
        m = elig.loc[d] if d in elig.index else None
        x, y = f.loc[d], fwd.loc[d]
        ok = x.notna() & y.notna() & (m if m is not None else True)
        if ok.sum() < min_n:
            continue
        out[d] = x[ok].rank().corr(y[ok].rank())
    return pd.Series(out, dtype=float)


def base_score(P: dict, d) -> pd.Series:
    """Frozen v1 composite at date d: 0.7 pct(rev_yoy) + 0.3 pct(rev_mom), NaN -> 0.5 (as ranking.score)."""
    a = P["rev_yoy"].loc[d].rank(pct=True).fillna(0.5)
    b = P["rev_mom"].loc[d].rank(pct=True).fillna(0.5)
    return 0.7 * a + 0.3 * b


def incremental_ic(P: dict, name: str, sign: int, w: float, fwd: pd.DataFrame, elig: pd.DataFrame,
                   dates) -> dict:
    """IC(base + w*sign*pct(F)) - IC(base), and IC of F residualised on the base score (partial information)."""
    rows = []
    for d in dates:
        if d not in fwd.index:
            continue
        m = elig.loc[d]
        y = fwd.loc[d]
        b = base_score(P, d)
        f = P[name].loc[d]
        fp = (sign * f).rank(pct=True).fillna(0.5)
        ok = m & y.notna()
        if ok.sum() < 30:
            continue
        comp = b + w * fp
        ic_b = b[ok].rank().corr(y[ok].rank())
        ic_c = comp[ok].rank().corr(y[ok].rank())
        okf = ok & f.notna()
        if okf.sum() >= 30:
            rb_, rf = b[okf].rank(), (sign * f[okf]).rank()
            beta = np.polyfit(rb_, rf, 1)
            res = rf - np.polyval(beta, rb_)
            ic_p = pd.Series(res).rank().corr(y[okf].rank())
        else:
            ic_p = np.nan
        rows.append((d, ic_b, ic_c, ic_p))
    df = pd.DataFrame(rows, columns=["date", "ic_base", "ic_comp", "ic_partial"]).set_index("date")
    return {"n": len(df), "ic_base": df["ic_base"].mean(), "ic_comp": df["ic_comp"].mean(),
            "delta_ic": (df["ic_comp"] - df["ic_base"]).mean(), "partial_ic": df["ic_partial"].mean(),
            "delta_ic_t": _t(df["ic_comp"] - df["ic_base"]), "partial_ic_t": _t(df["ic_partial"])}


def _t(s: pd.Series, lag: int = 0) -> float:
    s = s.dropna()
    if len(s) < 5 or s.std() == 0:
        return float("nan")
    return float(s.mean() / s.std() * np.sqrt(len(s)))
