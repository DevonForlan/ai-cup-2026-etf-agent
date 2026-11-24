"""TACTICAL_TECH_SPRINT_V1 (Owner decision 2026-11-24: final days, technology "as close to 100 % as feasible") - over the unchanged
Frozen Quant v1.

Why a new mode: the AGGRESSIVE_RETURN overlay raises existing technology targets up to the per-name cap and funds them by removing
non-technology names, so a portfolio with few technology names drops below 20 holdings (2026-11-24: every 93 %+ candidate failed
R_COUNT with 15 holdings and the Issue #65 fallback stopped at 65 %). This mode keeps the holdings count by adding technology NAMES:

  1. The UNCHANGED Frozen Quant v1 constructor runs first (observed only).
  2. Every non-technology holding is sold. Technology holdings are kept; a holding already within `no_trade_band` of the equal
     target weight is left untouched (no order).
  3. New technology names fill the count up to `min_holdings`: Quant-eligible names first, then the rest of the technology list,
     each group ordered by the AGGRESSIVE_RETURN composite score (no hand-picked ticker), liquid enough (20-day average traded
     value >= `min_avg_amount`), with a price and a whole lot.
  4. Levels are tried from `level_max` (e.g. 99 % technology) downward; EVERY candidate goes through Quant's own `_finalize`
     (lots, holdings 20-30, per-name cap, cash >= 0 under the +/-5 % stress fills, cash < 25 %, Active Share, <= 30 orders).
     The first (highest) level that passes is used.
  5. If nothing passes, the AGGRESSIVE_RETURN overlay is used (recorded as fallback); if that fails too, Quant's result.
Rollback: the floor_schedule segment `policy: sprint` in config/tactical_tech_overweight_v1.yaml -> `policy: aggressive`.
"""
from __future__ import annotations

from decimal import Decimal

from agent.config import D
from agent.portfolio import baseline as B
from agent.portfolio import constructor as K
from agent.tactical import tech_regime as RG
from agent.tactical.tech_overweight import Q, _tech_weight

VERSION = "TACTICAL_TECH_SPRINT_V1"


def liquid(prices, names, min_avg_amount):
    """Names whose 20-day average traded value >= min_avg_amount (pure; no `amount` column -> every name passes)."""
    if not min_avg_amount or prices is None or len(prices) == 0 or "amount" not in prices:
        return set(names)
    out = set()
    px = prices[prices["ticker"].astype(str).isin(set(names))].sort_values(["ticker", "date"])
    for t, g in px.groupby("ticker"):
        amt = [float(x) for x in g["amount"].tolist()][-20:]
        if amt and sum(amt) / len(amt) >= float(min_avg_amount):
            out.add(str(t))
    return out


def plan_sprint(held_w, tech, ranked_new, level, *, cap, min_holdings, max_holdings, max_orders, no_trade_band=0.01, keep_nontech=0):
    """Pure. held_w {ticker: Decimal weight}; ranked_new = technology names not held, best first.
    Target: `level` of NAV invested; every non-technology holding is sold except the `keep_nontech` smallest ones (left untouched,
    no order - used when the 30-order cap does not allow the full switch in one day); the rest of `level` goes to technology over
    max(min_holdings, held) names. Returns (target_w, no_trade, info) or None if counts / cap / orders cannot work."""
    level, cap = D(str(level)), D(cap)
    nontech = sorted((t for t in held_w if t not in tech), key=lambda t: (held_w[t], t))
    left_nt = nontech[:keep_nontech]
    sell = sorted(nontech[keep_nontech:])
    level -= sum((held_w[t] for t in left_nt), Decimal(0))
    keep = sorted((t for t in held_w if t in tech), key=lambda t: (-held_w[t], t))
    n = max(min_holdings - len(left_nt), len(keep))
    if n + len(left_nt) > max_holdings:
        return None
    add = [t for t in ranked_new if t not in held_w][:max(0, n - len(keep))]
    if len(keep) + len(add) < n:
        return None
    names = keep + add
    per = level / n
    if per > cap:
        return None
    stay = {t for t in keep if abs(held_w[t] - per) <= D(str(no_trade_band)) and held_w[t] <= cap}
    rest = [t for t in names if t not in stay]
    if rest:
        per2 = (level - sum((held_w[t] for t in stay), Decimal(0))) / len(rest)
        if per2 > cap or per2 <= Decimal("0.005"):
            return None
    else:
        per2 = Decimal(0)
    orders = len(sell) + len(rest)
    if orders > max_orders:
        return None
    w = {t: held_w[t] for t in stay}
    w.update({t: held_w[t] for t in left_nt})
    for t in rest:
        w[t] = per2.quantize(Q, rounding="ROUND_FLOOR")
    return w, set(stay) | set(left_nt), {"sold_nontech": sell, "kept_nontech": left_nt, "kept_tech": keep, "untouched": sorted(stay),
                                         "added": add, "per_weight": float(per2), "orders_planned": orders}


def run_overlay_sprint(plan, res0, prev_cash, rb, cfg, market, etf_holdings, etf_meta, scores, regime_override, tcfg, tech,
                       fallback=None):
    tw, prev_h, no_trade, nav, closes, lot = plan
    nav = D(nav)
    sc = dict(tcfg.get("sprint") or {})
    agg = dict(tcfg.get("risk_adjusted") or {})
    agg.update(tcfg.get("aggressive") or {})
    cap = min(D(cfg["strategy_buffers"]["other_target_cap"]), D(str(sc.get("max_weight", 0.09))))
    min_h, max_h = int(sc.get("min_holdings", 21)), int(sc.get("max_holdings", 28))
    max_orders = int(sc.get("max_orders", 30))
    lv_max, lv_min = float(sc.get("level_max", 0.99)), float(sc.get("level_min", 0.85))
    band = float(sc.get("no_trade_band", 0.01))
    regime, stance, cash_rng, why = regime_override or B.regime_from_market(market, cfg)

    frames = tcfg.get("_frames") or RG.load_market_frames(tcfg["trade_date"])
    prices, inst, _ = frames
    rank_of = {t: int(r) for t, r in scores["rank"].dropna().items()} if "rank" in scores else {}
    elig = scores["eligible"].to_dict() if "eligible" in scores else {}
    sig = RG.ticker_signals(prices, inst, set(tech))
    z = RG.composite_score({t: sig[t] for t in tech if t in sig}, rank_of, agg)

    held_w = {}
    for t, sh in prev_h.items():
        px = closes.get(t)
        if px is not None and int(sh) > 0:
            held_w[t] = (Decimal(int(sh)) * D(px) / nav).quantize(Q, rounding="ROUND_FLOOR")
    tech_before = _tech_weight(held_w, tech)
    liq = liquid(prices, tech, float(sc.get("min_avg_amount", 0)))

    def buyable(t):
        px = closes.get(t)
        return px is not None and t in liq and t not in held_w and Decimal("0.03") * nav / D(px) >= lot

    pool = sorted((t for t in tech if buyable(t)), key=lambda t: (not bool(elig.get(t)), -z.get(t, -99.0), t))
    rec = {"base_strategy": "FROZEN_QUANT_V1", "tactical_overlay": "TECH_SPRINT", "policy": "sprint", "version": VERSION,
           "owner_directive": tcfg.get("owner_directive"), "frozen_quant_sha256": tcfg.get("frozen_quant_sha256"),
           "target_tech_weight_min": float(tcfg.get("target_tech_weight_min") or 0.0), "tech_weight_before_overlay": tech_before,
           "pool_top": [{"ticker": t, "eligible": bool(elig.get(t)), "score": round(z.get(t, 0.0), 3)} for t in pool[:20]]}
    cands = []

    def evaluate(label, tw2, nt2, info):
        notes = [f"科技股衝刺（Owner 2026-11-24：比賽尾聲，科技股盡量接近 100%）：候選 {label}；賣出非科技 {info.get('sold_nontech', [])}，"
                 f"新增科技 {info.get('added', [])}；新增科技股依 Frozen Quant 合格與綜合分數排序（非人工選股）"]
        res = K._finalize(tw2, nt2, prev_h, D(prev_cash), nav, closes, rb, cfg, etf_holdings, etf_meta, regime, stance, why, cash_rng,
                          {"kept": list(prev_h), "new": info.get("added", []), "dropped": info.get("sold_nontech", []),
                           "rank_of": rank_of, "tactical": VERSION}, notes)
        ok = isinstance(res, K.TargetPortfolio)
        row = {"label": label, "passed": ok}
        if ok:
            row.update(tech_after=_tech_weight(res.est_weights, tech), cash_after=float(res.est_cash / res.est_nav), orders=len(res.orders))
        else:
            row["reason"] = str(getattr(res, "reason", ""))[:160]
        cands.append(row)
        return res if ok else None

    chosen = None
    n_nontech = sum(1 for t in held_w if t not in tech)
    for k in range(0, n_nontech + 1):                  # 0 = full switch; k > 0 only when the order cap forces a partial switch
        lv = lv_max
        while lv >= lv_min - 1e-9 and chosen is None:
            label = f"sprint@{lv:.2f}" + (f"_keep{k}" if k else "")
            p = plan_sprint(held_w, tech, pool, lv, cap=cap, min_holdings=min_h, max_holdings=max_h, max_orders=max_orders,
                            no_trade_band=band, keep_nontech=k)
            if p is None:
                cands.append({"label": label, "passed": False, "reason": "counts / cap / orders do not work"})
            else:
                res = evaluate(label, *p)
                if res is not None:
                    chosen = (label, lv, res, p[2])
            lv = round(lv - 0.01, 4)
        if chosen is not None:
            break
    rec["candidates"] = cands
    if chosen is None:
        rec["fallback"] = "no compliant sprint candidate; AGGRESSIVE_RETURN overlay used"
        if fallback is not None:
            res, r2 = fallback()
            r2.update({k: v for k, v in rec.items() if k not in r2 and k != "policy"})
            r2["fallback"], r2["policy_requested"], r2["sprint_candidates"] = rec["fallback"], "sprint", cands
            return res, r2
        rec.update(status="TECH_OVERWEIGHT_BLOCKED", reason=rec["fallback"], tech_weight_after_overlay=tech_before)
        return res0, rec
    label, lv, res, info = chosen
    rec.update(status="TECH_OVERWEIGHT_APPLIED", selected=label, selected_mode="sprint", selected_level=lv,
               selection_reason="highest technology level that passes every hard guard (holdings 20-30 kept by adding technology names)",
               sold_nontech=info["sold_nontech"], kept_nontech=info["kept_nontech"], kept_tech=info["kept_tech"], untouched_tech=info["untouched"],
               added_tech_names=info["added"], tech_weight_after_overlay=_tech_weight(res.est_weights, tech), blocker=None, fallback=None,
               reason=f"TECH_SPRINT: {label}")
    return res, rec
