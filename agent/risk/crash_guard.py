"""Crash Guard — deterministic risk-off state machine (no LLM can trigger it).

Inputs (all PIT, from FeatureSet.market + previous settlement):
  universe 5d / 20d return (EW-150 proxy), 20d EW volatility, breadth, SOX, TSM ADR,
  TAIFEX night futures, portfolio drawdown from peak.
Each input contributes stress points (0/1/2) by thresholds; points -> raw state:
  NORMAL < caution_points <= CAUTION < risk_off_points <= RISK_OFF < crisis_points <= CRISIS
Hysteresis: escalation is immediate; de-escalation by ONE level only after `exit_confirm_days`
consecutive days whose raw state is lower than the current state.
Actions (soft only): cash target range, new entries on/off, high-vol weight cap, max
(de/re)leveraging per day. Official limits (cash < 25%, caps, 20-30 names) are never touched.
"""
from __future__ import annotations

import math

STATES = ["NORMAL", "CAUTION", "RISK_OFF", "CRISIS"]

DEFAULT = {
    "enabled": False,
    "thresholds": {   # (level1, level2): worse-than -> +1, +2 points
        "ret_5d": [-0.04, -0.07],
        "ret_20d": [-0.06, -0.12],
        "vol_20d": [0.30, 0.45],          # higher is worse
        "breadth": [0.30, 0.15],          # lower is worse
        "sox": [-0.03, -0.06],
        "tsm_adr": [-0.03, -0.06],
        "night": [-0.015, -0.03],
        "port_dd": [0.06, 0.10],          # higher is worse
    },
    "points": {"caution": 2, "risk_off": 4, "crisis": 7},
    "exit_confirm_days": 2,
    # Cash ceilings leave room for PASSIVE drift: in a crash NAV falls while cash stays, so the cash
    # ratio rises by itself (20% cash + 20% equity drop -> 23.8%). Rule §六(十四)(2) warns on the
    # settled ratio regardless of cause (Round 04 W2 finding).
    "states": {
        "NORMAL": {"cash": [0.03, 0.08], "allow_new": True, "vol_cap": None},
        "CAUTION": {"cash": [0.07, 0.10], "allow_new": True, "vol_cap": None},
        "RISK_OFF": {"cash": [0.10, 0.14], "allow_new": False, "vol_cap": 0.06},
        "CRISIS": {"cash": [0.12, 0.16], "allow_new": False, "vol_cap": 0.05},
    },
    "cash_hard_ceiling": 0.20,   # above this the guard re-invests in ANY state (official limit is 25%)
    "max_deleveraging_per_day": 0.10,
    "max_releveraging_per_day": 0.10,
    "high_vol_quantile": 0.80,
}


def _ok(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def params(cfg: dict) -> dict:
    p = {**DEFAULT, **(cfg.get("crash_guard") or {})}
    p["thresholds"] = {**DEFAULT["thresholds"], **(cfg.get("crash_guard", {}) or {}).get("thresholds", {})}
    p["states"] = {**DEFAULT["states"], **(cfg.get("crash_guard", {}) or {}).get("states", {})}
    p["points"] = {**DEFAULT["points"], **(cfg.get("crash_guard", {}) or {}).get("points", {})}
    return p


def portfolio_drawdown(nav_history: list, initial_nav) -> float:
    navs = ([float(initial_nav)] if initial_nav is not None else []) + [float(x[1]) for x in nav_history or []]
    if not navs:
        return 0.0
    peak = max(navs)
    return (peak - navs[-1]) / peak if peak > 0 else 0.0


def stress_points(market: dict, port_dd: float, p: dict) -> tuple[int, dict]:
    th = p["thresholds"]
    pts, detail = 0, {}

    def lower_worse(name, val, lv):
        nonlocal pts
        if not _ok(val):
            return
        k = 2 if val <= lv[1] else (1 if val <= lv[0] else 0)
        pts += k
        detail[name] = (round(float(val), 4), k)

    def higher_worse(name, val, lv):
        nonlocal pts
        if not _ok(val):
            return
        k = 2 if val >= lv[1] else (1 if val >= lv[0] else 0)
        pts += k
        detail[name] = (round(float(val), 4), k)

    lower_worse("ret_5d", market.get("universe_median_ret_5d"), th["ret_5d"])
    lower_worse("ret_20d", market.get("ew_index_ret_20d"), th["ret_20d"])
    higher_worse("vol_20d", market.get("ew_index_vol_20d"), th["vol_20d"])
    lower_worse("breadth", market.get("breadth_above_ma20"), th["breadth"])
    lower_worse("sox", market.get("overnight_sox_ret"), th["sox"])
    lower_worse("tsm_adr", market.get("tsm_adr_ret"), th["tsm_adr"])
    lower_worse("night", market.get("taiex_futures_night_ret"), th["night"])
    higher_worse("port_dd", port_dd, th["port_dd"])
    return pts, detail


def raw_state(points: int, p: dict) -> str:
    q = p["points"]
    if points >= q["crisis"]:
        return "CRISIS"
    if points >= q["risk_off"]:
        return "RISK_OFF"
    if points >= q["caution"]:
        return "CAUTION"
    return "NORMAL"


def step(prev: dict | None, market: dict, port_dd: float, cfg: dict) -> dict:
    """prev = previous guard state dict (from agent_state) -> new guard state dict."""
    p = params(cfg)
    pts, detail = stress_points(market, port_dd, p)
    raw = raw_state(pts, p)
    cur = (prev or {}).get("state", "NORMAL")
    calm = (prev or {}).get("calm_days", 0)
    if STATES.index(raw) > STATES.index(cur):
        new, calm = raw, 0                           # escalate immediately
    elif STATES.index(raw) < STATES.index(cur):
        calm += 1
        if calm >= int(p["exit_confirm_days"]):
            new, calm = STATES[STATES.index(cur) - 1], 0   # one level down after confirmation
        else:
            new = cur
    else:
        new, calm = cur, 0
    st = p["states"][new]
    return {"state": new, "raw_state": raw, "points": pts, "detail": detail, "calm_days": calm,
            "cash": list(st["cash"]), "allow_new": bool(st["allow_new"]), "vol_cap": st.get("vol_cap"),
            "max_delever": float(p["max_deleveraging_per_day"]), "max_relever": float(p["max_releveraging_per_day"]),
            "high_vol_quantile": float(p["high_vol_quantile"]), "port_dd": round(port_dd, 4),
            "cash_hard_ceiling": float(p["cash_hard_ceiling"])}
