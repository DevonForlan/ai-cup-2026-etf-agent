"""End-to-end: settlement(T-1) -> fixture data -> features -> portfolio -> orders -> D-Plan ->
validation -> settlement(T) -> NAV. Plus a full 24-day synthetic competition."""
import json
from decimal import Decimal

from agent.config import D
from agent.pipeline import day_market, run_day
from agent.run_sim import simulate
from agent.sim.calendar import TradingCalendar
from agent.sim.models import Settlement
from agent.sim.settle import settle


def test_one_day_end_to_end(fixture_store, rb, cfg, tmp_path):
    cal = TradingCalendar(fixture_store.dates())
    d1, d2 = "2026-10-26", "2026-10-27"
    s0 = Settlement.initial(cal.prev(d1), rb.rules.initial_cash)
    r1 = run_day(d1, fixture_store, s0, rb, cfg, team_id="TEAM_TEST", out_dir=tmp_path / "out",
                 log_dir=tmp_path / "logs1", store_is_fixture=True, calendar=cal)
    assert r1.validation.ok, [c.message for c in r1.validation.failures]
    assert not r1.fallback
    doc = json.loads(r1.dplan_path.read_text(encoding="utf-8"))
    assert r1.dplan_path.name == f"D-Plan_TEAM_TEST_{d1}.json"
    assert 20 <= len(doc["decisions"]) <= 30 and len(doc["orders"]) == len(doc["decisions"])
    s1 = settle(s0, doc["orders"], day_market(fixture_store, d1), rb)
    assert not s1.warnings and not s1.trades_void
    # NAV reconciles: Σ shares × close + cash
    m = day_market(fixture_store, d1)
    assert s1.nav == sum(Decimal(s) * m.close[t] for t, s in s1.holdings.items()) + s1.cash
    assert 20 <= len(s1.holdings) <= 30
    # cash moved exactly by executions
    spent = sum(Decimal(e["value"]) + Decimal(e["fee"]) for e in s1.executions if e.get("status") == "FILLED")
    assert abs(s1.cash - (rb.rules.initial_cash - spent)) < Decimal("0.0001")   # Decimal 28-digit VWAP rounding
    # Day 2 continues from settlement 1
    r2 = run_day(d2, fixture_store, s1, rb, cfg, team_id="TEAM_TEST", out_dir=tmp_path / "out",
                 log_dir=tmp_path / "logs2", store_is_fixture=True, calendar=cal)
    assert r2.validation.ok, [c.message for c in r2.validation.failures]
    doc2 = r2.doc
    covered = {d["ticker"] for d in doc2["decisions"]} | {n["ticker"] for n in doc2["no_trade_decisions"]}
    assert set(s1.holdings) <= covered
    s2 = settle(s1, doc2["orders"], day_market(fixture_store, d2), rb)
    assert not s2.warnings
    assert s2.nav > 0


def test_24_day_synthetic_competition(fixture_store, tmp_path):
    summ = simulate("2026-10-26", "2026-11-27", history=fixture_store.root, method="B0_score_tiered",
                    run_id="pytest_24d", fixture=True, out_root=tmp_path, quiet=True)
    assert summ["days"] >= 24
    assert summ["validation_failures"] == 0
    assert summ["illegal_portfolio_days"] == 0
    assert summ["warning_count"] == 0 and not summ["dq"]
    root = tmp_path / "pytest_24d"
    assert (root / "summary.json").exists() and (root / "daily.csv").exists()
    setts = sorted((root / "settlement").glob("*.json"))
    prev = None
    for p in setts:                        # NAV rollover: each day's starting holdings = previous settlement
        s = json.loads(p.read_text(encoding="utf-8"))
        assert 20 <= len(s["holdings"]) <= 30
        if prev is not None:
            assert D(s["cum_fees"]) >= D(prev["cum_fees"])
            assert len(s["nav_history"]) == len(prev["nav_history"]) + 1
        prev = s
