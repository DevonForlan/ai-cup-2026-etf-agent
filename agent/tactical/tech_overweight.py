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
    if not cfg.get("enabled") or cfg.get("version") != VERSION or not cfg.get("trade_date"):
        return None
    cfg["_fingerprint"] = hashlib.sha256(raw).hexdigest()
    cfg["_path"] = str(p)
    return cfg


def resolve(trade_date: str, config_path=None) -> dict | None:
    """The config if (and only if) it is enabled AND scoped to exactly this trade date."""
    c = load_config(config_path)
    return c if c is not None and str(c["trade_date"]) == str(trade_date) else None


def tech_tickers(cfg: dict) -> set[str]:
    """Technology classification used since #41-#43 (the same list the tactical V2 config carries); resolved relative to the repo."""
    src = Path(cfg.get("tech_classification_file") or "config/tactical_override_v2.yaml")
    p = src if src.is_absolute() else ROOT / src
    d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {str(t) for t in d.get(cfg.get("tech_classification_key") or "reduce_tickers", [])}


def overlay_weights(tw, no_trade, rank_of, eligible, tech, target, cap, lot_ok=lambda t, w: True):
    """Pure function. Returns (new_target_weights, new_no_trade, info). Cash (1 - sum) is unchanged."""
    w = {t: D(v) for t, v in tw.items()}
    target, cap = D(target), D(cap)
    info = {"funded_from": [], "raised": {}, "added": []}
    need = target - sum((v for t, v in w.items() if t in tech), Decimal(0))
    if need <= 0:
        return w, set(no_trade), info
    nontech = sorted((t for t in w if t not in tech), key=lambda t: (-rank_of.get(t, WORST), t))
    need = min(need, sum((w[t] for t in nontech), Decimal(0)))
    rem, gained = need, {}
    existing = [t for t in w if t in tech]
    for _ in range(40):                                             # 1) Quant's own technology targets, proportional water-fill
        room = {t: cap - w[t] for t in existing if cap - w[t] > Q}
        if rem <= Q or not room:
            break
        base = sum((w[t] for t in room), Decimal(0)) or Decimal(1)
        step = {t: min(room[t], rem * w[t] / base) for t in room}
        for t, s in step.items():
            w[t] += s
            gained[t] = gained.get(t, Decimal(0)) + s
        rem -= sum(step.values(), Decimal(0))
    if rem > Q:                                                     # 2) further Quant-ranked, eligible technology names (best rank first)
        cands = sorted((t for t in tech if t not in w and eligible.get(t) and t in rank_of), key=lambda t: (rank_of[t], t))
        for t in cands:
            if rem <= Q:
                break
            give = min(cap, NEW_NAME_START, rem)
            if not lot_ok(t, give):
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
    info["raised"] = {t: float(v) for t, v in gained.items() if t not in info["added"]}
    w = {t: v.quantize(Q, rounding="ROUND_FLOOR") for t, v in w.items()}
    changed = {t for t in w if t not in tw or w[t] != D(tw[t])}
    return w, {t for t in no_trade if t in w and t not in changed}, info


def _tech_weight(weights, tech):
    return float(sum((v for t, v in weights.items() if t in tech), Decimal(0)))


def run_overlay(plan, res0, prev_cash, rb, cfg, market, etf_holdings, etf_meta, scores, regime_override, tcfg, tech):
    """plan = Quant's observed (target_w, prev_h, no_trade, nav, closes, lot). Returns (result, record_fields)."""
    tw, prev_h, no_trade, nav, closes, lot = plan
    nav = D(nav)
    rank_of = {t: int(r) for t, r in scores["rank"].dropna().items()} if "rank" in scores else {}
    elig = scores["eligible"].to_dict() if "eligible" in scores else {}
    scored = set(scores.index[scores["score"].notna()]) if "score" in scores else set(rank_of)
    elig = {t: bool(v) and t in scored for t, v in elig.items()}
    caps = D(cfg["strategy_buffers"]["other_target_cap"])
    minimum = D(str(tcfg["target_tech_weight_min"]))
    regime, stance, cash_rng, why = regime_override or B.regime_from_market(market, cfg)

    def lot_ok(t, w):
        px = closes.get(t)
        return px is not None and w * nav / D(px) >= lot

    quant_tw_tech = _tech_weight({t: D(v) for t, v in tw.items()}, tech)
    quant_res_tech = _tech_weight(res0.est_weights, tech) if isinstance(res0, K.TargetPortfolio) else None
    rec = {"base_strategy": "FROZEN_QUANT_V1", "tactical_overlay": "TECH_OVERWEIGHT", "target_tech_weight_min": float(minimum),
           "tech_weight_before_overlay": quant_res_tech if quant_res_tech is not None else quant_tw_tech,
           "quant_target_tech_weight": quant_tw_tech, "quant_target_names": len(tw),
           "frozen_quant_sha256": tcfg.get("frozen_quant_sha256")}
    start = float(minimum) + 0.01
    levels = [start, start + 0.01, start + 0.02, start + 0.04, float(minimum)] + \
        [round(float(minimum) - 0.01 * i, 4) for i in range(1, 40) if float(minimum) - 0.01 * i > quant_tw_tech]
    best = None
    tried = []
    for lv in levels:
        tw2, nt2, info = overlay_weights(tw, no_trade, rank_of, elig, tech, lv, caps, lot_ok)
        notes = [f"一次性科技股加碼（Owner Issue #63）：沿用 Frozen Quant v1 目標與排名，科技目標 ≥ {float(minimum):.0%}，"
                 f"資金先來自排名最低的非科技持股：{info['funded_from']}；新增科技（Quant 排名內）：{info['added']}"]
        res = K._finalize(tw2, nt2, prev_h, D(prev_cash), nav, closes, rb, cfg, etf_holdings, etf_meta, regime, stance, why, cash_rng,
                          {"kept": list(prev_h), "new": info["added"], "dropped": info["funded_from"], "rank_of": rank_of,
                           "tactical": VERSION}, notes)
        got = _tech_weight(res.est_weights, tech) if isinstance(res, K.TargetPortfolio) else None
        tried.append({"level": round(lv, 4), "passed": got is not None, "tech_after": got,
                      **({} if got is not None else {"reason": str(getattr(res, "reason", ""))[:160]})})
        if got is None:
            continue
        if best is None or got > best[0]:
            best = (got, res, info)
        if got >= float(minimum):
            break
    rec["levels_tried"] = tried
    if best is None:
        rec.update(status="TECH_OVERWEIGHT_BLOCKED", reason="no overlay level passed Quant's own legality pipeline; Quant result returned untouched",
                   tech_weight_after_overlay=rec["tech_weight_before_overlay"])
        return res0, rec
    got, res, info = best
    reached = got >= float(minimum)
    rec.update(status="TECH_OVERWEIGHT_APPLIED" if reached else "TECH_OVERWEIGHT_PARTIAL", funded_from=info["funded_from"],
               raised_tech_names=info["raised"], added_tech_names=info["added"], tech_weight_after_overlay=got,
               reason="technology >= minimum reached" if reached else
               f"highest compliant attainable technology exposure {got:.2%} < {float(minimum):.0%}: a hard guard (holdings / per-name cap / "
               "cash / Active Share / 30 orders / lots) prevents more")
    return res, rec
