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


def test_cash_is_deployed_when_every_holding_is_inside_the_band():
    """2026-11-26 regression: 21 technology names at 4.0-4.85 %, 6.2 % cash. Every name was within 1pt of 0.99/21, so the plan
    left everything untouched (0 orders, 93.8 %). The level must be reached by raising the names below the target."""
    held = {f"T{i:02d}": Decimal("0.0400") + Decimal(i) / Decimal(2500) for i in range(21)}   # 4.00 % .. 4.80 %
    tech = set(held)
    total = sum(held.values())
    assert Decimal("0.92") < total < Decimal("0.95")                            # ~92.4 % invested
    w, nt, info = SP.plan_sprint(held, tech, [], 0.99, cap=Decimal("0.09"), min_holdings=21, max_holdings=28, max_orders=30)
    assert abs(float(sum(w.values())) - 0.99) < 0.001 and len(w) == 21
    per = Decimal("0.99") / 21
    assert all(held[t] >= per for t in nt)                                       # only names at/above the target stay untouched
    assert all(w[t] > held[t] for t in w if t not in nt) and info["orders_planned"] >= 1   # buys only, no sells


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


def test_supersede_same_policy_needs_the_explicit_flag(monkeypatch):
    """2026-11-26: a FINAL built under the SAME policy is superseded only with --allow-same-policy (fixed implementation)."""
    from datetime import datetime
    from agent.ops import morning_final as MF
    from agent.ops import scheduled_run as SR
    from agent.ops import tactical_supersede as TS
    from agent.ops import team as TM
    from agent.submission import base as SB
    monkeypatch.setattr(SR, "run_mode", lambda ops: "COMPETITION")
    monkeypatch.setattr(SR, "holidays", lambda ops: set())
    monkeypatch.setattr(TM, "resolve", lambda mode, ops: {"status": "OK"})
    monkeypatch.setattr(MF, "plan", lambda now, hol, ops, trade_date=None: {"action": "RUN", "trade_date": "2026-11-26"})
    monkeypatch.setattr(SB, "get_state", lambda t, ops: {"state": SB.CONFIRMED})
    monkeypatch.setattr(TS, "_prior_policy", lambda t, ops, prior: "sprint")
    args = ({"reasons": []}, {"policy": "sprint"}, {"sha256": "sha256:ab"}, "2026-11-26", {}, datetime(2026, 11, 26, 1, 0))
    blocked = TS._tech_preconditions(*args)
    assert not blocked["ok"] and any("already built under policy sprint" in r for r in blocked["reasons"])
    allowed = TS._tech_preconditions({"reasons": []}, *args[1:], allow_same_policy=True)
    assert allowed["ok"] and allowed["allow_same_policy"] is True
