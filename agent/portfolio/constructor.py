"""Baseline portfolio constructor. Always returns either a fully legal TargetPortfolio or
FallbackToPreviousPortfolio — never a half-legal result.

Pipeline: score rank -> selection (turnover-aware) -> tiered/equal weights -> strategy caps
-> lot feasibility -> no-trade band -> cash band -> Active Share -> decisions/orders
-> pre-trade + post-trade(estimated) + stress compliance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

import pandas as pd

from agent.config import D
from agent.engine import compliance as C
from agent.engine.active_share import compute_active_share
from agent.engine.fees import buy_cost, sell_cost
from agent.engine.models import Report, Status
from agent.engine.orders import DerivedOrder, derive_orders, target_shares
from agent.engine.rules import RuleBook
from agent.portfolio import baseline as B
from agent.portfolio.decisions import PlannedDecision, enforce_decision_limit, plan_decisions

Q = Decimal("0.000001")


@dataclass
class TargetPortfolio:
    weights: dict[str, Decimal]               # target weights for all names held after today
    cash_weight_est: Decimal
    plan: list[PlannedDecision]
    orders: list[DerivedOrder]
    regime: str
    stance: str
    regime_why: str
    cash_range: tuple[float, float]
    selection: dict
    est_holdings: dict[str, int]
    est_cash: Decimal
    est_nav: Decimal
    est_weights: dict[str, Decimal]
    active_share: object | None
    reports: list[Report] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    is_fallback: bool = False


@dataclass
class FallbackToPreviousPortfolio:
    reason: str
    reports: list[Report] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    is_fallback: bool = True


def _caps(tickers, rb: RuleBook, cfg) -> dict[str, Decimal]:
    sb = cfg["strategy_buffers"]
    return {t: D(sb["tsmc_target_cap"]) if t == rb.rules.tsmc_ticker else D(sb["other_target_cap"]) for t in tickers}


def estimate(orders: list[DerivedOrder], prev_h: dict[str, int], prev_cash: Decimal, closes: dict,
             rb: RuleBook, buy_shift: Decimal = Decimal(0), sell_shift: Decimal = Decimal(0)):
    """Holdings / cash after orders, fills at close×(1+shift), fees included; NAV at close."""
    h = {t: s for t, s in prev_h.items() if s > 0}
    cash = D(prev_cash)
    mode = rb.assumptions.fee_rounding_mode
    for o in orders:
        px = D(closes[o.ticker])
        if o.side == "BUY":
            v = Decimal(o.shares) * px * (1 + buy_shift)
            cash -= v + buy_cost(v, rb.rules, mode)
            h[o.ticker] = h.get(o.ticker, 0) + o.shares
        else:
            v = Decimal(o.shares) * px * (1 - sell_shift)
            f, tx = sell_cost(v, rb.rules, mode)
            cash += v - f - tx
            h[o.ticker] = h.get(o.ticker, 0) - o.shares
    h = {t: s for t, s in h.items() if s != 0}
    nav = sum((Decimal(s) * D(closes[t]) for t, s in h.items()), Decimal(0)) + cash
    w = {t: Decimal(s) * D(closes[t]) / nav for t, s in h.items()} if nav > 0 else {}
    return h, cash, nav, w


def _try_hold(prev_h, prev_cash, nav_prev, closes_prev, rb, cfg, scores, etf_holdings, etf_meta,
              regime, stance, why, cash_rng):
    """Non-rebalance day: keep every holding (all NO_TRADE) if the unchanged portfolio passes all
    official checks at T-1 close and every name is still eligible. Otherwise return None."""
    elig = scores["eligible"].to_dict() if "eligible" in scores else {}
    if any(not elig.get(t, False) for t in prev_h):
        return None
    rep = C.check_portfolio(prev_h, closes_prev, prev_cash, rb, "維持(預估)", "post_trade_estimate")
    _, _, est_nav, est_w = estimate([], prev_h, prev_cash, closes_prev, rb)
    as_res = None
    if etf_holdings:
        as_res = compute_active_share(est_w, etf_holdings, rb.active_etfs, rb.assumptions.active_share_mode,
                                      (etf_meta or {}).get("date"), (etf_meta or {}).get("synthetic", False))
        C.check_active_share(as_res, rb, None, rep)
    caps = _caps(prev_h, rb, cfg)
    if rep.failures or any(est_w[t] > caps[t] + D("0.01") for t in est_w):
        return None
    w = {t: est_w[t].quantize(Q, rounding="ROUND_FLOOR") for t in prev_h}
    plan = [PlannedDecision(t, "NO_TRADE", w[t], s, s, "no_rebalance_day") for t, s in sorted(prev_h.items())]
    rank_of = {t: int(r) for t, r in scores["rank"].dropna().items()} if "rank" in scores else {}
    return TargetPortfolio(w, prev_cash / est_nav, plan, [], regime, stance, why, cash_rng,
                           {"kept": list(prev_h), "new": [], "dropped": [], "rank_of": rank_of, "hold_mode": True},
                           dict(prev_h), prev_cash, est_nav, est_w, as_res, [rep], ["非再平衡日：維持組合"])


def construct(scores: pd.DataFrame, prev_holdings: dict[str, int], prev_cash: Decimal, nav_prev: Decimal,
              closes_prev: dict, rb: RuleBook, cfg: dict, market: dict,
              etf_holdings: dict | None = None, etf_meta: dict | None = None,
              method: str | None = None, holding_days: dict[str, int] | None = None,
              is_rebalance_day: bool = True, regime_override: tuple | None = None
              ) -> TargetPortfolio | FallbackToPreviousPortfolio:
    sb = cfg["strategy_buffers"]
    tparams = B.turnover_params(cfg)
    method = method or cfg["baseline"]["method"]
    lot = rb.rules.lot_size
    notes: list[str] = []
    nav_prev = D(nav_prev)
    prev_h = {t: int(s) for t, s in prev_holdings.items() if int(s) > 0}
    missing_px = [t for t in prev_h if closes_prev.get(t) is None]
    if missing_px:
        return FallbackToPreviousPortfolio(f"前日持股缺收盤價 {missing_px}")

    regime, stance, cash_rng, why = regime_override or B.regime_from_market(market, cfg)
    if not is_rebalance_day and prev_h:
        held = _try_hold(prev_h, D(prev_cash), nav_prev, closes_prev, rb, cfg, scores, etf_holdings, etf_meta,
                         regime, stance, why, cash_rng)
        if held is not None:
            return held
        notes.append("非再平衡日但維持現有組合未通過檢查 → 改為完整再平衡")
    cash_lo = max(D(cash_rng[0]), D(sb["cash_target_min"]) if regime != "risk_on" else D(cash_rng[0]))
    cash_hi = min(D(cash_rng[1]), D("0.20"))
    cash_mid = (cash_lo + cash_hi) / 2

    exclude: set[str] = set()
    for attempt in range(6):
        sel, info = B.select_names(scores, prev_h, cfg, exclude, holding_days)
        if len(sel) < rb.rules.holdings_min:
            return FallbackToPreviousPortfolio(f"可選標的不足 {len(sel)} 檔")
        raw = B.equal_raw_weights(sel) if method in ("B1_score_equal", "B2_momentum", "B3_institutional") \
            else B.tiered_raw_weights(sel, cfg)
        caps = _caps(sel, rb, cfg)
        w = B.water_fill(raw, Decimal(1) - cash_mid, caps)
        # lot feasibility: a name whose target rounds to 0 lots is excluded and selection retried
        zero = [t for t, x in w.items() if target_shares(x, nav_prev, closes_prev[t], lot) == 0]
        if zero:
            exclude |= set(zero)
            notes.append(f"整張不可行剔除 {zero}")
            continue
        break
    else:
        return FallbackToPreviousPortfolio("整張可行性調整超過次數")

    # no-trade band for existing holdings
    band = D(str(tparams["rebalance_threshold"]))
    no_trade: set[str] = set()
    cur_w = {t: Decimal(s) * D(closes_prev[t]) / nav_prev for t, s in prev_h.items()}
    for t in sel:
        if t in prev_h and abs(w[t] - cur_w[t]) < band and cur_w[t] <= caps[t]:
            no_trade.add(t)
    # re-balance the traded names so expected cash stays inside [cash_lo, cash_hi]
    for _ in range(3):
        eff = {t: (cur_w[t] if t in no_trade else w[t]) for t in sel}
        cash_est = 1 - sum(eff.values(), Decimal(0))
        if cash_lo <= cash_est <= cash_hi:
            break
        traded = [t for t in sel if t not in no_trade]
        if not traded:
            break
        fixed = sum((cur_w[t] for t in no_trade), Decimal(0))
        target_traded = (1 - cash_mid) - fixed
        sub = B.water_fill({t: float(w[t]) for t in traded}, target_traded, {t: caps[t] for t in traded})
        w.update(sub)

    # Active Share (strategy target is stricter than the official 20%)
    as_res = None
    as_target = D(sb["active_share_target"])
    if etf_holdings:
        for i in range(15):
            eff = {t: (cur_w[t] if t in no_trade else w[t]) for t in sel}
            as_res = compute_active_share(eff, etf_holdings, rb.active_etfs, rb.assumptions.active_share_mode,
                                          (etf_meta or {}).get("date"), (etf_meta or {}).get("synthetic", False))
            if as_res.minimum_active_share is None or as_res.minimum_active_share >= as_target:
                break
            bench = etf_holdings[as_res.benchmark_ticker]
            overlap = sorted([t for t in sel if t in bench and t not in no_trade],
                             key=lambda t: -min(w[t], D(bench[t])))
            free = [t for t in sel if t not in bench and t not in no_trade and w[t] < caps[t]]
            if not overlap or not free:
                break
            t0 = overlap[0]
            cut = min(Decimal("0.01"), w[t0] - Decimal("0.01"))
            if cut <= 0:
                break
            w[t0] -= cut
            room = {t: caps[t] - w[t] for t in free}
            tot = sum(room.values(), Decimal(0))
            for t in free:
                w[t] = (w[t] + cut * room[t] / tot).quantize(Q, rounding="ROUND_FLOOR")
            notes.append(f"Active Share 調整：{t0} −{cut}")

    s_shift = D(sb["stress_price_shift"])
    scale = Decimal(1)
    for attempt in range(4):
        target_w = {t: (w[t] if t in no_trade else w[t] * scale).quantize(Q, rounding="ROUND_FLOOR") for t in sel}
        plan = plan_decisions(target_w, prev_h, no_trade, nav_prev, closes_prev, lot)
        plan = enforce_decision_limit(plan, 30)
        decisions = [{"ticker": p.ticker, "decision_id": f"tmp{i}", "target_weight": float(p.target_weight)}
                     for i, p in enumerate(plan) if p.action != "NO_TRADE"]
        orders = derive_orders(decisions, prev_h, nav_prev, closes_prev, lot)
        if len(orders) > 30:
            return FallbackToPreviousPortfolio(f"委託筆數 {len(orders)} > 30")
        # stress: buys +5% / sells -5% must not push cash negative -> otherwise raise the cash buffer and retry
        _, c_bad, n_bad, _ = estimate(orders, prev_h, D(prev_cash), closes_prev, rb, s_shift, s_shift)
        if c_bad >= 0 or attempt == 3:
            break
        traded_w = sum((target_w[t] for t in sel if t not in no_trade), Decimal(0))
        need = (-c_bad) / n_bad + Decimal("0.005")
        if traded_w <= need:
            break
        scale = scale * (1 - need / traded_w)
        notes.append(f"壓力測試現金不足，交易部位權重縮放 ×{float(scale):.4f}")

    reports = []
    pre = C.check_target_weights(target_w, rb, "目標")
    reports.append(pre)
    est_h, est_cash, est_nav, est_w = estimate(orders, prev_h, D(prev_cash), closes_prev, rb)
    post = C.check_portfolio(est_h, closes_prev, est_cash, rb, "委託後(預估)", "post_trade_estimate")
    C.check_orders([{"ticker": o.ticker, "side": o.side, "shares": o.shares} for o in orders], prev_h, rb, post)
    if etf_holdings:
        as_res = compute_active_share(est_w, etf_holdings, rb.active_etfs, rb.assumptions.active_share_mode,
                                      (etf_meta or {}).get("date"), (etf_meta or {}).get("synthetic", False))
    if as_res is not None:
        C.check_active_share(as_res, rb, as_target, post)
    else:
        post.add("R_ACTIVE_SHARE", Status.UNKNOWN, "無主動 ETF 持股資料", None, rb.rules.active_share_min,
                 C.SRC["R_ACTIVE_SHARE"])
    reports.append(post)
    stress = Report("stress")
    for name, bs, ss in (("buy+5%/sell-5%", s_shift, s_shift), ("buy-5%/sell+5%", -s_shift, -s_shift)):
        _, c2, n2, _ = estimate(orders, prev_h, D(prev_cash), closes_prev, rb, bs, ss)
        cw = c2 / n2 if n2 > 0 else Decimal(0)
        ok = c2 >= 0 and cw < rb.rules.cash_max_weight
        stress.add("STRESS_CASH", Status.PASS if ok else Status.FAIL, f"{name}: 現金 {c2:,.0f}（{float(cw):.3%}）",
                   cw, [0, rb.rules.cash_max_weight], "策略壓力測試（非官方）")
    reports.append(stress)
    fails = [c for r in reports for c in r.failures]
    if fails:
        return FallbackToPreviousPortfolio("合規檢查失敗：" + "; ".join(f"{c.rule_id} {c.message}" for c in fails[:5]),
                                           reports, notes)
    return TargetPortfolio(target_w, est_cash / est_nav, plan, orders, regime, stance, why, cash_rng, info,
                           est_h, est_cash, est_nav, est_w, as_res, reports, notes)
