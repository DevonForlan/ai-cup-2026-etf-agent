"""derive-orders.v2 (指南 ⑥; schema orders.description):

    target_shares = floor(target_weight × NAV_{T-1} ÷ close_{T-1} ÷ 1000) × 1000
    order_shares  = target_shares − current_shares        (+ = BUY, − = SELL)

All arithmetic in Decimal. Input floats are converted via repr() to keep the JSON literal.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal, localcontext

from agent.config import D


@dataclass(frozen=True)
class DerivedOrder:
    ticker: str
    side: str              # BUY | SELL
    shares: int
    decision_ref: str
    target_shares: int
    current_shares: int
    target_weight: Decimal
    detail: str


def target_shares(target_weight, nav_prev, close_prev, lot_size: int = 1000) -> int:
    w, nav, px = D(target_weight), D(nav_prev), D(close_prev)
    if px <= 0:
        raise ValueError("close price must be > 0")
    if w < 0:
        raise ValueError("target_weight must be >= 0")
    with localcontext() as ctx:
        ctx.prec = 50
        lots = (w * nav / px / Decimal(lot_size)).to_integral_value(rounding=ROUND_FLOOR)
    return int(lots) * lot_size


def derive_order(decision: dict, current_shares: int, nav_prev, close_prev,
                 lot_size: int = 1000) -> DerivedOrder | None:
    tw = D(decision["target_weight"])
    ts = target_shares(tw, nav_prev, close_prev, lot_size)
    diff = ts - int(current_shares)
    if diff == 0:
        return None
    side = "BUY" if diff > 0 else "SELL"
    detail = (f"target_shares = floor({tw}×{D(nav_prev)} / {D(close_prev)} / {lot_size})×{lot_size}"
              f" = {ts:,}；現持 {int(current_shares):,} → {side} {abs(diff):,}")
    return DerivedOrder(decision["ticker"], side, abs(diff), decision["decision_id"], ts,
                        int(current_shares), tw, detail[:300])


def derive_orders(decisions: list[dict], holdings: dict[str, int], nav_prev,
                  closes_prev: dict[str, object], lot_size: int = 1000) -> list[DerivedOrder]:
    out = []
    for d in decisions:
        t = d["ticker"]
        o = derive_order(d, holdings.get(t, 0), nav_prev, closes_prev[t], lot_size)
        if o is not None:
            out.append(o)
    return out


def orders_to_dplan(orders: list[DerivedOrder]) -> list[dict]:
    return [{"ticker": o.ticker, "side": o.side, "shares": o.shares, "decision_ref": o.decision_ref,
             "derivation_detail": o.detail} for o in orders]
