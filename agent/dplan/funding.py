"""funding_for (C14) is DERIVED: sells are flagged as funding only when the gap really exists,
i.e. removing all flagged sells drops the estimated cash ratio below the declared lower bound."""
from __future__ import annotations

from decimal import Decimal

from agent.config import D
from agent.dplan.posture import cash_ratio_after
from agent.engine.rules import RuleBook


def derive_funding(decisions: list[dict], orders: list[dict], prev_cash, nav, closes, rb: RuleBook,
                   cash_lo: float) -> dict[str, list[str]]:
    """Returns {sell_decision_id: [buy_decision_ids (<=5)]} or {} if no gap exists."""
    sells = [d["decision_id"] for d in decisions if d["action"] in ("TRIM", "SELL_ALL")]
    buys = [d for d in decisions if d["action"] in ("BUY", "ADD")]
    if not sells or not buys:
        return {}
    ex = set(sells)
    # gap must exist under both fee assumptions (server behaviour unconfirmed)
    r_hi = max(cash_ratio_after(orders, prev_cash, nav, closes, rb, f, ex) for f in (False, True))
    if not r_hi < D(cash_lo):
        return {}
    val = {o["decision_ref"]: Decimal(int(o["shares"])) * D(closes[o["ticker"]]) for o in orders if o["side"] == "BUY"}
    top = sorted((b["decision_id"] for b in buys if b["decision_id"] in val), key=lambda k: -val[k])[:5]
    return {s: top for s in sells} if top else {}
