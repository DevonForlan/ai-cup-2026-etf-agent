"""Performance metrics. MDD per 辦法 §五: max over t of (peak_before_t − NAV_t) / peak."""
from __future__ import annotations

from decimal import Decimal

from agent.config import D


def max_drawdown(navs: list, initial=None) -> Decimal:
    series = ([D(initial)] if initial is not None else []) + [D(x) for x in navs]
    peak = None
    mdd = Decimal(0)
    for v in series:
        if peak is None or v > peak:
            peak = v
        elif peak > 0:
            dd = (peak - v) / peak
            if dd > mdd:
                mdd = dd
    return mdd


def mdd_both(navs: list, initial) -> dict:
    return {"include_initial_nav_true": max_drawdown(navs, initial),
            "include_initial_nav_false": max_drawdown(navs, None)}


def summarize(settlements: list, initial_cash) -> dict:
    navs = [s.nav for s in settlements]
    if not navs:
        return {}
    final = settlements[-1]
    init = D(initial_cash)
    daily = []
    prev = init
    for v in navs:
        daily.append((v - prev) / prev if prev else Decimal(0))
        prev = v
    return {
        "days": len(navs),
        "final_nav": final.nav,
        "final_nav_with_accrued_dividends": final.nav_with_accrued,
        "total_return": final.nav_with_accrued / init - 1,
        "mdd": mdd_both(navs, init),
        "cum_turnover": final.cum_turnover,
        "cum_fees": final.cum_fees,
        "cum_tax": final.cum_tax,
        "cost_pct_initial": (final.cum_fees + final.cum_tax) / init,
        "warning_count": final.warning_count,
        "dq": final.dq,
        "dq_reasons": final.dq_reasons,
        "best_day": max(daily),
        "worst_day": min(daily),
        "avg_holdings": sum(len(s.holdings) for s in settlements) / len(settlements),
    }
