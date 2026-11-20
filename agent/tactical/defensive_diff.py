"""TACTICAL_DEFENSIVE_DIFFERENTIATION_V1 (Owner decision 2026-11-20, option B) - over the unchanged Frozen Quant v1.

Why: the 2026-11-20 relative-ranking analysis showed the technology portfolio moves with the active-ETF crowd (beta ~0.97, ~2% six-day
tracking deviation), so it cannot change the ranking. The Owner chose to differ from the crowd for the remaining days:

    low-volatility NON-technology stocks + cash ~16 % (well below the official 25 % cap)

  1. The UNCHANGED Frozen Quant v1 constructor runs first (observed only).
  2. Pool = universe names outside the technology list, ranked by 60-day realised volatility (lowest first), liquid enough
     (20-day average traded value >= `min_avg_amount`), with a price.
  3. Transition under the 30-order cap and the 20-30 holdings rule: sell the LARGEST technology positions completely, leave the
     smallest ones untouched (no order) and buy the lowest-volatility pool names, so that orders <= max_orders and holdings >= min_holdings.
     Later days continue until no technology name is left.
  4. Once no technology name is held: keep the portfolio unless cash leaves [cash_min, cash_max] (then equal-weight re-sizing).
  5. EVERY candidate goes through Quant's own `_finalize` (lots, holdings 20-30, per-name cap, cash < 25 % also under the +/-5 % stress
     fills, Active Share, <= 30 orders). Candidates are tried from the most technology sold downward; the first that passes is used.
  6. If nothing passes, the AGGRESSIVE_RETURN overlay is used (recorded as fallback); if that fails too, Quant's result (fail closed).
Rollback: the floor_schedule segment `policy: defensive` in config/tactical_tech_overweight_v1.yaml -> `policy: aggressive, min: 0.93`.
"""
from __future__ import annotations

import math
from decimal import Decimal

from agent.config import D
from agent.portfolio import baseline as B
from agent.portfolio import constructor as K
from agent.tactical import tech_regime as RG
from agent.tactical.tech_overweight import Q, _tech_weight

VERSION = "TACTICAL_DEFENSIVE_DIFFERENTIATION_V1"


def volatility_pool(prices, universe, tech, lookback=60, min_avg_amount=0.0):
    """[(ticker, vol)] of non-technology universe names, lowest realised volatility first (pure; prices = daily_prices rows)."""
    if prices is None or len(prices) == 0:
        return []
    out = []
    px = prices.sort_values(["ticker", "date"])
    for t, g in px.groupby("ticker"):
        t = str(t)
        if t in tech or t not in universe:
            continue
        c = [float(x) for x in g["close"].tolist()][-(lookback + 1):]
        if len(c) < 21:
            continue
        r = [c[i] / c[i - 1] - 1 for i in range(1, len(c)) if c[i - 1] > 0]
        m = sum(r) / len(r)
        vol = math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1))
        if "amount" in g and min_avg_amount:
            amt = [float(x) for x in g["amount"].tolist()][-20:]
            if not amt or sum(amt) / len(amt) < float(min_avg_amount):
                continue
        out.append((t, vol))
    return sorted(out, key=lambda x: (x[1], x[0]))


def plan_transition(held_w, tech, pool, sell_n, *, cash_target, cap, min_holdings, max_holdings, max_orders):
    """Pure. held_w {ticker: Decimal weight} (current), pool [ticker] lowest-vol first. Sell the `sell_n` largest technology holdings,
    keep everything else untouched, buy enough pool names. Returns (target_w, no_trade, info) or None if the counts cannot work."""
    held_tech = sorted((t for t in held_w if t in tech), key=lambda t: (-held_w[t], t))
    sell = held_tech[:sell_n]
    keep = {t: w for t, w in held_w.items() if t not in sell}
    buys_avail = [t for t in pool if t not in held_w]
    need = max(0, min_holdings - len(keep))
    room = max_orders - len(sell)
    invest = Decimal(1) - D(cash_target) - sum(keep.values(), Decimal(0))
    b = max(need, 1 if invest > Decimal("0.02") else 0)  # buy exactly what the holdings rule needs (fewest orders), at least one if cash is idle
    if b > room or b > len(buys_avail):
        return None
    buys = buys_avail[:b]
    per = (invest / b).quantize(Q, rounding="ROUND_FLOOR") if b else Decimal(0)
    per = min(per, D(cap))
    if b and per <= Decimal("0.005"):
        return None
    w = dict(keep)
    for t in buys:
        w[t] = per
    if not (min_holdings <= len(w) <= max_holdings):
        return None
    return w, set(keep), {"sold_tech": sell, "kept_tech": [t for t in keep if t in tech], "added": buys, "per_new_weight": float(per)}


def equal_resize(held_w, cash_target, cap):
    """Pure. Equal weights over the current holdings with the target cash (used once no technology name is left)."""
    n = len(held_w)
    per = min(((Decimal(1) - D(cash_target)) / n).quantize(Q, rounding="ROUND_FLOOR"), D(cap))
    return {t: per for t in held_w}


def run_overlay_defensive(plan, res0, prev_cash, rb, cfg, market, etf_holdings, etf_meta, scores, regime_override, tcfg, tech,
                          fallback=None):
    tw, prev_h, no_trade, nav, closes, lot = plan
    nav = D(nav)
    dc = dict(tcfg.get("defensive") or {})
    cash_target = float(dc.get("cash_target", 0.16))
    cash_min, cash_max = (dc.get("cash_band") or [0.10, 0.20])
    cap = min(D(cfg["strategy_buffers"]["other_target_cap"]), D(str(dc.get("max_weight", 0.09))))
    min_h, max_h = int(dc.get("min_holdings", 21)), int(dc.get("max_holdings", 28))
    max_orders = int(dc.get("max_orders", 30))
    regime, stance, cash_rng, why = regime_override or B.regime_from_market(market, cfg)
    frames = tcfg.get("_frames") or RG.load_market_frames(tcfg["trade_date"])
    universe = set(rb.universe) if getattr(rb, "universe", None) else set(closes)
    pool_v = volatility_pool(frames[0], universe, tech, int(dc.get("vol_lookback", 60)), float(dc.get("min_avg_amount", 0)))
    pool = [t for t, _ in pool_v if closes.get(t) is not None]
    vol_of = dict(pool_v)

    held_w = {}
    for t, sh in prev_h.items():
        px = closes.get(t)
        if px is not None and int(sh) > 0:
            held_w[t] = (Decimal(int(sh)) * D(px) / nav).quantize(Q, rounding="ROUND_FLOOR")
    tech_before = _tech_weight(held_w, tech)
    cash_now = float(1 - sum(held_w.values(), Decimal(0)))
    rec = {"base_strategy": "FROZEN_QUANT_V1", "tactical_overlay": "DEFENSIVE_DIFFERENTIATION", "policy": "defensive", "version": VERSION,
           "owner_directive": tcfg.get("owner_directive"), "frozen_quant_sha256": tcfg.get("frozen_quant_sha256"),
           "target_tech_weight_min": float(tcfg.get("target_tech_weight_min") or 0.0),
           "tech_weight_before_overlay": tech_before, "cash_target": cash_target, "cash_band": [cash_min, cash_max],
           "pool_top": [{"ticker": t, "vol60": round(v, 4)} for t, v in pool_v[:30]]}
    cands = []

    def evaluate(label, tw2, nt2, info):
        notes = [f"差異化防守策略（Owner 2026-11-20 選項 B）：以低波動非科技股取代科技股、現金目標 {cash_target:.0%}"
                 f"（官方上限 25%）；候選 {label}；賣出科技 {info.get('sold_tech', [])}，新增 {info.get('added', [])}"]
        res = K._finalize(tw2, nt2, prev_h, D(prev_cash), nav, closes, rb, cfg, etf_holdings, etf_meta, regime, stance, why, cash_rng,
                          {"kept": list(prev_h), "new": info.get("added", []), "dropped": info.get("sold_tech", []), "rank_of": {},
                           "tactical": VERSION}, notes)
        ok = isinstance(res, K.TargetPortfolio)
        row = {"label": label, "passed": ok}
        if ok:
            row.update(tech_after=_tech_weight(res.est_weights, tech), cash_after=float(res.est_cash / res.est_nav),
                       orders=len(res.orders), holdings=len(res.est_holdings) if hasattr(res, "est_holdings") else None)
        else:
            row["reason"] = str(getattr(res, "reason", ""))[:160]
        cands.append(row)
        return res if ok else None

    chosen = None
    held_tech = [t for t in held_w if t in tech]
    if held_tech:
        for s in range(len(held_tech), 0, -1):
            p = plan_transition(held_w, tech, pool, s, cash_target=cash_target, cap=cap, min_holdings=min_h, max_holdings=max_h,
                                max_orders=max_orders)
            if p is None:
                continue
            res = evaluate(f"transition_sell{s}", *p)
            if res is not None:
                chosen = (f"transition_sell{s}", res, p[2])
                break
    else:
        if cash_min <= cash_now <= cash_max:
            res = evaluate("stay", dict(held_w), set(held_w), {})
            if res is not None:
                chosen = ("stay", res, {})
        if chosen is None:
            res = evaluate("equal_resize", equal_resize(held_w, cash_target, cap), set(), {})
            if res is not None:
                chosen = ("equal_resize", res, {})
    rec["candidates"] = cands
    if chosen is None:
        rec["fallback"] = "no compliant defensive candidate; AGGRESSIVE_RETURN overlay used"
        if fallback is not None:
            res, r2 = fallback()
            r2.update({k: v for k, v in rec.items() if k not in r2 and k != "policy"})
            r2["fallback"], r2["policy_requested"] = rec["fallback"], "defensive"
            return res, r2
        rec.update(status="TECH_OVERWEIGHT_BLOCKED", reason=rec["fallback"], tech_weight_after_overlay=tech_before)
        return res0, rec
    label, res, info = chosen
    rec.update(status="TECH_OVERWEIGHT_APPLIED", selected=label, selected_mode=label.split("_sell")[0], selected_level=None,
               selection_reason=("sell the most technology possible within 30 orders / 20-30 holdings, replace with the lowest-volatility "
                                 "non-technology names" if label.startswith("transition") else
                                 "no technology left; cash inside the band -> keep" if label == "stay" else
                                 "no technology left; cash outside the band -> equal-weight re-size"),
               sold_tech=info.get("sold_tech", []), kept_tech=info.get("kept_tech", []), added_defensive=info.get("added", []),
               added_vol60={t: round(vol_of.get(t, float("nan")), 4) for t in info.get("added", [])},
               tech_weight_after_overlay=_tech_weight(res.est_weights, tech), blocker=None, fallback=None,
               reason=f"DEFENSIVE_DIFFERENTIATION: {label}")
    return res, rec
