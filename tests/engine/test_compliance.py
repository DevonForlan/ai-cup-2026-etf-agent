import dataclasses
from decimal import Decimal

import pytest

from agent.engine.compliance import check_orders, check_portfolio, check_target_weights
from agent.engine.models import Status
from agent.engine.rules import RuleBook

UNI = ["2330", "2454", "2317", "2308", "3711", "2881", "2383", "2303", "2882", "3037", "2891", "1303",
       "2345", "2382", "2408", "7769", "2412", "2327", "6669", "3017", "2885", "2887", "2360", "2886",
       "2059", "6505", "2884", "2880", "2357", "2890", "2883"]


def port(n, w=None):
    """n names equal weight w (default ~ (1-0.1)/n) as target weights."""
    w = w if w is not None else 0.9 / n
    return {t: w for t in UNI[:n]}


def statuses(rep, rid):
    return rep.statuses(rid)


def test_universe_loaded(rb):
    assert len(rb.universe) == 150 and len(rb.active_etfs) == 30
    assert rb.universe["5274"]["market"] == "TPEx" and rb.authority_of("5274") == "tpex"


def test_official_rules_values(rb):
    r = rb.rules
    assert (r.tsmc_max_weight, r.other_max_weight, r.cash_max_weight) == (Decimal("0.25"), Decimal("0.10"), Decimal("0.25"))
    assert (r.holdings_min, r.holdings_max, r.lot_size) == (20, 30, 1000)
    assert r.active_share_min == Decimal("0.20")


def test_19_and_31_stocks_fail(rb):
    assert Status.FAIL in check_target_weights(port(19, 0.045), rb).statuses("R_COUNT")
    assert Status.FAIL in check_target_weights(port(31, 0.03), rb).statuses("R_COUNT")
    assert check_target_weights(port(20, 0.045), rb).statuses("R_COUNT") == {Status.PASS}
    assert check_target_weights(port(30, 0.03), rb).statuses("R_COUNT") == {Status.PASS}


def test_count_exclusive_assumption(rb):
    rb2 = RuleBook(rb.rules, rb.universe, rb.active_etfs, rb.assumptions.with_overrides(holdings_count_inclusive=False))
    assert Status.FAIL in check_target_weights(port(20, 0.045), rb2).statuses("R_COUNT")


def test_tsmc_and_other_caps(rb):
    p = port(22, 0.035)
    p["2330"] = 0.26
    assert Status.FAIL in check_target_weights(p, rb).statuses("R_TSMC_CAP")
    p["2330"] = 0.25
    assert Status.FAIL not in check_target_weights(p, rb).statuses("R_TSMC_CAP")
    p["2454"] = 0.1001
    assert Status.FAIL in check_target_weights(p, rb).statuses("R_OTHER_CAP")


def test_cash_negative_and_over_25(rb):
    p = port(22, 0.046)        # 101.2% invested -> negative cash
    assert Status.FAIL in check_target_weights(p, rb).statuses("R_CASH_NEG")
    p = port(22, 0.034)        # 74.8% invested -> 25.2% cash
    assert Status.FAIL in check_target_weights(p, rb).statuses("R_CASH_MAX")


def test_cash_exactly_25_follows_assumption(rb):
    p = {t: 0.0375 for t in UNI[:20]}   # 75% invested
    assert Status.FAIL in check_target_weights(p, rb).statuses("R_CASH_MAX")      # assumption: not allowed
    rb2 = RuleBook(rb.rules, rb.universe, rb.active_etfs, rb.assumptions.with_overrides(cash_equal_25_allowed=True))
    assert check_target_weights(p, rb2).statuses("R_CASH_MAX") == {Status.PASS}


def test_non_universe(rb):
    p = port(21, 0.04)
    p["0050"] = 0.02
    assert Status.FAIL in check_target_weights(p, rb).statuses("R_UNIVERSE")


def test_holdings_portfolio_check(rb):
    h = {t: 10000 for t in UNI[:22]}
    px = {t: 400 for t in UNI}
    rep = check_portfolio(h, px, 10_000_000, rb)   # 22 * 4M = 88M, cash 10M
    assert rep.ok
    h["2330"] = -1000
    assert Status.FAIL in check_portfolio(h, px, 10_000_000, rb).statuses("R_NO_SHORT")


def test_odd_lot_holdings_warn(rb):
    h = {t: 10000 for t in UNI[:22]}
    h["2317"] = 10500                     # e.g. from stock dividend
    rep = check_portfolio(h, {t: 400 for t in UNI}, 10_000_000, rb)
    assert rep.statuses("R_LOT") == {Status.WARNING}


def test_order_odd_lot_and_oversell(rb):
    rep = check_orders([{"ticker": "2330", "side": "BUY", "shares": 1500}], {}, rb)
    assert Status.FAIL in rep.statuses("R_LOT")
    rep = check_orders([{"ticker": "2330", "side": "SELL", "shares": 3000}], {"2330": 2000}, rb)
    assert Status.FAIL in rep.statuses("R_OVERSELL")
    rep = check_orders([{"ticker": "2330", "side": "SELL", "shares": 2000}], {"2330": 2000}, rb)
    assert rep.ok
