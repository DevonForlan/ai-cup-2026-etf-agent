"""market_view.posture is DERIVED from the orders (C12), never free-written.

net flow = Σ BUY value − Σ SELL value at T-1 close.
  |net| <= tolerance (2% NAV)  -> hold ; net > tol -> increase ; net < −tol -> reduce
target_cash_pct_range must contain the estimated post-trade cash ratio (computed with and
without fees, since whether the server includes fees is unconfirmed)."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from agent.config import D
from agent.engine.fees import buy_cost, sell_cost
from agent.engine.rules import RuleBook


@dataclass
class Posture:
    net_exposure_intent: str
    target_cash_pct_range: tuple[float, float]
    net_flow: Decimal
    nav: Decimal
    cash_ratio_no_fee: Decimal
    cash_ratio_with_fee: Decimal


def cash_ratio_after(orders: list[dict], prev_cash, nav, closes, rb: RuleBook, include_fees: bool,
                     exclude_refs: set[str] | None = None) -> Decimal:
    cash = D(prev_cash)
    fees = Decimal(0)
    mode = rb.assumptions.fee_rounding_mode
    for o in orders:
        if exclude_refs and o["decision_ref"] in exclude_refs:
            continue
        v = Decimal(int(o["shares"])) * D(closes[o["ticker"]])
        if o["side"] == "BUY":
            cash -= v
            if include_fees:
                f = buy_cost(v, rb.rules, mode)
                cash -= f; fees += f
        else:
            cash += v
            if include_fees:
                f, t = sell_cost(v, rb.rules, mode)
                cash -= f + t; fees += f + t
    n = D(nav) - fees
    return cash / n if n > 0 else Decimal(0)


def derive_posture(orders: list[dict], prev_cash, nav, closes, rb: RuleBook,
                   declared_range: tuple[float, float], margin: float = 0.01) -> Posture:
    nav = D(nav)
    nf = sum((Decimal(int(o["shares"])) * D(closes[o["ticker"]]) * (1 if o["side"] == "BUY" else -1)
              for o in orders), Decimal(0))
    tol = rb.rules.c12_hold_tolerance_nav * nav
    intent = "hold" if abs(nf) <= tol else ("increase" if nf > 0 else "reduce")
    r0 = cash_ratio_after(orders, prev_cash, nav, closes, rb, False)
    r1 = cash_ratio_after(orders, prev_cash, nav, closes, rb, True)
    lo_e, hi_e = min(r0, r1), max(r0, r1)
    lo = max(0.0, min(float(declared_range[0]), float(lo_e) - margin))
    hi = min(float(rb.rules.cash_max_weight), max(float(declared_range[1]), float(hi_e) + margin))
    lo, hi = round(lo, 4), round(hi, 4)
    if lo > float(lo_e):
        lo = max(0.0, round(float(lo_e) - 0.0001, 4))
    if hi < float(hi_e):
        hi = min(float(rb.rules.cash_max_weight), round(float(hi_e) + 0.0001, 4))
    return Posture(intent, (lo, hi), nf, nav, r0, r1)
