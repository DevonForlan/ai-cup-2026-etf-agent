"""Owner 2026-11-24: TECH_SPRINT (technology as close to 100 % as feasible) over the unchanged Frozen Quant v1."""
from decimal import Decimal

import pandas as pd

from agent.tactical import tech_sprint as SP


def _held():
    """11/24-like book: 15 technology names (one oversized), 5 non-technology names, ~16 % cash."""
    w = {f"T{i:02d}": Decimal("0.04") for i in range(15)}
    w["T00"] = Decimal("0.09")
    w.update({f"N{i}": Decimal("0.03") for i in range(5)})
    return w


TECH = {f"T{i:02d}" for i in range(15)} | {f"P{i:02d}" for i in range(20)}
POOL = [f"P{i:02d}" for i in range(20)]


def test_sprint_sells_nontech_keeps_count_and_reaches_the_level():
    held = _held()
    w, nt, info = SP.plan_sprint(held, TECH, POOL, 0.97, cap=Decimal("0.09"), min_holdings=21, max_holdings=28, max_orders=30)
    assert not any(t.startswith("N") for t in w) and info["sold_nontech"] == [f"N{i}" for i in range(5)]
    assert len(w) == 21 and info["added"] == POOL[:6]                          # 15 kept + 6 best-ranked new names
    assert abs(float(sum(w.values())) - 0.97) < 0.001 and max(w.values()) <= Decimal("0.09")
    assert set(nt) == {f"T{i:02d}" for i in range(1, 15)}                     # within 1pt of 0.97/21 -> untouched (no order)
    assert held["T00"] != w["T00"] and info["orders_planned"] == 5 + 1 + 6 <= 30


def test_sprint_returns_none_when_infeasible():
    held = _held()
    assert SP.plan_sprint(held, TECH, POOL[:2], 0.97, cap=Decimal("0.09"), min_holdings=21, max_holdings=28, max_orders=30) is None  # too few names
    assert SP.plan_sprint(held, TECH, POOL, 0.97, cap=Decimal("0.09"), min_holdings=21, max_holdings=28, max_orders=10) is None      # orders
    assert SP.plan_sprint(held, TECH, POOL, 0.99, cap=Decimal("0.04"), min_holdings=21, max_holdings=28, max_orders=30) is None      # cap


def test_partial_switch_keeps_the_smallest_nontech_untouched_when_orders_bind():
    held = {f"N{i:02d}": Decimal("0.05") + Decimal(i) / Decimal(1000) for i in range(15)} | {f"T{i:02d}": Decimal("0.02") for i in range(6)}
    tech = {f"T{i:02d}" for i in range(6)} | set(POOL)
    assert SP.plan_sprint(held, tech, POOL, 0.95, cap=Decimal("0.09"), min_holdings=21, max_holdings=28, max_orders=30) is None
    w, nt, info = SP.plan_sprint(held, tech, POOL, 0.95, cap=Decimal("0.09"), min_holdings=21, max_holdings=28, max_orders=30,
                                 keep_nontech=3)
    assert info["kept_nontech"] == ["N00", "N01", "N02"] and {"N00", "N01", "N02"} <= nt   # smallest left untouched (no order)
    assert info["orders_planned"] <= 30 and len(w) == 21 and abs(float(sum(w.values())) - 0.95) < 0.001


def test_liquidity_filter():
    rows = [{"date": f"2026-10-{d + 1:02d}", "ticker": t, "close": 100.0, "amount": a}
            for d in range(25) for t, a in (("BIG", 5e8), ("THIN", 1e6))]
    assert SP.liquid(pd.DataFrame(rows), {"BIG", "THIN"}, 3e8) == {"BIG"}
    assert SP.liquid(None, {"A"}, 3e8) == {"A"}


def test_dispatcher_routes_sprint_policy(monkeypatch):
    from agent.tactical import tech_overweight as TW
    seen = {}

    def fake(*a, fallback=None, **k):
        seen["fallback"] = fallback
        return "RES", {"policy": "sprint"}
    monkeypatch.setattr(SP, "run_overlay_sprint", fake)
    res, rec = TW.run_overlay(None, None, None, None, None, None, None, None, None, None, {"policy": "sprint"}, set())
    assert res == "RES" and rec["policy"] == "sprint" and callable(seen["fallback"])
