"""Market Regime v0 — deterministic, no LLM.

Inputs (all PIT, visible before 08:55 on T): universe breadth (share above 20d MA), equal-weight
universe 20d trend and 20d volatility (TAIEX proxy), overnight SOX, TSM ADR, TAIEX night futures.
Each input -> bounded signal in [-1, 1]; regime_score = weighted mean of available signals.
Only SOFT parameters depend on the regime (cash target range); official limits are never touched.
"""
from __future__ import annotations

import math

DEFAULT = {
    "weights": {"breadth": 0.25, "trend": 0.20, "sox": 0.15, "tsm": 0.15, "night": 0.25},
    "scales": {"trend": 0.05, "sox": 0.02, "tsm": 0.02, "night": 0.01},
    "vol_high": 0.30,            # annualised EW-index vol above this -> -0.3 penalty
    "risk_on_score": 0.25,
    "risk_off_score": -0.25,
}


def _clip(x: float) -> float:
    return max(-1.0, min(1.0, x))


def _ok(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def regime_score(market: dict, params: dict | None = None) -> tuple[float | None, dict]:
    p = {**DEFAULT, **(params or {})}
    w, sc = p["weights"], p["scales"]
    sig = {}
    if _ok(market.get("breadth_above_ma20")):
        sig["breadth"] = _clip((market["breadth_above_ma20"] - 0.5) * 2)
    if _ok(market.get("ew_index_ret_20d")):
        sig["trend"] = _clip(market["ew_index_ret_20d"] / sc["trend"])
    if _ok(market.get("overnight_sox_ret")):
        sig["sox"] = _clip(market["overnight_sox_ret"] / sc["sox"])
    if _ok(market.get("tsm_adr_ret")):
        sig["tsm"] = _clip(market["tsm_adr_ret"] / sc["tsm"])
    if _ok(market.get("taiex_futures_night_ret")):
        sig["night"] = _clip(market["taiex_futures_night_ret"] / sc["night"])
    if not sig:
        return None, {}
    tw = sum(w[k] for k in sig)
    score = sum(w[k] * v for k, v in sig.items()) / tw
    if _ok(market.get("ew_index_vol_20d")) and market["ew_index_vol_20d"] > p["vol_high"]:
        score -= 0.3
        sig["vol_penalty"] = -0.3
    return max(-1.0, min(1.0, score)), sig


def market_regime(fs, overnight, cfg):
    """Returns (regime, stance, cash_range, why, score) or None when no inputs are available."""
    rc = cfg.get("regime", {})
    params = rc.get("v0", {})
    s, sig = regime_score(fs.market, params)
    if s is None:
        return None
    p = {**DEFAULT, **params}
    reg = "risk_on" if s >= p["risk_on_score"] else ("risk_off" if s <= p["risk_off_score"] else "neutral")
    stance = {"risk_on": "aggressive", "neutral": "neutral", "risk_off": "defensive"}[reg]
    lo, hi = rc["cash_by_regime"][reg]
    parts = "、".join(f"{k}={v:+.2f}" for k, v in sig.items())
    why = f"Regime v0 分數 {s:+.2f}（{parts}；門檻 ±{p['risk_on_score']:.2f}）"
    return reg, stance, (float(lo), float(hi)), why, round(s, 4)
