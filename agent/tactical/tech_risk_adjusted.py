"""TACTICAL_TECH_RISK_ADJUSTED_V1 (Issue #68, Owner directive 2026-11-13) - risk-adjusted technology overweight over the unchanged Frozen Quant v1.

Replaces the Issue #65 "highest compliant technology weight" search from the effective trade date (2026-11-16). Policy:

    best risk-adjusted portfolio  subject to  technology weight >= 85 %   (floor = hard minimum, never an optimisation target)

  1. The UNCHANGED Frozen Quant v1 constructor runs first (observed, never altered) - its own target names / weights / ranking remain the
     primary source of eligible names.
  2. Regime (tech_regime.classify_regime) sets the exposure band: STRONG 90-95 %, NORMAL 87-92 %, DEFENSIVE (high volatility / weak breadth /
     SOX or futures-night drop) 85-88 %. The band is where candidates are searched - the top of a band is never forced.
  3. Candidates = "stay" (today's holdings, zero turnover) plus overlay builds (levels inside the band x {score-tilted, proportional} allocation).
     Score tilt uses Quant rank (primary) + 5d / 20d relative strength + institutional flow + 20d realised volatility + extreme gap / sharp move.
     Sub-sector concentration (memory / PCB-CCL-materials / ASIC-IC design) is capped per bucket inside the allocation.
  4. EVERY candidate goes through Quant's own `_finalize` (lots, per-name cap, cash band, compliance, Active Share, stress, <= 30 orders).
  5. Selection by utility U = H*(mu'w - gamma/2 w'Sigma w) - transaction cost; the "stay" portfolio is kept unless another candidate beats it by more
     than `min_improvement` (turnover / cost discipline: no trading just to move between nearby compliant exposures).
  6. If nothing compliant exists inside the band, the band is widened to the strong ceiling; if still nothing, the Issue #65 search is the fallback
     and the reason is recorded. If that also fails, Quant's own result is returned untouched (fail closed).
Rollback: floor_schedule segment `policy` (config/tactical_tech_overweight_v1.yaml) or `enabled: false`.
"""
from __future__ import annotations

from decimal import Decimal

from agent.config import D
from agent.portfolio import baseline as B
from agent.portfolio import constructor as K
from agent.tactical import tech_regime as RG
from agent.tactical.tech_overweight import Q, _tech_weight, overlay_weights

VERSION = "TACTICAL_TECH_RISK_ADJUSTED_V1"


def _wts(res):
    return {t: float(v) for t, v in res.est_weights.items()} if isinstance(res, K.TargetPortfolio) else None


def run_overlay_v2(plan, res0, prev_cash, rb, cfg, market, etf_holdings, etf_meta, scores, regime_override, tcfg, tech, legacy=None):
    tw, prev_h, no_trade, nav, closes, lot = plan
    nav = D(nav)
    ra = tcfg.get("risk_adjusted") or {}
    floor = float(tcfg["target_tech_weight_min"])
    rank_of = {t: int(r) for t, r in scores["rank"].dropna().items()} if "rank" in scores else {}
    elig = scores["eligible"].to_dict() if "eligible" in scores else {}
    scored = set(scores.index[scores["score"].notna()]) if "score" in scores else set(rank_of)
    elig = {t: bool(v) and t in scored for t, v in elig.items()}
    caps = D(cfg["strategy_buffers"]["other_target_cap"])
    cash_floor = tcfg.get("min_cash_weight")
    regime, stance, cash_rng, why = regime_override or B.regime_from_market(market, cfg)

    frames = tcfg.get("_frames") or RG.load_market_frames(tcfg["trade_date"])
    prices, inst, overn = frames
    reg = RG.classify_regime(prices, overn, tech, ra)
    names_all = set(tech) | set(prev_h) | set(tw)
    sig = RG.ticker_signals(prices, inst, names_all)
    z_all = RG.composite_score({t: sig[t] for t in tech if t in sig}, rank_of, ra)
    sigma = {t: s.get("vol20") for t, s in sig.items()}
    bmap = RG.bucket_map(ra, tech)
    bcap = float(ra.get("bucket_cap", 0.30))
    kappa = float(ra.get("tilt_kappa", 0.35))
    mult = {t: min(2.0, max(0.5, pow(2.718281828, kappa * z))) for t, z in z_all.items()}
    margin = float(ra.get("min_improvement", 0.0005))
    lo, hi = reg["band_min"], reg["band_max"]
    lo = max(lo, floor)
    strong_hi = float(ra.get("strong_ceiling", 0.95))

    quant_tw_tech = _tech_weight({t: D(v) for t, v in tw.items()}, tech)
    rec = {"base_strategy": "FROZEN_QUANT_V1", "tactical_overlay": "TECH_RISK_ADJUSTED", "policy": "risk_adjusted", "version": VERSION,
           "target_tech_weight_min": floor, "owner_tech_floor": floor, "owner_directive": tcfg.get("owner_directive"),
           "tech_weight_before_overlay": _tech_weight(res0.est_weights, tech) if isinstance(res0, K.TargetPortfolio) else quant_tw_tech,
           "quant_target_tech_weight": quant_tw_tech, "quant_target_names": len(tw), "frozen_quant_sha256": tcfg.get("frozen_quant_sha256"),
           "regime": reg["regime"], "regime_reasons": reg["reasons"], "regime_inputs": reg["inputs"], "regime_missing_inputs": reg["missing_inputs"],
           "band": [lo, hi], "bucket_cap": bcap}
    cands: list[dict] = []

    def evaluate(label, mode, lv, tw2, nt2, info):
        notes = [f"科技股風險調整策略（Owner Issue #68）：regime={reg['regime']}，科技區間 {lo:.0%}–{hi:.0%}（下限 {floor:.0%} 非目標），"
                 f"候選 {label}；沿用 Frozen Quant v1 目標與排名，並考量相對強弱／法人／波動／跳空與子產業集中度及換手成本"]
        res = K._finalize(tw2, nt2, prev_h, D(prev_cash), nav, closes, rb, cfg, etf_holdings, etf_meta, regime, stance, why, cash_rng,
                          {"kept": list(prev_h), "new": info.get("added", []), "dropped": info.get("funded_from", []), "rank_of": rank_of,
                           "tactical": VERSION}, notes)
        w = _wts(res)
        row = {"label": label, "mode": mode, "level": None if lv is None else round(lv, 4), "passed": w is not None}
        if w is None:
            row["reason"] = str(getattr(res, "reason", ""))[:160]
            cands.append(row)
            return None
        tech_after = _tech_weight(res.est_weights, tech)
        cost, turnover = RG.trade_cost(res.orders, closes, nav, ra)
        u = RG.utility(w, z_all, sigma, bmap, cost, ra)
        bw = RG.bucket_weights(w, bmap)
        row.update(tech_after=tech_after, orders=len(res.orders), turnover=turnover, cost=cost, utility=u["utility"], alpha=u["alpha"],
                   risk=u["risk"], max_bucket=max(bw.values()) if bw else 0.0, buckets={k: round(v, 4) for k, v in bw.items()})
        row["_res"], row["_info"] = res, info
        cands.append(row)
        return row

    # candidate "stay": today's holdings, nothing traded (turnover discipline)
    held_w = {}
    for t, sh in prev_h.items():
        px = closes.get(t)
        if px is not None and int(sh) > 0:
            held_w[t] = (Decimal(int(sh)) * D(px) / nav).quantize(Q, rounding="ROUND_FLOOR")
    if held_w:
        evaluate("stay", "stay", None, held_w, set(held_w), {"funded_from": [], "added": []})
    for mode in ("tilt", "proportional"):
        lv = lo
        while lv <= strong_hi + 1e-9:
            tw2, nt2, info = overlay_weights(tw, no_trade, rank_of, elig, tech, lv, caps,
                                             lambda t, w: closes.get(t) is not None and w * nav / D(closes[t]) >= lot,
                                             mode="proportional", cash_floor=cash_floor, mult=mult if mode == "tilt" else None,
                                             bucket_of=bmap, bucket_cap=bcap)
            evaluate(f"{mode}@{lv:.2f}", mode, lv, tw2, nt2, info)
            lv = round(lv + 0.01, 4)

    fmin = floor + float(ra.get("floor_buffer", 0.005))        # safety margin: prices move between the 19:30 plan and the next-day VWAP fills
    stay_tol = float(ra.get("stay_band_tolerance", 0.03))      # hysteresis: holdings up to band_max + 3pt are kept (no trading just to shave exposure)

    def eligible_rows(top, guard=True):
        return [c for c in cands if c.get("passed") and c["tech_after"] >= fmin - 1e-9
                and c["tech_after"] <= top + (stay_tol if c["label"] == "stay" else 0.005)
                and (not guard or c["max_bucket"] <= bcap + 0.005)]          # sub-sector concentration guard (overrides stability)
    pool, used_hi = eligible_rows(hi), hi
    if not pool:
        pool, used_hi = eligible_rows(strong_hi), strong_hi
    if not pool:                                                             # no candidate respects the bucket cap: relax it, record it
        pool, used_hi = eligible_rows(hi, guard=False) or eligible_rows(strong_hi, guard=False), hi
        rec["bucket_guard_relaxed"] = bool(pool)
    rec["band_used_max"] = used_hi
    rec["candidates"] = [{k: v for k, v in c.items() if not k.startswith("_")} for c in cands]
    rec["levels_tried"] = [{"mode": c["mode"], "level": c["level"], "passed": c["passed"], "tech_after": c.get("tech_after"),
                            **({"reason": c["reason"]} if "reason" in c else {})} for c in cands]
    if not pool:
        rec["fallback"] = "no compliant candidate inside the risk-adjusted band; Issue #65 search used"
        if legacy is not None:
            res, r2 = legacy(plan, res0, prev_cash, rb, cfg, market, etf_holdings, etf_meta, scores, regime_override, tcfg, tech)
            r2.update({k: v for k, v in rec.items() if k not in r2})
            r2["fallback"] = rec["fallback"]
            return res, r2
        rec.update(status="TECH_OVERWEIGHT_BLOCKED", reason=rec["fallback"], tech_weight_after_overlay=rec["tech_weight_before_overlay"])
        return res0, rec
    best = max(pool, key=lambda c: c["utility"])
    stay = next((c for c in pool if c["label"] == "stay"), None)
    chosen, why_sel = best, "highest risk-adjusted utility inside the band"
    if stay is not None and best is not stay and best["utility"] - stay["utility"] < margin:
        chosen, why_sel = stay, (f"stability: best candidate {best['label']} improves utility by {best['utility'] - stay['utility']:.5f} "
                                 f"< min_improvement {margin}; existing portfolio kept (no turnover)")
    res, info = chosen["_res"], chosen["_info"]
    rec.update(selected=chosen["label"], selected_mode=chosen["mode"], selected_level=chosen["level"], selection_reason=why_sel,
               stay_utility=None if stay is None else stay["utility"], selected_utility=chosen["utility"],
               status="TECH_OVERWEIGHT_APPLIED", funded_from=info.get("funded_from", []), reduced_nontech_names=info.get("funded_from", []),
               funded_from_cash_weight=info.get("from_cash", 0.0), raised_tech_names=info.get("raised", {}), added_tech_names=info.get("added", []),
               tech_weight_after_overlay=chosen["tech_after"], blocker=None, regime_turnover=chosen["turnover"], transaction_cost=chosen["cost"],
               bucket_weights_after=chosen["buckets"],
               top_tilt_scores=dict(sorted(((t, round(z, 3)) for t, z in z_all.items()), key=lambda x: -x[1])[:8]),
               reason=f"{reg['regime']} regime, band {lo:.0%}-{used_hi:.0%}: {why_sel}")
    return res, rec
