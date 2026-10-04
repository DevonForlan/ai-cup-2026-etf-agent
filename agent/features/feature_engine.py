"""Feature engine: PITView -> per-ticker features for the 150-stock universe + market facts.

Reads ONLY through PITView. Missing data -> NaN (never fabricated).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from agent.config import ROOT
from agent.data.pit import PITView
from agent.features import institutional as INS
from agent.features import momentum as MOM
from agent.features import relative_strength as RS
from agent.features import revenue as REV
from agent.features import volatility as VOL
from agent.features import volume as VLM

FEATURES = ["ret_5d", "ret_20d", "ret_60d", "relative_strength_20d", "relative_strength_60d",
            "volume_ratio_5d", "volatility_20d", "distance_to_52w_high", "institutional_flow_5d",
            "institutional_flow_20d", "revenue_yoy", "revenue_mom"]
FEATURE_VERSION = "features-v2"   # v2: overnight/market regime inputs


@dataclass
class FeatureSet:
    trade_date: str
    as_of: str
    last_data_date: str | None
    features: pd.DataFrame                 # index ticker; FEATURES + aux columns
    market: dict = field(default_factory=dict)
    reads: list = field(default_factory=list)


def _panel(df: pd.DataFrame, col: str) -> pd.DataFrame:
    if len(df) == 0:
        return pd.DataFrame()
    p = df.pivot(index="date", columns="ticker", values=col).sort_index()
    return p.astype("float64")


def build_features(view: PITView, universe: list[str], trade_date: str) -> FeatureSet:
    prices = view.prices()
    prices = prices[prices["date"] < trade_date]          # strictly before T
    close = _panel(prices, "close").reindex(columns=universe)
    volume = _panel(prices, "volume").reindex(columns=universe)
    amount = _panel(prices, "amount").reindex(columns=universe)
    ins = view.institutional()
    ins = ins[ins["date"] < trade_date]
    tnet = _panel(ins, "total_net").reindex(columns=universe)
    if len(tnet):
        tnet = tnet.reindex(close.index)

    f = pd.DataFrame(index=pd.Index(universe, name="ticker"))
    last = close.index.max() if len(close) else None
    if last is not None:
        f["close_prev"] = close.ffill().iloc[-1]          # last traded close (suspensions)
        f["vwap_prev"] = (amount.iloc[-1] / volume.iloc[-1]).replace([np.inf, -np.inf], np.nan)
        f["n_obs"] = close.notna().sum()
        f["ret_1d"] = MOM.trailing_return(close, 1)
        f["ret_5d"] = MOM.trailing_return(close, 5)
        f["ret_20d"] = MOM.trailing_return(close, 20)
        f["ret_60d"] = MOM.trailing_return(close, 60)
        f["relative_strength_20d"] = RS.relative_strength(close, 20)
        f["relative_strength_60d"] = RS.relative_strength(close, 60)
        f["volume_ratio_5d"] = VLM.volume_ratio(volume, 5, 60)
        f["avg_value_20d"] = VLM.avg_traded_value(amount, 20)
        f["volatility_20d"] = VOL.realized_vol(close, 20)
        f["distance_to_52w_high"] = MOM.distance_to_high(close, 250, 120)
        ma20 = close.tail(20).mean() if len(close) >= 20 else pd.Series(np.nan, index=universe)
        f["above_ma20"] = (close.iloc[-1] > ma20).where(ma20.notna())
    else:
        for c in ["close_prev", "vwap_prev", "n_obs", "ret_1d", "ret_5d", "ret_20d", "ret_60d",
                  "relative_strength_20d", "relative_strength_60d", "volume_ratio_5d", "avg_value_20d",
                  "volatility_20d", "distance_to_52w_high", "above_ma20"]:
            f[c] = np.nan
    if len(tnet) and tnet.notna().any().any():
        f["inst_net_5d_shares"] = INS.net_flow_shares(tnet, 5)
        f["inst_net_20d_shares"] = INS.net_flow_shares(tnet, 20)
        f["institutional_flow_5d"] = INS.flow_intensity(tnet, volume, 5)
        f["institutional_flow_20d"] = INS.flow_intensity(tnet, volume, 20)
    else:
        for c in ["inst_net_5d_shares", "inst_net_20d_shares", "institutional_flow_5d", "institutional_flow_20d"]:
            f[c] = np.nan
    rv = REV.revenue_features(view.monthly_revenue(), universe)
    f = f.join(rv)
    for c in FEATURES:
        if c not in f:
            f[c] = np.nan
    f = f.replace([np.inf, -np.inf], np.nan)

    market = {}
    if last is not None:
        market = {
            "last_data_date": last,
            "universe_median_ret_1d": float(f["ret_1d"].median(skipna=True)),
            "universe_median_ret_5d": float(f["ret_5d"].median(skipna=True)),
            "universe_median_ret_20d": float(f["ret_20d"].median(skipna=True)),
            "breadth_above_ma20": float(f["above_ma20"].dropna().astype(float).mean()) if f["above_ma20"].notna().any() else float("nan"),
            "advancers_1d": int((f["ret_1d"] > 0).sum()),
            "decliners_1d": int((f["ret_1d"] < 0).sum()),
            "n_with_price": int(f["close_prev"].notna().sum()),
        }
        # equal-weight universe index (TAIEX proxy): 20d trend and 20d realised vol
        ew = close.pct_change(fill_method=None).median(axis=1).dropna()
        if len(ew) >= 20:
            market["ew_index_ret_20d"] = float((1 + ew.tail(20)).prod() - 1)
            market["ew_index_vol_20d"] = float(ew.tail(20).std() * np.sqrt(252))
    market.update(overnight_market_features(view, trade_date))
    return FeatureSet(trade_date, view.as_of, last, f, market, list(view.reads))


OVERNIGHT_MAP = {"SPX": "overnight_sp500_ret", "NDX": "overnight_nasdaq_ret", "SOX": "overnight_sox_ret",
                 "TSM": "tsm_adr_ret", "TXF_NIGHT": "taiex_futures_night_ret", "USDTWD": "usd_twd_ret"}


def overnight_market_features(view: PITView, trade_date: str) -> dict:
    """Latest visible overnight row per symbol with date <= T (PIT: available_at <= as_of).
    Stale rows (older than T by > 4 calendar days) are ignored."""
    try:
        o = view.table("market_overnight")
    except Exception:  # noqa: BLE001
        return {}
    if o is None or len(o) == 0:
        return {}
    o = o[o["date"] <= trade_date].sort_values("date")
    out = {}
    cutoff = (pd.Timestamp(trade_date) - pd.Timedelta(days=4)).strftime("%Y-%m-%d")
    for sym, name in OVERNIGHT_MAP.items():
        g = o[(o["symbol"] == sym) & (o["date"] >= cutoff)]
        if len(g) and pd.notna(g.iloc[-1]["ret"]):
            out[name] = float(g.iloc[-1]["ret"])
            out[name + "_date"] = str(g.iloc[-1]["date"])
            out[name + "_available_at"] = str(g.iloc[-1]["available_at"])
    return out


def save_features(fs: FeatureSet, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or ROOT / "data" / "processed" / "features"
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{fs.trade_date.replace('-', '')}.parquet"
    df = fs.features.copy()
    df["above_ma20"] = df["above_ma20"].astype("float64")
    df["revenue_ym"] = df["revenue_ym"].astype("string")
    df.reset_index().to_parquet(p, index=False)
    return p
