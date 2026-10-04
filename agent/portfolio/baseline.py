"""Deterministic baseline building blocks: rule-based regime, selection with turnover control,
tiered weights, and cap water-filling. No LLM."""
from __future__ import annotations

import math
from decimal import Decimal

import pandas as pd

Q = Decimal("0.000001")


def regime_from_market(market: dict, cfg: dict) -> tuple[str, str, tuple[float, float], str]:
    """Returns (regime, stance, cash_target_range, rationale)."""
    rc = cfg["regime"]
    b = market.get("breadth_above_ma20")
    m20 = market.get("universe_median_ret_20d")
    if b is None or (isinstance(b, float) and math.isnan(b)):
        reg, why = "neutral", "缺少廣度資料，預設中性"
    elif b <= rc["risk_off_breadth"] and (m20 is None or m20 < 0):
        reg, why = "risk_off", f"站上 20 日均線比例 {b:.0%} ≤ {rc['risk_off_breadth']:.0%} 且 20 日中位報酬為負"
    elif b >= rc["risk_on_breadth"] and (m20 is None or m20 > 0):
        reg, why = "risk_on", f"站上 20 日均線比例 {b:.0%} ≥ {rc['risk_on_breadth']:.0%} 且 20 日中位報酬為正"
    else:
        reg, why = "neutral", f"站上 20 日均線比例 {b:.0%}，介於門檻之間"
    stance = {"risk_on": "aggressive", "neutral": "neutral", "risk_off": "defensive"}[reg]
    lo, hi = rc["cash_by_regime"][reg]
    return reg, stance, (float(lo), float(hi)), why


def turnover_params(cfg: dict) -> dict:
    """Turnover controls with backward-compatible defaults (Round 02 configs still work)."""
    sb, tv = cfg["strategy_buffers"], cfg.get("turnover", {})
    target = sb["target_holdings"]
    return {
        "entry_rank": tv.get("entry_rank", target),
        "hold_rank": tv.get("hold_rank", target + tv.get("hold_buffer", 10)),
        "min_holding_days": tv.get("min_holding_days", 0),
        "extreme_exit_rank": tv.get("extreme_exit_rank", 120),
        "swap_score_margin": tv.get("swap_score_margin", 0.10),
        "max_new_names_per_day": tv.get("max_new_names_per_day", 5),
        "rebalance_threshold": tv.get("rebalance_threshold", tv.get("no_trade_band", 0.015)),
        "score_ema_alpha": tv.get("score_ema_alpha", 1.0),
        "turnover_penalty_lambda": tv.get("turnover_penalty_lambda", 0.0),
        "turnover_cost_score_units": tv.get("turnover_cost_score_units", 0.02),
        "rebalance_every": tv.get("rebalance_every", 1),
        "max_daily_changes": tv.get("max_daily_changes", 28),
    }


def select_names(scores: pd.DataFrame, prev_holdings: dict[str, int], cfg: dict,
                 exclude: set[str] | None = None, holding_days: dict[str, int] | None = None
                 ) -> tuple[list[str], dict]:
    """Turnover-aware selection with rank buffer, minimum holding period and swap margin.

    * existing holding kept if rank <= hold_rank, or if still inside min_holding_days and
      rank <= extreme_exit_rank (never kept when ineligible = no data / illiquid)
    * a new name may enter only if rank <= entry_rank (relaxed only to reach the official minimum)
    * a new name replaces the weakest unprotected kept name only if score beats it by swap margin
    """
    sb = cfg["strategy_buffers"]
    tp = turnover_params(cfg)
    target, tmin, tmax = sb["target_holdings"], sb["target_holdings_min"], sb["target_holdings_max"]
    exclude = exclude or set()
    holding_days = holding_days or {}
    elig = scores[scores["eligible"] & scores["score"].notna() & ~scores.index.isin(list(exclude))]
    ranked = list(elig.sort_values("rank").index)
    rank_of = {t: i + 1 for i, t in enumerate(ranked)}
    sc = elig["score"].to_dict()
    held = [t for t, s in prev_holdings.items() if s > 0]
    protected = {t for t in held if holding_days.get(t, 10**6) < tp["min_holding_days"]
                 and rank_of.get(t, 10**9) <= tp["extreme_exit_rank"]}
    kept = sorted([t for t in held if rank_of.get(t, 10**9) <= tp["hold_rank"] or t in protected],
                  key=lambda t: rank_of.get(t, 10**9))
    dropped = [t for t in held if t not in kept]
    initial = not held
    max_new = len(ranked) if initial else tp["max_new_names_per_day"]
    if len(kept) > tmax:
        over = sorted([t for t in kept if t not in protected], key=lambda t: -rank_of.get(t, 10**9))
        for t in over[: len(kept) - tmax]:
            kept.remove(t)
            dropped.append(t)
    sel = list(kept)
    new: list[str] = []
    entry_ok = [t for t in ranked if rank_of[t] <= tp["entry_rank"] and t not in sel]
    for t in entry_ok:
        if len(sel) >= target or len(new) >= max_new:
            break
        sel.append(t)
        new.append(t)
    margin = tp["swap_score_margin"]
    for t in entry_ok:
        if len(new) >= max_new:
            break
        if t in sel:
            continue
        cands = [x for x in sel if x in kept and x not in protected]
        weakest = min(cands, key=lambda x: sc.get(x, -1e9), default=None)
        if weakest is None or sc[t] < sc.get(weakest, -1e9) + margin:
            break
        sel.remove(weakest)
        kept.remove(weakest)
        dropped.append(weakest)
        sel.append(t)
        new.append(t)
    # D-Plan allows at most 30 decisions/orders per day: cap BUY(new) + SELL_ALL(dropped) changes.
    # When the minimum count needs more names, re-admit dropped holdings first (no order needed).
    max_changes = int(tp.get("max_daily_changes", 28))
    for t in sorted(dropped, key=lambda x: rank_of.get(x, 10**9)):
        needed = max(0, tmin - len(sel))
        if len(dropped) + len(new) + needed <= max_changes:
            break
        if t in rank_of and t not in sel:      # only eligible names can be re-admitted
            sel.append(t)
            kept.append(t)
            dropped = [x for x in dropped if x != t]
    for t in ranked:                       # legality first: reach the minimum count
        if len(sel) >= tmin:
            break
        if t not in sel:
            sel.append(t)
            new.append(t)
    sel = sorted(sel, key=lambda t: rank_of.get(t, 10**9))
    return sel, {"kept": kept, "new": new, "dropped": dropped, "rank_of": rank_of,
                 "protected": sorted(protected)}


def tiered_raw_weights(selected: list[str], cfg: dict) -> dict[str, float]:
    tiers = cfg["baseline"]["tiers"]
    out = {}
    for i, t in enumerate(selected):
        w = tiers[-1]["weight"]
        for tier in tiers:
            if i < tier["top"]:
                w = tier["weight"]
                break
        out[t] = float(w)
    return out


def equal_raw_weights(selected: list[str]) -> dict[str, float]:
    return {t: 1.0 for t in selected}


def water_fill(raw: dict[str, float], invest: Decimal, caps: dict[str, Decimal]) -> dict[str, Decimal]:
    """Scale raw weights to sum `invest`, cap each name, redistribute excess to uncapped names.
    Leftover (if every name is capped) stays as cash."""
    w = {t: Decimal(str(v)) for t, v in raw.items() if v > 0}
    fixed: dict[str, Decimal] = {}
    remaining = invest
    for _ in range(len(w) + 1):
        free = {t: v for t, v in w.items() if t not in fixed}
        tot = sum(free.values(), Decimal(0))
        if not free or tot <= 0 or remaining <= 0:
            break
        trial = {t: v / tot * remaining for t, v in free.items()}
        over = {t for t, v in trial.items() if v > caps[t]}
        if not over:
            fixed.update(trial)
            remaining = Decimal(0)
            break
        for t in over:
            fixed[t] = caps[t]
            remaining -= caps[t]
    return {t: v.quantize(Q, rounding="ROUND_FLOOR") for t, v in fixed.items()}
