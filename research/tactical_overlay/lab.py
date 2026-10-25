"""RESEARCH ONLY (Issue #14). Point-in-time data, signals, replay engine and overlays (PRE_REGISTRATION.md §1, §5).

Timing: the target for trade date T may use Taiwan prices / flows through T-1 close and overnight data whose
`available_at` <= T 07:00. The replay trades at T's close (the frozen pipeline trades at T's VWAP; gate R0
measures the difference). Never imported by production code; the frozen config is never written.
"""
from __future__ import annotations

import csv
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FEE, TAX, THRESH, INIT = 0.001425, 0.003, 0.0025, 1e9
TSMC, TSMC_CAP, OTHER_CAP, CASH_MAX, MIN_NAMES = "2330", 0.235, 0.09, 0.25, 20

# ---------------------------------------------------------------- event calendar (US dates; approximate, public)
FOMC = ["2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12", "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
        "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
        "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09"]
CPI = ["2024-01-11", "2024-02-13", "2024-03-12", "2024-04-10", "2024-05-15", "2024-06-12", "2024-07-11", "2024-08-14",
       "2024-09-11", "2024-10-10", "2024-11-13", "2024-12-11", "2025-01-15", "2025-02-12", "2025-03-12", "2025-04-10",
       "2025-05-13", "2025-06-11", "2025-07-15", "2025-08-12", "2025-09-11", "2025-10-24", "2025-12-18",
       "2026-01-13", "2026-02-11", "2026-03-11", "2026-04-10", "2026-05-12", "2026-06-10", "2026-07-14", "2026-08-12",
       "2026-09-11", "2026-10-14"]
NFP = ["2024-01-05", "2024-02-02", "2024-03-08", "2024-04-05", "2024-05-03", "2024-06-07", "2024-07-05", "2024-08-02",
       "2024-09-06", "2024-10-04", "2024-11-01", "2024-12-06", "2025-01-10", "2025-02-07", "2025-03-07", "2025-04-04",
       "2025-05-02", "2025-06-06", "2025-07-03", "2025-08-01", "2025-09-05", "2025-11-20", "2025-12-16",
       "2026-01-09", "2026-02-06", "2026-03-06", "2026-04-03", "2026-05-08", "2026-06-05", "2026-07-02", "2026-08-07",
       "2026-09-04", "2026-10-02"]
FRED_LAG_DAYS = {"DGS10": 2, "DCOILWTICO": 3, "DTWEXBGS": 7, "VIXCLS": 1}


def universe() -> list[str]:
    with open(ROOT / "config" / "universe_150.csv", encoding="utf-8-sig") as f:
        return [r["ticker"] for r in csv.DictReader(f)]


def sector_map() -> dict[str, str]:
    with open(HERE / "sector_map.csv", encoding="utf-8") as f:
        return {r["ticker"]: r["sector"] for r in csv.DictReader(f)}


class Data:
    """All PIT inputs, loaded once."""

    def __init__(self):
        from agent.data.loaders import HistoryStore
        st = HistoryStore(ROOT / "data" / "history")
        uni = set(universe())
        px = st.load("daily_prices")
        px = px[px["ticker"].astype(str).isin(uni)].copy()
        px["ticker"] = px["ticker"].astype(str)
        self.close = px.pivot_table(index="date", columns="ticker", values="close").sort_index().ffill()
        self.volume = px.pivot_table(index="date", columns="ticker", values="volume").sort_index()
        vw = px.pivot_table(index="date", columns="ticker", values="vwap").sort_index()
        self.vwap = vw.reindex_like(self.close).fillna(self.close)
        self.dates = list(self.close.index)
        self.ret = self.close.pct_change(fill_method=None)
        ins = st.load("institutional")
        ins = ins[ins["ticker"].astype(str).isin(uni)].copy()
        ins["ticker"] = ins["ticker"].astype(str)
        self.foreign = ins.pivot_table(index="date", columns="ticker", values="foreign_net").reindex(self.dates)
        ca = st.load("corporate_actions")
        ca = ca[(ca["ticker"].astype(str).isin(uni)) & (ca["cash_dividend"].fillna(0) > 0)]
        self.div = {(r.ex_date, str(r.ticker)): float(r.cash_dividend) for r in ca.itertuples()}
        sd = st.load("corporate_actions")
        sd = sd[(sd["ticker"].astype(str).isin(uni)) & (sd["stock_dividend_per_share"].fillna(0) > 0)]
        self.stock_div = {(r.ex_date, str(r.ticker)): float(r.stock_dividend_per_share) for r in sd.itertuples()}
        self.overnight = st.load("market_overnight")
        self.sector = sector_map()
        self.fred = {}
        for s in FRED_LAG_DAYS:
            p = ROOT / "data" / "research" / "tactical" / f"fred_{s}.csv"
            if p.exists():
                f = pd.read_csv(p)
                f.columns = ["date", "value"]
                f["value"] = pd.to_numeric(f["value"], errors="coerce")
                self.fred[s] = f.dropna().set_index("date")["value"]
        self.sig = self._signals()

    # ------------------------------------------------------------ signals for decision date T (index = T)
    def _signals(self) -> dict:
        c = self.close
        s = {}
        s["mom20"] = (c / c.shift(20) - 1).shift(1)
        s["mom60"] = (c / c.shift(60) - 1).shift(1)
        s["vol20"] = self.ret.rolling(20, min_periods=15).std().shift(1)
        vol = self.volume.reindex(c.index)
        f = self.foreign.reindex(c.index)
        s["flow20"] = (f.rolling(20, min_periods=15).sum() / vol.rolling(20, min_periods=15).sum()).shift(1)
        s["flow5"] = (f.rolling(5, min_periods=4).sum() / vol.rolling(5, min_periods=4).sum()).shift(1)
        above = (c > c.rolling(20, min_periods=15).mean()).where(c.notna())
        mk = pd.DataFrame(index=c.index)
        mk["breadth"] = above.mean(axis=1).shift(1)
        ew = self.ret.median(axis=1)
        idx = (1 + ew.fillna(0)).cumprod()
        mk["ew_trend20"] = (idx / idx.shift(20) - 1).shift(1)
        mk["ew_vol20"] = (ew.rolling(20).std() * np.sqrt(252)).shift(1)
        mk["ew_dd60"] = (idx / idx.rolling(60, min_periods=20).max() - 1).shift(1)
        dec = pd.DataFrame({"date": c.index, "decision": pd.to_datetime(pd.Series(c.index)) + pd.Timedelta(hours=7)})
        m = self.overnight.copy()
        m["ts"] = pd.to_datetime(m["available_at"].astype(str).str[:19])
        for sym, n in (("SOX", 20), ("SOX", 5), ("TSM", 5), ("NDX", 20), ("SPX", 20), ("USDTWD", 20)):
            g = m[m["symbol"] == sym].sort_values("ts")[["ts", "close"]].dropna().copy()
            g[f"r{n}"] = g["close"] / g["close"].shift(n) - 1
            j = pd.merge_asof(dec, g[["ts", f"r{n}"]], left_on="decision", right_on="ts", direction="backward")
            fresh = (j["decision"] - j["ts"]) <= pd.Timedelta(hours=96)
            mk[f"{sym}_{n}"] = np.where(fresh, j[f"r{n}"], np.nan)
        for name, ser in self.fred.items():
            lag = FRED_LAG_DAYS[name]
            vals = []
            for d in c.index:
                cut = (pd.Timestamp(d) - timedelta(days=lag)).strftime("%Y-%m-%d")
                hist = ser[ser.index <= cut]
                vals.append((hist.iloc[-1], hist.iloc[-21] if len(hist) > 21 else np.nan) if len(hist) else (np.nan, np.nan))
            mk[f"{name}_lvl"] = [v[0] for v in vals]
            mk[f"{name}_chg20"] = [v[0] - v[1] for v in vals]
        mk["event_next"] = [self._event_on(d) for d in c.index]
        s["market"] = mk
        return s

    def _event_on(self, d: str) -> bool:
        """True if a US FOMC / CPI / payroll release happens on US date d (its Taiwan reaction is on the next
        Taiwan session), i.e. de-risk positions held over Taiwan close d -> close d+1."""
        return d in set(FOMC) | set(CPI) | set(NFP)

    def sector_returns(self, d: str, col: str) -> pd.Series:
        m = self.sig[col].loc[d] if d in self.sig[col].index else pd.Series(dtype=float)
        df = pd.DataFrame({"r": m, "sec": pd.Series(self.sector)}).dropna()
        g = df.groupby("sec")["r"].agg(["mean", "count"])
        return g[g["count"] >= 3]["mean"]


# ---------------------------------------------------------------- frozen run loading
def load_run(run_dir: Path) -> dict:
    daily = pd.read_csv(run_dir / "daily.csv", encoding="utf-8-sig")
    days, weights, inv = [], [], []
    for d in daily["date"].astype(str):
        st = json.loads((run_dir / "settlement" / f"{d}.json").read_text(encoding="utf-8"))
        days.append(d)
        weights.append({str(t): int(n) for t, n in st["holdings"].items() if int(n) > 0})
    return {"days": days, "shares": weights, "nav": daily["nav"].astype(float).tolist(),
            "cash": daily["cash"].astype(float).tolist()}


def frozen_weights(run: dict, data: Data) -> list[dict]:
    out = []
    for d, sh, nav in zip(run["days"], run["shares"], run["nav"]):
        cl = data.close.loc[d]
        out.append({t: n * float(cl[t]) / nav for t, n in sh.items()})
    return out


# ---------------------------------------------------------------- caps / transforms
def enforce(w: dict, invested: float) -> dict:
    """Scale to `invested`, apply 2330 / other caps (excess redistributed pro rata to uncapped names), cash < 25%."""
    invested = min(max(invested, 1 - CASH_MAX + 1e-6), 0.995)
    w = {t: max(v, 0.0) for t, v in w.items() if v > 0}
    if not w:
        return w
    tot = sum(w.values())
    w = {t: v / tot * invested for t, v in w.items()}
    for _ in range(20):
        caps = {t: (TSMC_CAP if t == TSMC else OTHER_CAP) for t in w}
        over = {t: v - caps[t] for t, v in w.items() if v > caps[t] + 1e-12}
        if not over:
            break
        excess = sum(over.values())
        for t in over:
            w[t] = caps[t]
        free = {t: v for t, v in w.items() if t not in over and v < caps[t] - 1e-12}
        fs = sum(free.values())
        if fs <= 0:
            break
        for t, v in free.items():
            w[t] = v + excess * v / fs
    return w


def tilt(w: dict, score: dict, up: float = 1.25, down: float = 0.75) -> dict:
    s = {t: score.get(t) for t in w}
    valid = [t for t in w if s[t] is not None and not pd.isna(s[t])]
    if len(valid) < 3:
        return dict(w)
    order = sorted(valid, key=lambda t: s[t])
    k = len(order) // 3
    mult = {t: 1.0 for t in w}
    for t in order[:k]:
        mult[t] = down
    for t in order[-k:]:
        mult[t] = up
    return {t: v * mult[t] for t, v in w.items()}


# ---------------------------------------------------------------- overlays (fixed parameters, PRE_REGISTRATION §5)
def overlay_fn(name: str, data: Data, rng: np.random.Generator | None = None, shift: int = 0):
    """Returns f(day_index, date, base_weights) -> target weights. `rng` = name-placebo, `shift` = time-placebo."""
    mk = data.sig["market"]
    dates = data.dates

    def mdate(d):          # time-shifted signal date for timing placebos
        if not shift:
            return d
        i = dates.index(d)
        return dates[(i - shift) % len(dates)]

    def stock_score(col):
        def f(d, w):
            row = data.sig[col].loc[d] if d in data.sig[col].index else pd.Series(dtype=float)
            sc = {t: (row.get(t) if t in row.index else None) for t in w}
            if rng is not None:
                vals = list(sc.values())
                rng.shuffle(vals)
                sc = dict(zip(sc.keys(), vals))
            return sc
        return f

    inv_of = lambda w: sum(w.values())  # noqa: E731

    if name in ("F2a", "F2b", "F3a", "F3b"):
        col = {"F2a": "mom20", "F2b": "mom60", "F3a": "flow20", "F3b": "flow5"}[name]
        sf = stock_score(col)
        return lambda i, d, w: enforce(tilt(w, sf(d, w)), inv_of(w))
    if name == "F4a":
        def f4a(i, d, w):
            v = data.sig["vol20"].loc[d]
            iv = {t: (1 / v[t] if t in v.index and v[t] > 0 else None) for t in w}
            if rng is not None:
                vals = list(iv.values()); rng.shuffle(vals); iv = dict(zip(iv.keys(), vals))
            ok = {t: x for t, x in iv.items() if x is not None}
            if len(ok) < 3:
                return dict(w)
            tot_w, tot_iv = inv_of(w), sum(ok.values())
            nw = {t: 0.5 * w[t] + 0.5 * (ok[t] / tot_iv * tot_w if t in ok else w[t]) for t in w}
            return enforce(nw, tot_w)
        return f4a
    if name == "F4b":
        def f4b(i, d, w):
            v = data.sig["vol20"].loc[d].dropna()
            hi = set(v[v >= v.quantile(0.8)].index)
            if rng is not None:
                hi = set(rng.choice(list(w), size=min(len(w), max(1, len(hi & set(w)))), replace=False))
            return enforce({t: x * (0.5 if t in hi else 1.0) for t, x in w.items()}, inv_of(w))
        return f4b
    if name in ("F5a", "F5b"):
        col = "mom20" if name == "F5a" else "mom60"

        def f5(i, d, w):
            sr = data.sector_returns(d, col).sort_values()
            if len(sr) < 6:
                return dict(w)
            secs = list(sr.index)
            if rng is not None:
                rng.shuffle(secs)
            top, bot = set(secs[-3:]), set(secs[:3])
            m = {t: (1.25 if data.sector.get(t) in top else 0.75 if data.sector.get(t) in bot else 1.0) for t in w}
            return enforce({t: x * m[t] for t, x in w.items()}, inv_of(w))
        return f5
    if name in ("F6a", "F6b"):
        col = "SOX_20" if name == "F6a" else "TSM_5"

        def f6(i, d, w):
            x = mk.at[mdate(d), col]
            if pd.isna(x):
                return dict(w)
            k = 1.2 if x > 0 else 0.8
            return enforce({t: v * (k if data.sector.get(t) == "半導體業" else 1.0) for t, v in w.items()}, inv_of(w))
        return f6
    if name in ("F7a", "F7b"):
        cut = 0.10 if name == "F7a" else 0.20

        def f7(i, d, w):
            on = bool(mk.at[mdate(d), "event_next"])
            return enforce(w, inv_of(w) * (1 - cut)) if on else dict(w)
        return f7
    if name == "F8a":
        def f8a(i, d, w):
            x = mk.at[mdate(d), "USDTWD_20"]
            return enforce(w, inv_of(w) - 0.05) if (not pd.isna(x) and x > 0.01) else dict(w)
        return f8a
    if name == "F8b":
        def f8b(i, d, w):
            x = mk.at[mdate(d), "DGS10_chg20"] if "DGS10_chg20" in mk else np.nan
            return enforce(w, inv_of(w) - 0.05) if (not pd.isna(x) and x > 0.25) else dict(w)
        return f8b
    if name == "F1b":
        def f1b(i, d, w):
            x = mk.at[mdate(d), "breadth"]
            return enforce(w, 0.97) if (not pd.isna(x) and x >= 0.50) else dict(w)
        return f1b
    if name in ("F9a", "F9b"):
        def f9(i, d, w):
            names = sorted(w, key=lambda t: -w[t])
            if rng is not None:
                names = list(rng.permutation(names))
            keep = names[:MIN_NAMES] if len(names) > MIN_NAMES else names
            base = {t: w[t] for t in keep} if name == "F9a" else {t: w[t] ** 2 for t in keep}
            return enforce(base, inv_of(w))
        return f9
    raise KeyError(name)


VARIANTS = ["F1b", "F2a", "F2b", "F3a", "F3b", "F4a", "F4b", "F5a", "F5b", "F6a", "F6b", "F7a", "F7b", "F8a", "F8b",
            "F9a", "F9b"]
FAMILIES = {"F1": ["F1b"], "F2": ["F2a", "F2b"], "F3": ["F3a", "F3b"], "F4": ["F4a", "F4b"], "F5": ["F5a", "F5b"],
            "F6": ["F6a", "F6b"], "F7": ["F7a", "F7b"], "F8": ["F8a", "F8b"], "F9": ["F9a", "F9b"]}
NAME_PLACEBO = {"F2a", "F2b", "F3a", "F3b", "F4a", "F4b", "F5a", "F5b", "F9a", "F9b"}


# ---------------------------------------------------------------- replay engine
def replay(days: list[str], run: dict, data: Data, fn=None) -> dict:
    """Shares / cash book that mirrors the frozen mechanics: on day d trade at d's VWAP toward the target, mark at
    d's close. Baseline target = the frozen shares of day d. Overlay: the frozen holdings are converted to weights at
    d's VWAP (frozen invested share kept), transformed by `fn`, and converted back to shares. A name is traded only
    when |Δw| >= 0.25% NAV (exits / entries always). Official fees / tax. Dividends receivable are NOT added to
    NAV (same convention as the frozen daily NAV)."""
    cash, sh = INIT, {}
    navs, turn, cost_tot, viol, viol_off = [], 0.0, 0.0, 0, 0
    for i, d in enumerate(days):
        vw, cl = data.vwap.loc[d], data.close.loc[d]
        sh = {t: n * (1 + data.stock_div.get((d, t), 0.0)) for t, n in sh.items()}   # stock dividend: no trade
        nav_x = cash + sum(n * float(vw[t]) for t, n in sh.items())
        fsh = run["shares"][i]
        if fn is None:
            tgt_sh = dict(fsh)
        else:
            f_inv = sum(n * float(vw[t]) for t, n in fsh.items())
            f_nav = f_inv + run["cash"][i]
            base = {t: n * float(vw[t]) / f_nav for t, n in fsh.items()}
            tw = fn(i, d, base)
            tgt_sh = {t: x * nav_x / float(vw[t]) for t, x in tw.items() if x > 0}
        cur_w = {t: n * float(vw[t]) / nav_x for t, n in sh.items()}
        tgt_w = {t: n * float(vw[t]) / nav_x for t, n in tgt_sh.items()}
        if fn is None:                      # baseline: follow the frozen book exactly
            new = dict(tgt_sh)
        else:
            new = dict(sh)
            for t in set(sh) | set(tgt_sh):
                a_, b_ = cur_w.get(t, 0.0), tgt_w.get(t, 0.0)
                if b_ == 0.0:
                    new.pop(t, None)
                elif a_ == 0.0 or abs(b_ - a_) >= THRESH:
                    new[t] = tgt_sh[t]
        buy = sum(max(new.get(t, 0) - sh.get(t, 0), 0) * float(vw[t]) for t in set(sh) | set(new))
        sell = sum(max(sh.get(t, 0) - new.get(t, 0), 0) * float(vw[t]) for t in set(sh) | set(new))
        c = buy * FEE + sell * (FEE + TAX)
        cash += sell - buy - c
        cost_tot += c
        turn += (buy + sell) / nav_x
        sh = {t: n for t, n in new.items() if n > 0}
        nav = cash + sum(n * float(cl[t]) for t, n in sh.items())
        w = {t: n * float(cl[t]) / nav for t, n in sh.items()}
        if sh and (len(sh) < MIN_NAMES or len(sh) > 30 or cash / nav >= CASH_MAX
                   or any(v > (TSMC_CAP if t == TSMC else OTHER_CAP) + 0.005 for t, v in w.items())):
            viol += 1                      # frozen-strategy buffers (2330 23.5%, others 9%) + 0.5% tolerance
        if sh and (len(sh) < MIN_NAMES or len(sh) > 30 or cash / nav >= CASH_MAX
                   or any(v > (0.25 if t == TSMC else 0.10) for t, v in w.items())):
            viol_off += 1                  # OFFICIAL limits (2330 <= 25%, others <= 10%, cash < 25%, 20-30 names)
        navs.append(nav)
    return {"nav": navs, "turnover": turn, "cost": cost_tot, "violations": viol, "violations_official": viol_off}


def path_metrics(navs: list[float]) -> dict:
    nav = np.array([INIT] + list(navs))
    peak = np.maximum.accumulate(nav)
    r = nav[1:] / nav[:-1] - 1
    return {"ret": nav[-1] / INIT - 1, "mdd": float(-(nav / peak - 1).min()), "worst_1d": float(r.min()),
            "vol": float(r.std() * np.sqrt(252))}


# ---------------------------------------------------------------- benchmarks
def ew_universe(days: list[str], data: Data) -> float:
    i0 = data.dates.index(days[0])
    if i0 == 0:
        return np.nan
    p0, p1 = data.close.loc[data.dates[i0 - 1]], data.close.loc[days[-1]]
    r = (p1 / p0 - 1).dropna()
    return float(r.mean()) - FEE


def random_portfolios(days: list[str], data: Data, n: int = 500, k: int = 25, seed: int = 14,
                      exit_cost: bool = True) -> np.ndarray:
    rng = np.random.default_rng(seed)
    p0, p1 = data.close.loc[days[0]], data.close.loc[days[-1]]
    ok = [t for t in data.close.columns if not pd.isna(p0[t]) and not pd.isna(p1[t])]
    r = (p1[ok] / p0[ok] - 1).to_numpy()
    out = np.array([r[rng.choice(len(ok), size=k, replace=False)].mean() for _ in range(n)])
    return out - FEE - ((FEE + TAX) if exit_cost else 0.0)


def percentile(x: float, dist: np.ndarray) -> float:
    return float((dist < x).mean() * 100)


# ---------------------------------------------------------------- statistics (numpy only; no scipy in the venv)
class _Res:
    def __init__(self, statistic=None, pvalue=None):
        self.statistic, self.pvalue = statistic, pvalue


def spearmanr(x, y) -> _Res:
    x, y = pd.Series(np.asarray(x, dtype=float)), pd.Series(np.asarray(y, dtype=float))
    ok = ~(x.isna() | y.isna())
    if ok.sum() < 3:
        return _Res(np.nan)
    return _Res(float(x[ok].rank().corr(y[ok].rank())))


def signflip_p(x, n: int = 20000, seed: int = 14) -> float:
    """Two-sided sign-flip permutation p-value for mean(x) = 0 (paired differences)."""
    x = np.asarray(x, dtype=float)
    if len(x) == 0 or np.allclose(x, 0):
        return 1.0
    rng = np.random.default_rng(seed)
    obs = abs(x.mean())
    flips = rng.choice([-1.0, 1.0], size=(n, len(x)))
    return float(((np.abs((flips * x).mean(axis=1)) >= obs - 1e-15).sum() + 1) / (n + 1))
