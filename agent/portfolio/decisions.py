"""Map target weights vs previous holdings to D-Plan decision actions.

  prev = 0, target > 0            -> BUY
  prev > 0, target = 0            -> SELL_ALL (target_weight 0)
  prev > 0, in no-trade band      -> no_trade
  prev > 0, derived shares higher -> ADD ; lower -> TRIM ; equal -> no_trade
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from agent.engine.orders import target_shares


@dataclass
class PlannedDecision:
    ticker: str
    action: str              # BUY | ADD | TRIM | SELL_ALL | NO_TRADE
    target_weight: Decimal
    current_shares: int
    target_shares: int
    reason: str              # machine reason code


def plan_decisions(target_w: dict[str, Decimal], prev_holdings: dict[str, int], no_trade: set[str],
                   nav_prev: Decimal, closes_prev: dict, lot: int = 1000) -> list[PlannedDecision]:
    out = []
    tickers = sorted(set(target_w) | {t for t, s in prev_holdings.items() if s > 0})
    for t in tickers:
        cur = int(prev_holdings.get(t, 0))
        w = target_w.get(t, Decimal(0))
        if cur > 0 and t in no_trade:
            out.append(PlannedDecision(t, "NO_TRADE", w, cur, cur,
                                       "odd_lot_locked" if cur % lot else "no_trade_band"))
            continue
        ts = target_shares(w, nav_prev, closes_prev[t], lot) if w > 0 else 0
        if cur == 0 and ts > 0:
            out.append(PlannedDecision(t, "BUY", w, cur, ts, "new_selection"))
        elif cur == 0:
            continue
        elif w == 0:
            out.append(PlannedDecision(t, "SELL_ALL", Decimal(0), cur, 0, "deselected"))
        elif ts > cur:
            out.append(PlannedDecision(t, "ADD", w, cur, ts, "rebalance_up"))
        elif ts < cur:
            out.append(PlannedDecision(t, "TRIM", w, cur, ts, "rebalance_down"))
        else:
            out.append(PlannedDecision(t, "NO_TRADE", w, cur, cur, "same_lots"))
    return out


def enforce_decision_limit(plan: list[PlannedDecision], max_decisions: int = 30) -> list[PlannedDecision]:
    """D-Plan decisions maxItems=30. Demote the smallest ADD/TRIM changes to NO_TRADE if needed."""
    trades = [p for p in plan if p.action != "NO_TRADE"]
    if len(trades) <= max_decisions:
        return plan
    adjustable = sorted([p for p in trades if p.action in ("ADD", "TRIM")],
                        key=lambda p: abs(p.target_shares - p.current_shares))
    excess = len(trades) - max_decisions
    demote = {p.ticker for p in adjustable[:excess]}
    return [PlannedDecision(p.ticker, "NO_TRADE", p.target_weight, p.current_shares, p.current_shares,
                            "decision_limit") if p.ticker in demote else p for p in plan]
