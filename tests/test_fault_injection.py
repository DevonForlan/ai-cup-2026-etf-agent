"""Fault injection: the agent must still produce a legal, validated Quant D-Plan when inputs are
missing or stale."""
import copy

import pandas as pd
import pytest

from agent.data.loaders import HistoryStore
from agent.features.regime import market_regime, regime_score
from agent.pipeline import run_day
from agent.sim.calendar import TradingCalendar
from agent.sim.models import Settlement

D1 = "2026-10-27"


@pytest.mark.parametrize("faults", [{"institutional"}, {"revenue"}, {"etf"}, {"overnight"},
                                    {"institutional", "revenue", "etf", "overnight"}])
def test_missing_inputs_still_valid(fixture_store, rb, cfg, tmp_path, faults):
    s0 = Settlement.initial("x", rb.rules.initial_cash)
    r = run_day(D1, fixture_store, s0, rb, cfg, team_id="TEAM_TEST", out_dir=tmp_path, log_dir=tmp_path,
                store_is_fixture=True, light=True, data_faults=faults)
    assert r.validation.ok, [c.message for c in r.validation.failures]
    assert 20 <= len(r.doc["decisions"]) <= 30


def test_missing_price_day_falls_back(fixture_store, rb, cfg, tmp_path):
    # day 1 builds a legal portfolio; on day 2 the T-1 price file is missing -> fallback D-Plan that
    # keeps the previous portfolio (all no_trade), still schema/semantic valid.
    from agent.pipeline import day_market
    from agent.sim.settle import settle
    cal = TradingCalendar(fixture_store.dates())
    s0 = Settlement.initial("x", rb.rules.initial_cash)
    r1 = run_day("2026-10-23", fixture_store, s0, rb, cfg, team_id="TEAM_TEST", out_dir=tmp_path, log_dir=tmp_path,
                 store_is_fixture=True, light=True, calendar=cal)
    s1 = settle(s0, r1.doc["orders"], day_market(fixture_store, "2026-10-23"), rb)
    s1b = settle(s1, [], day_market(fixture_store, "2026-10-26"), rb)
    st = HistoryStore(tmp_path / "st")
    p = fixture_store.load("daily_prices")
    st.upsert("daily_prices", p[p["date"] != "2026-10-26"])
    st.upsert("institutional", fixture_store.load("institutional"))
    r = run_day(D1, st, s1b, rb, cfg, team_id="TEAM_TEST", out_dir=tmp_path, log_dir=tmp_path,
                store_is_fixture=True, light=True, calendar=cal, use_cache=False)
    assert r.fallback and r.doc["orders"] == []
    assert {n["ticker"] for n in r.doc["no_trade_decisions"]} == set(s1b.holdings)


def test_stale_etf_holdings_still_valid(fixture_store, rb, cfg, tmp_path):
    st = HistoryStore(tmp_path / "st2")
    for t in ("daily_prices", "institutional", "monthly_revenue"):
        st.upsert(t, fixture_store.load(t))
    e = fixture_store.load("etf_holdings").copy()
    e["date"] = "2025-06-02"
    e["is_stale"] = True
    st.upsert("etf_holdings", e)
    s0 = Settlement.initial("x", rb.rules.initial_cash)
    r = run_day(D1, st, s0, rb, cfg, team_id="TEAM_TEST", out_dir=tmp_path, log_dir=tmp_path,
                store_is_fixture=True, light=True)
    assert r.validation.ok


def test_regime_v0_bounds_and_soft_only(cfg):
    s, sig = regime_score({"breadth_above_ma20": 1.0, "ew_index_ret_20d": 0.2, "overnight_sox_ret": 0.05,
                           "tsm_adr_ret": 0.05, "taiex_futures_night_ret": 0.03})
    assert s == 1.0
    s2, _ = regime_score({"breadth_above_ma20": 0.1, "taiex_futures_night_ret": -0.03, "ew_index_vol_20d": 0.6})
    assert s2 == -1.0
    assert regime_score({})[0] is None

    class FS:
        market = {"breadth_above_ma20": 0.1, "taiex_futures_night_ret": -0.03}
    reg = market_regime(FS(), None, cfg)
    assert reg[0] == "risk_off"
    lo, hi = reg[2]
    assert 0 <= lo <= hi < float(0.25)          # soft cash range never breaches the official 25%


def test_regime_enabled_run_is_valid(fixture_store, rb, cfg, tmp_path):
    c = copy.deepcopy(cfg)
    c["regime"]["use_v0"] = True
    s0 = Settlement.initial("x", rb.rules.initial_cash)
    r = run_day(D1, fixture_store, s0, rb, c, team_id="TEAM_TEST", out_dir=tmp_path, log_dir=tmp_path,
                store_is_fixture=True, light=True)
    assert r.validation.ok
