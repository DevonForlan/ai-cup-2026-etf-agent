"""Transaction costs (辦法 §六(十一); 指南 ⑥). Rounding mode is UNCONFIRMED (NC-5) -> parameter."""
from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from agent.config import OfficialRules

ROUNDING_MODES = ("exact", "round_half_up", "floor", "ceil")


def round_money(x: Decimal, mode: str) -> Decimal:
    if mode == "exact":
        return x
    if mode == "round_half_up":
        return x.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    if mode == "floor":
        return x.quantize(Decimal(1), rounding=ROUND_FLOOR)
    if mode == "ceil":
        return x.quantize(Decimal(1), rounding=ROUND_CEILING)
    raise ValueError(f"unknown fee rounding mode {mode!r} (allowed {ROUNDING_MODES})")


def buy_cost(value: Decimal, rules: OfficialRules, mode: str = "exact") -> Decimal:
    """Fee on a buy of `value` TWD."""
    return round_money(value * rules.buy_fee_rate, mode)


def sell_cost(value: Decimal, rules: OfficialRules, mode: str = "exact") -> tuple[Decimal, Decimal]:
    """(fee, tax) on a sell of `value` TWD. Each rounded separately."""
    fee = round_money(value * rules.sell_fee_rate, mode)
    tax = round_money(value * rules.transaction_tax_rate, mode)
    return fee, tax
