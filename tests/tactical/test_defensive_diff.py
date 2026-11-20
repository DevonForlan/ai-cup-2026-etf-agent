"""Owner 2026-11-20 option B: DEFENSIVE_DIFFERENTIATION (low-volatility non-technology + cash) over the unchanged Frozen Quant v1."""
from decimal import Decimal

import pandas as pd

from agent.tactical import defensive_diff as DD


def _held(n_tech=21, n_non=0):
    w = {f"T{i:02d}": Decimal("0.045") - Decimal(i) / Decimal(2000) for i in range(n_tech)}
    w.update({f"N{i:02d}": Decimal("0.02") for i in range(n_non)})
    return w


def test_transition_respects_30_orders_and_20_30_holdings_and_sells_the_largest_tech_first():
    held = _held()
    tech = {t for t in held if t.startswith("T")}
    pool = [f"P{i:02d}" for i in range(40)]
    best = None
    for s in range(len(tech), 0, -1):
        p = DD.plan_transition(held, tech, pool, s, cash_target=0.16, cap=Decimal("0.09"), min_holdings=21, max_holdings=28,
                               max_orders=30)
        if p is not None:
            best = (s, p)
            break
    s, (w, keep, info) = best
    assert s == 15                                            # 15 sells + 15 buys = 30 orders, 6 + 15 = 21 holdings
    orders = len(info["sold_tech"]) + len(info["added"])
    assert orders <= 30 and 21 <= len(w) <= 28
    assert info["sold_tech"] == sorted(tech, key=lambda t: -held[t])[:15]          # largest technology positions go first
    assert set(info["kept_tech"]) == keep and all(w[t] == held[t] for t in keep)  # kept names are untouched (no order)
    assert info["added"] == pool[:15]                                              # lowest-volatility pool names first
    cash = 1 - float(sum(w.values()))
    assert 0.15 <= cash <= 0.17 and max(w.values()) <= Decimal("0.09")


def test_transition_returns_none_when_the_counts_cannot_work():
    held = _held()
    tech = set(held)
    assert DD.plan_transition(held, tech, ["P1"], 15, cash_target=0.16, cap=Decimal("0.09"), min_holdings=21, max_holdings=28,
                              max_orders=30) is None                               # not enough pool names


def test_volatility_pool_excludes_tech_and_illiquid_and_sorts_by_volatility():
    rows = []
    for d in range(30):
        date = f"2026-10-{d + 1:02d}"
        rows += [{"date": date, "ticker": "CALM", "close": 100 + (d % 2) * 0.5, "amount": 5e8},
                 {"date": date, "ticker": "WILD", "close": 100 + (d % 2) * 8, "amount": 5e8},
                 {"date": date, "ticker": "THIN", "close": 100, "amount": 1e6},
                 {"date": date, "ticker": "TECH", "close": 100, "amount": 5e8}]
    pool = DD.volatility_pool(pd.DataFrame(rows), {"CALM", "WILD", "THIN", "TECH"}, {"TECH"}, 60, 3e8)
    assert [t for t, _ in pool] == ["CALM", "WILD"]


def test_equal_resize_keeps_cash_target_and_cap():
    w = DD.equal_resize({f"N{i}": Decimal("0.03") for i in range(21)}, 0.16, Decimal("0.09"))
    assert len(w) == 21 and abs(1 - float(sum(w.values())) - 0.16) < 0.001


def test_dispatcher_routes_defensive_policy(monkeypatch):
    from agent.tactical import tech_overweight as TW
    seen = {}

    def fake(*a, fallback=None, **k):
        seen["called"], seen["fallback"] = True, fallback
        return "RES", {"policy": "defensive"}
    monkeypatch.setattr(DD, "run_overlay_defensive", fake)
    res, rec = TW.run_overlay(None, None, None, None, None, None, None, None, None, None, {"policy": "defensive"}, set())
    assert res == "RES" and rec["policy"] == "defensive" and seen["called"] and callable(seen["fallback"])
