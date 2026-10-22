"""RESEARCH ONLY. Risk Overlay signals, votes, triggers and the daily state machine (ACCEPTANCE_GATE.md §2–§5).

Every value for trade date T is what a 07:00 decision on T could see: price-derived signals use closes through T-1
(shift 1); overnight series are merged as-of on `available_at` <= T 07:00 and dropped when older than 96 hours.
Not used by production code.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STATES = ["NORMAL", "CAUTION", "RISK_OFF"]
STALE_H = 96

VOTES = {
    "v_breadth": lambda s: s["breadth"] < 0.35,
    "v_trend": lambda s: s["ew_trend20"] < -0.05,
    "v_dd": lambda s: s["ew_dd60"] < -0.10,
    "v_vol": lambda s: s["ew_vol20"] > 0.30,
    "v_sox": lambda s: s["SOX"] <= -0.03,
    "v_ndx": lambda s: s["NDX"] <= -0.02,
    "v_spx": lambda s: s["SPX"] <= -0.015,
    "v_tsm": lambda s: s["TSM"] <= -0.03,
    "v_txf": lambda s: s["TXF_NIGHT"] <= -0.015,
    "v_fx": lambda s: s["USDTWD_5d"] >= 0.01,
}

TRIGGERS = {   # raw level per day: 0 NORMAL, 1 CAUTION, 2 RISK_OFF
    "SLOW": lambda v: np.where((v.v_trend & v.v_breadth) | v.v_dd, 2, 0),
    "FAST": lambda v: np.where(v.v_txf | (v.v_sox & v.v_tsm), 2, 0),
    "VOL": lambda v: np.where(v.v_vol | v.v_dd, 2, 0),
    "VOTE": lambda v: np.where(v.n_votes >= 3, 2, 0),
    "GRADED": lambda v: np.where(v.n_votes >= 4, 2, np.where(v.n_votes >= 2, 1, 0)),
}

ACTIONS = {
    "A": {"CAUTION": {"cash": [0.08, 0.12], "allow_new": True, "vol_cap": None},
          "RISK_OFF": {"cash": [0.12, 0.16], "allow_new": True, "vol_cap": None}, "max_delever": 0.10},
    "B": {"CAUTION": {"cash": None, "allow_new": False, "vol_cap": None},
          "RISK_OFF": {"cash": None, "allow_new": False, "vol_cap": None}, "max_delever": 0.10},
    "C": {"CAUTION": {"cash": [0.10, 0.14], "allow_new": True, "vol_cap": None},
          "RISK_OFF": {"cash": [0.15, 0.19], "allow_new": True, "vol_cap": 0.06}, "max_delever": 0.15},
    "D": {"CAUTION": {"cash": [0.08, 0.12], "allow_new": True, "vol_cap": None},
          "RISK_OFF": {"cash": [0.15, 0.19], "allow_new": True, "vol_cap": 0.06}, "max_delever": 0.15},
}

CANDIDATES = {"A_SLOW": ("A", "SLOW"), "A_FAST": ("A", "FAST"), "A_VOL": ("A", "VOL"), "A_VOTE": ("A", "VOTE"),
              "B_VOTE": ("B", "VOTE"), "C_FAST": ("C", "FAST"), "C_VOTE": ("C", "VOTE"), "D_GRADED": ("D", "GRADED")}


def build_signals(store, extra_dates: list[str] | None = None) -> pd.DataFrame:
    uni = set(pd.read_csv(ROOT / "config" / "universe_150.csv", dtype=str, encoding="utf-8-sig")["ticker"])
    px = store.load("daily_prices")
    px = px[px["ticker"].astype(str).isin(uni)]
    close = px.pivot_table(index="date", columns="ticker", values="close").sort_index()
    dates = list(close.index) + [d for d in (extra_dates or []) if d > close.index[-1]]
    close = close.reindex(dates)
    r = close.pct_change(fill_method=None)
    ew = r.median(axis=1)       # universe index proxy = daily cross-sectional MEDIAN return (same as pipeline fs.market)
    idx = (1 + ew.fillna(0)).cumprod()
    s = pd.DataFrame(index=dates)
    above = (close > close.rolling(20, min_periods=15).mean()).where(close.notna())
    s["breadth"] = above.mean(axis=1).shift(1)
    s["ew_trend20"] = (idx / idx.shift(20) - 1).shift(1)
    s["ew_dd60"] = (idx / idx.rolling(60, min_periods=20).max() - 1).shift(1)
    s["ew_vol20"] = (ew.rolling(20).std() * np.sqrt(252)).shift(1)
    s["ew_ret5"] = (idx / idx.shift(5) - 1).shift(1)
    # in-sample last day of prices has no "next" decision unless extra_dates given; first rows NaN by design
    m = store.load("market_overnight").copy()
    m["ts"] = pd.to_datetime(m["available_at"].astype(str).str[:19])
    dec = pd.DataFrame({"date": dates, "decision": pd.to_datetime(pd.Series(dates)) + pd.Timedelta(hours=7)})
    for sym in ("SOX", "NDX", "SPX", "TSM", "TXF_NIGHT", "USDTWD"):
        g = m[m["symbol"] == sym].sort_values("ts")[["ts", "ret", "close"]].dropna(subset=["ts"]).copy()
        if sym == "USDTWD":
            g["ret"] = g["close"] / g["close"].shift(5) - 1
        j = pd.merge_asof(dec, g, left_on="decision", right_on="ts", direction="backward")
        fresh = (j["decision"] - j["ts"]) <= pd.Timedelta(hours=STALE_H)
        s["USDTWD_5d" if sym == "USDTWD" else sym] = j["ret"].where(fresh).to_numpy()
        s[f"{sym}_ts"] = j["ts"].astype(str).to_numpy()
    return s


def votes(s: pd.DataFrame) -> pd.DataFrame:
    v = pd.DataFrame(index=s.index)
    for k, f in VOTES.items():
        v[k] = f(s).fillna(False).astype(bool)           # missing input -> no vote (never a risk-off trigger)
    v["n_votes"] = v[list(VOTES)].sum(axis=1)
    return v


def state_series(raw: np.ndarray, index, exit_confirm: int = 2) -> pd.Series:
    """Escalate immediately; de-escalate one level after `exit_confirm` consecutive lower raw days."""
    cur, calm, out = 0, 0, []
    for x in raw:
        if x > cur:
            cur, calm = int(x), 0
        elif x < cur:
            calm += 1
            if calm >= exit_confirm:
                cur, calm = cur - 1, 0
        else:
            calm = 0
        out.append(STATES[cur])
    return pd.Series(out, index=index)


def candidate_states(s: pd.DataFrame) -> pd.DataFrame:
    v = votes(s)
    out = pd.DataFrame(index=s.index)
    for trig, f in TRIGGERS.items():
        out[trig] = state_series(f(v), s.index)
    return out


def shifted(states: pd.Series, offset: int) -> pd.Series:
    """Placebo: circular shift of a state series along the trading calendar (keeps frequency and run lengths)."""
    return pd.Series(np.roll(states.to_numpy(), offset), index=states.index)
