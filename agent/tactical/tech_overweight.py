"""TACTICAL_TECH_OVERWEIGHT_V1 — one-day technology overweight overlay (Issue #63, Owner directive 2026-11-10).

Scope: strictly ONE trade date (`trade_date` in config/tactical_tech_overweight_v1.yaml, equality test - no range, no
"from date" semantics), so it expires by itself and cannot leak into the next D-Plan.

Design (Frozen Quant v1 and everything under the frozen paths is untouched):
  * the UNCHANGED Frozen Quant v1 constructor runs first, called with is_rebalance_day=True so that it builds its own full
    target (names + weights) from its own ranking. Its plan is observed (never altered).
  * the overlay raises technology to >= target_tech_weight_min (no ceiling is imposed beyond the per-name cap) using ONLY
    technology names that Quant already targets (water-fill, proportional to Quant's own weights, per-name cap) and, if those
    cannot absorb it, further technology names ranked/eligible under Quant's own ranking (best rank first). No ticker is
    hand-picked. Funding comes from the lowest-ranked non-technology targets first.
  * the modified target goes through Quant's own `_finalize` (lots, caps, cash band, post-trade compliance, Active Share,
    stress, <= 30 orders). If the first level does not pass or realises < min, higher / lower levels are tried; if 75 % cannot be
    reached compliantly the highest compliant attainable exposure is used and the blocker is recorded. If nothing passes, Quant's
    own result is returned untouched (fail closed) and the reason is recorded.
  * Rollback: set `enabled: false` or delete the config. After the date nothing in this module has any effect.
"""
from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

import yaml

from agent.config import ROOT, D
from agent.portfolio import baseline as B
from agent.portfolio import constructor as K

VERSION = "TACTICAL_TECH_OVERWEIGHT_V1"
CONFIG_PATH = ROOT / "config" / "tactical_tech_overweight_v1.yaml"
Q = Decimal("0.00000001")
NEW_NAME_START = Decimal("0.06")      # initial weight of a technology name added from Quant's ranking
WORST = 10 ** 9


def load_config(path: Path | str | None = None) -> dict | None:
    p = Path(path) if path else CONFIG_PATH           # resolved at call time (tests point it elsewhere)
    try:
        raw = p.read_bytes()
        cfg = yaml.safe_load(raw.decode("utf-8")) or {}
    except (OSError, ValueError, yaml.YAMLError):
        return None
    if not cfg.get("enabled") or cfg.get("version") != VERSION or not (cfg.get("trade_date") or cfg.get("floor_schedule")):
        return None
    cfg["_fingerprint"] = hashlib.sha256(raw).hexdigest()
    cfg["_path"] = str(p)
    return cfg


def floor_for(cfg: dict, trade_date: str) -> float | None:
    """Issue #65: persistent owner floor. `floor_schedule` = [{from, to?, min}]: the segment with the latest `from` <= trade_date
    wins; a segment with `to` ends there, one without `to` persists until the Owner changes / disables the config. Legacy single-date
    config (Issue #63: `trade_date` + `target_tech_weight_min`) is still understood. None = inactive for that date."""
    td = str(trade_date)
    if cfg.get("floor_schedule"):
        best = None
        for seg in cfg["floor_schedule"]:
            if str(seg["from"]) <= td and (not seg.get("to") or td <= str(seg["to"])):
                if best is None or str(seg["from"]) >= str(best["from"]):
                    best = seg
        return None if best is None else float(best["min"])
    return float(cfg["target_tech_weight_min"]) if str(cfg.get("trade_date")) == td else None


def segment_policy(cfg: dict, trade_date: str) -> str | None:
    """Issue #68: policy of the floor segment in force on that date (None / 'highest_compliant' = the #65 search, 'risk_adjusted' = #68)."""
    td, best = str(trade_date), None
    for seg in cfg.get("floor_schedule") or []:
        if str(seg["from"]) <= td and (not seg.get("to") or td <= str(seg["to"])) and (best is None or str(seg["from"]) >= str(best["from"])):
            best = seg
    return None if best is None else best.get("policy")


def resolve(trade_date: str, config_path=None) -> dict | None:
    """The config (with `target_tech_weight_min` set to that date's floor) if the overlay is enabled and covers this trade date."""
    c = load_config(config_path)
    if c is None:
        return None
    fl = floor_for(c, trade_date)
    if fl is None:
        return None
    c = dict(c)
    c["policy"] = segment_policy(c, trade_date)
    c["target_tech_weight_min"] = fl
    c["trade_date"] = str(trade_date)
    return c


def tech_tickers(cfg: dict) -> set[str]:
    """Technology classification used since #41-#43 (the same list the tactical V2 config carries); resolved relative to the repo."""
    src = Path(cfg.get("tech_classification_file") or "config/tactical_override_v2.yaml")
    p = src if src.is_absolute() else ROOT / src
    d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {str(t) for t in d.get(cfg.get("tech_classification_key") or "reduce_tickers", [])}


def overlay_weights(tw, no_trade, rank_of, eligible, tech, target, cap, lot_ok=lambda t, w: True, mode="proportional", cash_floor=None,
                    mult=None, bucket_of=None, bucket_cap=None):
    """Pure function. Returns (new_target_weights, new_no_trade, info). Cash (1 - sum) is unchanged.
    mode "proportional": raise every Quant technology target proportionally (diversified, many orders);
    mode "ranked": raise the best-ranked Quant technology targets first up to the cap (few orders, used when the 30-order cap binds)."""
    w = {t: D(v) for t, v in tw.items()}
    target, cap = D(target), D(cap)
    info = {"funded_from": [], "raised": {}, "added": []}
    need = target - sum((v for t, v in w.items() if t in tech), Decimal(0))
    if need <= 0:
        return w, set(no_trade), info
    nontech = sorted((t for t in w if t not in tech), key=lambda t: (-rank_of.get(t, WORST), t))
    cash_now = Decimal(1) - sum(w.values(), Decimal(0))
    cash_room = max(Decimal(0), cash_now - D(cash_floor)) if cash_floor is not None else Decimal(0)   # only AFTER the non-tech targets are used up
    need = min(need, sum((w[t] for t in nontech), Decimal(0)) + cash_room)
    rem, gained = need, {}
    existing = [t for t in w if t in tech]
    bcap = D(bucket_cap) if (bucket_of and bucket_cap is not None) else None
    m_of = (lambda t: D(str(mult.get(t, 1.0)))) if mult else (lambda t: Decimal(1))

    def head(t):                                                    # Issue #68: sub-sector concentration headroom (None = unconstrained)
        if bcap is None:
            return None
        b = bucket_of.get(t)
        return bcap - sum((v for k, v in w.items() if bucket_of.get(k) == b), Decimal(0))
    if mode == "ranked":                                            # 1b) fewest orders: best-ranked existing tech first, each up to the cap
        for t in sorted(existing, key=lambda t: (rank_of.get(t, WORST), t)):
            if rem <= Q:
                break
            give = min(cap - w[t], rem, head(t) if bcap is not None else rem)
            if give > Q:
                w[t] += give
                gained[t] = gained.get(t, Decimal(0)) + give
                rem -= give
    for _ in range(40 if mode != "ranked" else 0):                  # 1) Quant's own technology targets, proportional water-fill
        room = {t: cap - w[t] for t in existing if cap - w[t] > Q}
        if bcap is not None:
            room = {t: r for t, r in room.items() if head(t) > Q}
        if rem <= Q or not room:
            break
        base = sum((w[t] * m_of(t) for t in room), Decimal(0)) or Decimal(1)
        step = {t: min(room[t], rem * w[t] * m_of(t) / base) for t in room}
        if bcap is not None:                                        # a sub-sector may not take more than its headroom in one pass
            tot: dict = {}
            for t, v in step.items():
                tot[bucket_of.get(t)] = tot.get(bucket_of.get(t), Decimal(0)) + v
            for t in list(step):
                b = bucket_of.get(t)
                h = bcap - sum((v for k, v in w.items() if bucket_of.get(k) == b), Decimal(0))
                if tot[b] > h:
                    step[t] = step[t] * max(h, Decimal(0)) / tot[b]
        for t, s in step.items():
            w[t] += s
            gained[t] = gained.get(t, Decimal(0)) + s
        rem -= sum(step.values(), Decimal(0))
    if rem > Q:                                                     # 2) further Quant-ranked, eligible technology names (best rank first)
        cands = sorted((t for t in tech if t not in w and eligible.get(t) and t in rank_of), key=lambda t: (rank_of[t], t))
        for t in cands:
            if rem <= Q:
                break
            give = min(cap, NEW_NAME_START, rem, head(t) if bcap is not None else rem)
            if give <= Q or not lot_ok(t, give):
                continue
            w[t] = give
            gained[t] = give
            info["added"].append(t)
            rem -= give
    allocated = need - rem
    left = allocated
    for t in nontech:                                               # funding: lowest-ranked non-technology first
        if left <= Q:
            break
        take = min(w[t], left)
        w[t] -= take
        left -= take
        info["funded_from"].append(t)
        if w[t] <= Q:
            del w[t]
    info["from_cash"] = float(max(left, Decimal(0)))
    info["raised"] = {t: float(v) for t, v in gained.items() if t not in info["added"]}
    w = {t: v.quantize(Q, rounding="ROUND_FLOOR") for t, v in w.items()}
    changed = {t for t in w if t not in tw or w[t] != D(tw[t])}
    return w, {t for t in no_trade if t in w and t not in changed}, info


def _tech_weight(weights, tech):
    return float(sum((v for t, v in weights.items() if t in tech), Decimal(0)))


def run_overlay_legacy(plan, res0, prev_cash, rb, cfg, market, etf_holdings, etf_meta, scores, regime_override, tcfg, tech):
    """plan = Quant's observed (target_w, prev_h, no_trade, nav, closes, lot). Returns (result, record_fields)."""
    tw, prev_h, no_trade, nav, closes, lot = plan
    nav = D(nav)
    rank_of = {t: int(r) for t, r in scores["rank"].dropna().items()} if "rank" in scores else {}
    elig = scores["eligible"].to_dict() if "eligible" in scores else {}
    scored = set(scores.index[scores["score"].notna()]) if "score" in scores else set(rank_of)
    elig = {t: bool(v) and t in scored for t, v in elig.items()}
    caps = D(cfg["strategy_buffers"]["other_target_cap"])
    minimum = D(str(tcfg["target_tech_weight_min"]))
    cash_floor = tcfg.get("min_cash_weight")             # funding of last resort once every non-technology target is used (None = never touch cash)
    regime, stance, cash_rng, why = regime_override or B.regime_from_market(market, cfg)

    def lot_ok(t, w):
        px = closes.get(t)
        return px is not None and w * nav / D(px) >= lot

    quant_tw_tech = _tech_weight({t: D(v) for t, v in tw.items()}, tech)
    quant_res_tech = _tech_weight(res0.est_weights, tech) if isinstance(res0, K.TargetPortfolio) else None
    rec = {"base_strategy": "FROZEN_QUANT_V1", "tactical_overlay": "TECH_OVERWEIGHT", "target_tech_weight_min": float(minimum),
           "owner_tech_floor": float(minimum), "owner_directive": tcfg.get("owner_directive"),
           "tech_weight_before_overlay": quant_res_tech if quant_res_tech is not None else quant_tw_tech,
           "quant_target_tech_weight": quant_tw_tech, "quant_target_names": len(tw),
           "frozen_quant_sha256": tcfg.get("frozen_quant_sha256")}
    # Issue #65 (2026-11-11 directive): the floor is a MINIMUM, not a target. Search UPWARD from the floor and keep the highest
    # compliant tech weight; every level goes through Quant's own _finalize (lots, caps, cash band, Active Share, stress, <=30 orders).
    fl = float(minimum)
    up = [round(fl + 0.01 * i, 4) for i in range(0, 60) if fl + 0.01 * i <= 0.995]
    down = [round(fl - 0.01 * i, 4) for i in range(1, 40) if fl - 0.01 * i > quant_tw_tech]
    best = None
    tried = []
    STALL = 4                                           # stop a mode after this many consecutive levels that do not improve the best

    def attempt(mode, lv):
        nonlocal best
        tw2, nt2, info = overlay_weights(tw, no_trade, rank_of, elig, tech, lv, caps, lot_ok, mode, cash_floor)
        notes = [f"科技股持續下限（Owner Issue #65/#63）：沿用 Frozen Quant v1 目標與排名，科技目標 ≥ {fl:.0%}（下限，非上限，向上搜尋最高合規水位），"
                 f"資金先來自排名最低的非科技持股：{info['funded_from']}；新增科技（Quant 排名內）：{info['added']}"]
        res = K._finalize(tw2, nt2, prev_h, D(prev_cash), nav, closes, rb, cfg, etf_holdings, etf_meta, regime, stance, why,
                          cash_rng, {"kept": list(prev_h), "new": info["added"], "dropped": info["funded_from"], "rank_of": rank_of,
                                     "tactical": VERSION}, notes)
        got = _tech_weight(res.est_weights, tech) if isinstance(res, K.TargetPortfolio) else None
        tried.append({"mode": mode, "level": round(lv, 4), "passed": got is not None, "tech_after": got,
                      **({} if got is not None else {"reason": str(getattr(res, "reason", ""))[:160]})})
        if got is not None and (best is None or got > best[0] + 1e-9):
            best = (got, res, info, mode, lv)
            return True
        return False

    for mode in ("proportional", "ranked"):             # diversified first; "ranked" uses fewer orders when the 30-order cap binds
        miss = 0
        for lv in up:
            improved = attempt(mode, lv)
            miss = 0 if improved else miss + 1
            if best is not None and best[0] >= fl and miss >= STALL:
                break
    if best is None or best[0] < fl:                    # floor not reachable: fall back to the highest compliant level below it
        for mode in ("proportional", "ranked"):
            for lv in down:
                attempt(mode, lv)
    rec["levels_tried"] = tried
    if best is None:
        rec.update(status="TECH_OVERWEIGHT_BLOCKED", reason="no overlay level passed Quant's own legality pipeline; Quant result returned untouched",
                   tech_weight_after_overlay=rec["tech_weight_before_overlay"])
        return res0, rec
    got, res, info, mode, lv = best
    reached = got >= float(minimum)
    rec.update(selected_mode=mode, selected_level=round(lv, 4), blocker=None if reached else
               ("30-order cap / per-name cap / lots / cash / Active Share: see levels_tried for each attempt"))
    rec.update(status="TECH_OVERWEIGHT_APPLIED" if reached else "TECH_OVERWEIGHT_PARTIAL", funded_from=info["funded_from"],
               reduced_nontech_names=info["funded_from"], funded_from_cash_weight=info["from_cash"],
               raised_tech_names=info["raised"], added_tech_names=info["added"], tech_weight_after_overlay=got,
               reason=f"technology {got:.2%} >= minimum {fl:.0%}; highest compliant level found by upward search" if reached else
               f"highest compliant attainable technology exposure {got:.2%} < {float(minimum):.0%}: a hard guard (holdings / per-name cap / "
               "cash / Active Share / 30 orders / lots) prevents more")
    return res, rec


def run_overlay(plan, res0, prev_cash, rb, cfg, market, etf_holdings, etf_meta, scores, regime_override, tcfg, tech):
    """Dispatcher: Issue #68 risk-adjusted policy from its effective date, else the Issue #65 highest-compliant search (history)."""
    if tcfg.get("policy") == "risk_adjusted":
        from agent.tactical import tech_risk_adjusted as RA
        return RA.run_overlay_v2(plan, res0, prev_cash, rb, cfg, market, etf_holdings, etf_meta, scores, regime_override, tcfg, tech,
                                 legacy=run_overlay_legacy)
    return run_overlay_legacy(plan, res0, prev_cash, rb, cfg, market, etf_holdings, etf_meta, scores, regime_override, tcfg, tech)
