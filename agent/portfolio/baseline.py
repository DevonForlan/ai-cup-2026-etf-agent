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


def select_names(scores: pd.DataFrame, prev_holdings: dict[str, int], cfg: dict,
                 exclude: set[str] | None = None) -> tuple[list[str], dict]:
    """Turnover-aware selection. Returns (selected tickers ordered by score, info)."""
    sb, tv = cfg["strategy_buffers"], cfg["turnover"]
    target, tmin, tmax = sb["target_holdings"], sb["target_holdings_min"], sb["target_holdings_max"]
    exclude = exclude or set()
    elig = scores[scores["eligible"] & scores["score"].notna() & ~scores.index.isin(list(exclude))]
    ranked = list(elig.sort_values("rank").index)
    rank_of = {t: i + 1 for i, t in enumerate(ranked)}
    sc = elig["score"].to_dict()
    held = [t for t, s in prev_holdings.items() if s > 0]
    keep_limit = target + tv["hold_buffer"]
    kept = sorted([t for t in held if rank_of.get(t, 10**9) <= keep_limit], key=lambda t: rank_of[t])
    dropped = [t for t in held if t not in kept]
    initial = not held
    max_new = len(ranked) if initial else tv["max_new_names_per_day"]
    if len(kept) > tmax:
        dropped += kept[tmax:]
        kept = kept[:tmax]
    sel = list(kept)
    new = []
    for t in ranked:
        if len(sel) >= target or len(new) >= max_new:
            break
        if t not in sel:
            sel.append(t)
            new.append(t)
    # swaps: a strong outsider replaces the weakest kept name
    margin = tv["swap_score_margin"]
    for t in ranked:
        if len(new) >= max_new:
            break
        if t in sel:
            continue
        weakest = min((x for x in sel if x in kept), key=lambda x: sc.get(x, -1e9), default=None)
        if weakest is None or sc[t] < sc.get(weakest, -1e9) + margin:
            break
        sel.remove(weakest)
        kept.remove(weakest)
        dropped.append(weakest)
        sel.append(t)
        new.append(t)
    # make sure the minimum count is met even if max_new limited it
    for t in ranked:
        if len(sel) >= tmin:
            break
        if t not in sel:
            sel.append(t)
            new.append(t)
    sel = sorted(sel, key=lambda t: rank_of.get(t, 10**9))
    return sel, {"kept": kept, "new": new, "dropped": dropped, "rank_of": rank_of}


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
