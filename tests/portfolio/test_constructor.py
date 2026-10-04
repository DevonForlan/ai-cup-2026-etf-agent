from decimal import Decimal

import pandas as pd

from agent.config import D
from agent.data.pit import PITView
from agent.engine.compliance import check_portfolio
from agent.features.feature_engine import build_features
from agent.pipeline import etf_holdings_from_view
from agent.portfolio.baseline import water_fill
from agent.portfolio.constructor import FallbackToPreviousPortfolio, TargetPortfolio, construct
from agent.portfolio.ranking import score

T = "2026-10-27"


def setup(fixture_store, rb, cfg):
    v = PITView(fixture_store, f"{T}T07:00:00+08:00")
    fs = build_features(v, sorted(rb.universe), T)
    sc = score(fs.features, cfg["score_weights"])
    closes = {t: D(round(float(x), 4)) for t, x in fs.features["close_prev"].dropna().items()}
    etf, meta = etf_holdings_from_view(v)
    return fs, sc, closes, etf, meta


def test_initial_portfolio_is_legal(fixture_store, rb, cfg):
    fs, sc, closes, etf, meta = setup(fixture_store, rb, cfg)
    tp = construct(sc, {}, rb.rules.initial_cash, rb.rules.initial_cash, closes, rb, cfg, fs.market, etf, meta)
    assert isinstance(tp, TargetPortfolio), getattr(tp, "reason", "")
    n = len(tp.est_holdings)
    assert cfg["strategy_buffers"]["target_holdings_min"] <= n <= cfg["strategy_buffers"]["target_holdings_max"]
    rep = check_portfolio(tp.est_holdings, closes, tp.est_cash, rb)
    assert rep.ok, [c.message for c in rep.failures]
    for t, w in tp.weights.items():                 # strategy buffers respected
        cap = cfg["strategy_buffers"]["tsmc_target_cap"] if t == "2330" else cfg["strategy_buffers"]["other_target_cap"]
        assert w <= Decimal(str(cap))
    assert all(o.shares % 1000 == 0 and o.side == "BUY" for o in tp.orders)
    assert tp.active_share is not None and tp.active_share.minimum_active_share >= Decimal("0.20")


def test_turnover_control_keeps_names(fixture_store, rb, cfg):
    fs, sc, closes, etf, meta = setup(fixture_store, rb, cfg)
    tp = construct(sc, {}, rb.rules.initial_cash, rb.rules.initial_cash, closes, rb, cfg, fs.market, etf, meta)
    held = tp.est_holdings
    nav = sum(Decimal(s) * closes[t] for t, s in held.items()) + tp.est_cash
    tp2 = construct(sc, held, tp.est_cash, nav, closes, rb, cfg, fs.market, etf, meta)
    assert isinstance(tp2, TargetPortfolio)
    # same scores, same prices -> almost everything is a no-trade
    trades = [p for p in tp2.plan if p.action != "NO_TRADE"]
    assert len(trades) <= 3, [(p.ticker, p.action) for p in trades]
    assert not [p for p in tp2.plan if p.action == "SELL_ALL"]


def test_fallback_when_not_enough_names(fixture_store, rb, cfg):
    fs, sc, closes, etf, meta = setup(fixture_store, rb, cfg)
    sc2 = sc.copy()
    keep = sc2.sort_values("rank").index[:10]
    sc2.loc[~sc2.index.isin(keep), "eligible"] = False
    r = construct(sc2, {}, rb.rules.initial_cash, rb.rules.initial_cash, closes, rb, cfg, fs.market, etf, meta)
    assert isinstance(r, FallbackToPreviousPortfolio)


def test_fallback_on_missing_price(fixture_store, rb, cfg):
    fs, sc, closes, etf, meta = setup(fixture_store, rb, cfg)
    c2 = dict(closes)
    c2.pop("2330")
    r = construct(sc, {"2330": 1000}, rb.rules.initial_cash, rb.rules.initial_cash, c2, rb, cfg, fs.market)
    assert isinstance(r, FallbackToPreviousPortfolio)


def test_lot_infeasible_names_are_replaced(fixture_store, rb, cfg):
    fs, sc, closes, etf, meta = setup(fixture_store, rb, cfg)
    top = sc.sort_values("rank").index[0]
    c2 = dict(closes)
    c2[top] = D(10**7)                    # one lot = 1e10 > any target weight -> 0 lots
    r = construct(sc, {}, rb.rules.initial_cash, rb.rules.initial_cash, c2, rb, cfg, fs.market, etf, meta)
    assert isinstance(r, TargetPortfolio) and top not in r.weights
    assert any("整張不可行" in n for n in r.notes)


def test_water_fill_caps():
    w = water_fill({"2330": 10, "A": 1, "B": 1}, Decimal("0.5"),
                   {"2330": Decimal("0.235"), "A": Decimal("0.09"), "B": Decimal("0.09")})
    assert w["2330"] == Decimal("0.235") and w["A"] == Decimal("0.09")
    assert sum(w.values()) <= Decimal("0.5")
