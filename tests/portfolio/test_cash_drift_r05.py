"""Round 05 regression: a passively drifted portfolio (cash inflow / crash -> cash > 25%) must be repaired by a
legal rebalance, never carried forward (an illegal fallback would earn a warning every day).
Bug 1: the no-trade band kept diluted names, so the capped traded names could not absorb the cash.
Bug 2: NO_TRADE names declared their water-fill target instead of their current weight (false R_CASH_NEG)."""
from decimal import Decimal

import pytest

from agent.config import load_strategy
from agent.pipeline import day_market, run_day
from agent.sim.calendar import TradingCalendar
from agent.sim.models import Settlement
from agent.sim.settle import settle


@pytest.fixture(scope="module")
def settled_day1(fixture_store, rb, tmp_path_factory):
    cfg = load_strategy("config/strategy_quant_v1.yaml")
    cal = TradingCalendar(fixture_store.dates())
    s0 = Settlement.initial(cal.prev("2026-10-26"), rb.rules.initial_cash)
    d = tmp_path_factory.mktemp("cd")
    r1 = run_day("2026-10-26", fixture_store, s0, rb, cfg, team_id="TEAM_TEST", out_dir=d, log_dir=None,
                 store_is_fixture=True, calendar=cal)
    s1 = settle(s0, r1.doc["orders"], day_market(fixture_store, "2026-10-26"), rb)
    s1.agent_state = r1.agent_state
    return s1, cfg, cal, d


@pytest.mark.parametrize("inflow", ["0.3", "0.6", "1.5"])
def test_cash_drift_is_rebalanced_legally(settled_day1, fixture_store, rb, inflow):
    s1, cfg, cal, d = settled_day1
    s = Settlement.from_dict(s1.to_dict())
    extra = s.nav * Decimal(inflow)
    s.cash += extra
    s.nav += extra
    assert s.cash / s.nav > rb.rules.cash_max_weight                    # previous portfolio is illegal
    r = run_day("2026-10-27", fixture_store, s, rb, cfg, team_id="TEAM_TEST", out_dir=d, log_dir=None,
                store_is_fixture=True, calendar=cal)
    assert not r.fallback and r.validation.ok, [c.message for c in r.validation.failures]
    assert r.doc["orders"] and r.result.cash_weight_est < rb.rules.cash_max_weight
    declared = sum(Decimal(str(x["target_weight"])) for x in r.doc["decisions"] + r.doc["no_trade_decisions"]
                   if x.get("target_weight") is not None)
    assert declared <= 1


def test_small_drift_still_holds(settled_day1, fixture_store, rb):
    """Inside the legal range the frozen hold behaviour is unchanged (no orders)."""
    s1, cfg, cal, d = settled_day1
    s = Settlement.from_dict(s1.to_dict())
    extra = s.nav * Decimal("0.05")
    s.cash += extra
    s.nav += extra
    r = run_day("2026-10-27", fixture_store, s, rb, cfg, team_id="TEAM_TEST", out_dir=d, log_dir=None,
                store_is_fixture=True, calendar=cal)
    assert r.validation.ok and r.doc["orders"] == []
