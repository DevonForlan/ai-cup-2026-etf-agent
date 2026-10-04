import math
from decimal import Decimal

import pytest

from agent.engine.fees import buy_cost, round_money, sell_cost
from agent.engine.orders import derive_order, derive_orders, target_shares


def test_example_042_numbers():
    # D-Plan_TEAM_042 derivation_detail
    assert target_shares(0.23, 102_000_000, 1480) == 15000
    assert target_shares(0.045, 102_000_000, 42.5) == 108000      # exact integer boundary
    assert target_shares(0.03, 102_000_000, 1250) == 2000


def test_decimal_floor_beats_float_floor():
    # 0.29 × 100,000 / 1 / 1000 = 29 exactly, but in float it is 28.999999999999996 -> floor 28
    assert math.floor(0.29 * 100_000 / 1 / 1000) == 28
    assert target_shares(0.29, 100_000, 1) == 29_000
    # same trap at competition scale: 0.07 x 1e9 / 70 / 1000 = 1000 lots exactly
    w, nav, px = 0.57, 1_000_000_000, 570
    exact = target_shares(w, nav, px)
    assert exact == int(Decimal("0.57") * nav / px / 1000) * 1000


def test_floor_boundary_just_below():
    # 1 share short of the next lot -> stays at lower lot
    assert target_shares(Decimal("0.0499999"), 1_000_000, 50) == 0
    assert target_shares(Decimal("0.05"), 1_000_000, 50) == 1000


def test_derive_orders_sides_and_noop():
    holdings = {"2330": 17000, "2317": 5000}
    decs = [{"ticker": "2330", "decision_id": "D1", "target_weight": 0.23},
            {"ticker": "2891", "decision_id": "D2", "target_weight": 0.045},
            {"ticker": "2317", "decision_id": "D3", "target_weight": 0.0}]
    closes = {"2330": 1480, "2891": 42.5, "2317": 200}
    out = {o.ticker: o for o in derive_orders(decs, holdings, 102_000_000, closes)}
    assert (out["2330"].side, out["2330"].shares) == ("SELL", 2000)
    assert (out["2891"].side, out["2891"].shares) == ("BUY", 108000)
    assert (out["2317"].side, out["2317"].shares) == ("SELL", 5000)
    assert derive_order({"ticker": "2330", "decision_id": "D9", "target_weight": 0.2468}, 17000,
                        102_000_000, 1480) is None


def test_negative_weight_rejected():
    with pytest.raises(ValueError):
        target_shares(-0.01, 1e6, 10)


def test_fees_exact(rb):
    assert buy_cost(Decimal("300150"), rb.rules) == Decimal("427.71375")
    fee, tax = sell_cost(Decimal("1010000"), rb.rules)
    assert fee == Decimal("1439.25") and tax == Decimal("3030")


@pytest.mark.parametrize("mode,expected", [("exact", Decimal("427.71375")), ("round_half_up", Decimal("428")),
                                           ("floor", Decimal("427")), ("ceil", Decimal("428"))])
def test_fee_rounding_modes(rb, mode, expected):
    assert buy_cost(Decimal("300150"), rb.rules, mode) == expected


def test_unknown_rounding_mode():
    with pytest.raises(ValueError):
        round_money(Decimal("1.5"), "bankers")
