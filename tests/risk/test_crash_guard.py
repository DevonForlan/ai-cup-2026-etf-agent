import copy
from decimal import Decimal

import pytest

from agent.config import D
from agent.data.pit import PITView
from agent.features.feature_engine import build_features
from agent.pipeline import etf_holdings_from_view, run_day
from agent.portfolio.constructor import TargetPortfolio, construct
from agent.portfolio.ranking import score
from agent.risk import crash_guard as CG
from agent.sim.models import Settlement

CALM = {"universe_median_ret_5d": 0.01, "ew_index_ret_20d": 0.02, "ew_index_vol_20d": 0.15,
        "breadth_above_ma20": 0.6, "overnight_sox_ret": 0.005, "tsm_adr_ret": 0.004,
        "taiex_futures_night_ret": 0.002}
CRASH = {"universe_median_ret_5d": -0.09, "ew_index_ret_20d": -0.15, "ew_index_vol_20d": 0.6,
         "breadth_above_ma20": 0.05, "overnight_sox_ret": -0.07, "tsm_adr_ret": -0.07,
         "taiex_futures_night_ret": -0.04}
GUARD_ON = {"crash_guard": {"enabled": True}}


def test_points_and_states():
    assert CG.stress_points(CALM, 0.0, CG.params(GUARD_ON))[0] == 0
    pts, det = CG.stress_points(CRASH, 0.12, CG.params(GUARD_ON))
    assert pts == 16 and det["port_dd"][1] == 2
    s = CG.step(None, CRASH, 0.0, GUARD_ON)
    assert s["state"] == "CRISIS" and s["allow_new"] is False and s["cash"][1] < 0.25


def test_hysteresis_one_level_after_two_calm_days():
    s = CG.step(None, CRASH, 0.0, GUARD_ON)                    # escalate immediately
    assert s["state"] == "CRISIS"
    s = CG.step(s, CALM, 0.0, GUARD_ON)
    assert s["state"] == "CRISIS" and s["calm_days"] == 1
    s = CG.step(s, CALM, 0.0, GUARD_ON)
    assert s["state"] == "RISK_OFF"                            # one level down only
    for exp in ("RISK_OFF", "CAUTION", "CAUTION", "NORMAL"):
        s = CG.step(s, CALM, 0.0, GUARD_ON)
        assert s["state"] == exp
    s2 = CG.step(s, {**CALM, "taiex_futures_night_ret": -0.035, "breadth_above_ma20": 0.1}, 0.0, GUARD_ON)
    assert s2["state"] == "RISK_OFF"                           # (2+2 points) re-escalation is immediate


def test_cash_ranges_below_official():
    for st in CG.DEFAULT["states"].values():
        assert 0 <= st["cash"][0] <= st["cash"][1] < 0.25


def test_portfolio_drawdown():
    assert CG.portfolio_drawdown([["d1", "110"], ["d2", "99"]], 100) == pytest.approx(0.1)
    assert CG.portfolio_drawdown([], None) == 0.0


def _setup(fixture_store, rb, cfg):
    T = "2026-10-27"
    v = PITView(fixture_store, f"{T}T07:00:00+08:00")
    fs = build_features(v, sorted(rb.universe), T)
    sc = score(fs.features, cfg["score_weights"])
    closes = {t: D(round(float(x), 4)) for t, x in fs.features["close_prev"].dropna().items()}
    etf, meta = etf_holdings_from_view(v)
    tp = construct(sc, {}, rb.rules.initial_cash, rb.rules.initial_cash, closes, rb, cfg, fs.market, etf, meta)
    held = tp.est_holdings
    nav = sum(Decimal(s) * closes[t] for t, s in held.items()) + tp.est_cash
    return fs, sc, closes, etf, meta, held, tp.est_cash, nav


def test_deleveraging_capped_per_day(fixture_store, rb, cfg):
    fs, sc, closes, etf, meta, held, cash, nav = _setup(fixture_store, rb, cfg)
    g = CG.step(None, CRASH, 0.0, GUARD_ON)
    g["high_vol"] = []
    r = construct(sc, held, cash, nav, closes, rb, cfg, fs.market, etf, meta, guard=g)
    assert isinstance(r, TargetPortfolio), getattr(r, "reason", "")
    assert all(o.side == "SELL" for o in r.orders)                       # trims only, no name changes
    assert set(r.est_holdings) == set(held)
    sold = sum(Decimal(o.shares) * closes[o.ticker] for o in r.orders)
    assert sold / nav <= Decimal("0.10") + Decimal("0.002")              # max_deleveraging_per_day
    assert r.cash_weight_est > cash / nav                               # cash raised


def test_vol_cap_and_no_new_entries(fixture_store, rb, cfg):
    fs, sc, closes, etf, meta, held, cash, nav = _setup(fixture_store, rb, cfg)
    big = max(held, key=lambda t: held[t] * closes[t])
    g = CG.step(None, {**CALM, "taiex_futures_night_ret": -0.035, "breadth_above_ma20": 0.1}, 0.0, GUARD_ON)
    assert g["state"] == "RISK_OFF"
    g["high_vol"] = [big]
    r = construct(sc, held, cash, nav, closes, rb, cfg, fs.market, etf, meta, guard=g)
    assert isinstance(r, TargetPortfolio)
    assert r.est_weights[big] <= Decimal(str(g["vol_cap"])) + Decimal("0.002")
    assert not [p for p in r.plan if p.action == "BUY"]


def _scaled(held, closes, nav, f):
    h = {t: int(s * f) // 1000 * 1000 for t, s in held.items()}
    return h, nav - sum(Decimal(s) * closes[t] for t, s in h.items())


def test_relever_after_recovery(fixture_store, rb, cfg):
    fs, sc, closes, etf, meta, held, cash, nav = _setup(fixture_store, rb, cfg)
    h, c2 = _scaled(held, closes, nav, 0.84)                            # cash ~20% after a crisis
    g = CG.step(None, CALM, 0.0, GUARD_ON)
    g["high_vol"] = []
    r = construct(sc, h, c2, nav, closes, rb, cfg, fs.market, etf, meta, guard=g)
    assert isinstance(r, TargetPortfolio), getattr(r, "reason", "")
    bought = sum(Decimal(o.shares) * closes[o.ticker] for o in r.orders if o.side == "BUY")
    assert 0 < bought / nav <= Decimal("0.10") + Decimal("0.002")       # max_releveraging_per_day
    assert set(r.est_holdings) == set(h)


def test_relever_restores_legality_first(fixture_store, rb, cfg):
    fs, sc, closes, etf, meta, held, cash, nav = _setup(fixture_store, rb, cfg)
    h, c2 = _scaled(held, closes, nav, 0.5)                             # cash ~50%: already illegal input
    g = CG.step(None, CALM, 0.0, GUARD_ON)
    g["high_vol"] = []
    r = construct(sc, h, c2, nav, closes, rb, cfg, fs.market, etf, meta, guard=g)
    assert isinstance(r, TargetPortfolio), getattr(r, "reason", "")
    assert r.cash_weight_est < Decimal("0.25")


def test_guard_enabled_run_is_valid(fixture_store, rb, cfg, tmp_path):
    c = copy.deepcopy(cfg)
    c["crash_guard"] = {"enabled": True}
    r = run_day("2026-10-27", fixture_store, Settlement.initial("x", rb.rules.initial_cash), rb, c,
                team_id="TEAM_TEST", out_dir=tmp_path, log_dir=tmp_path, store_is_fixture=True, light=True)
    assert r.validation.ok and r.guard is not None and r.agent_state["guard"]["state"] in CG.STATES
