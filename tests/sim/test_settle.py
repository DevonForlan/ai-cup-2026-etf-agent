"""Golden simulator tests: hand-calculated, reconciled to the cent."""
from decimal import Decimal

from agent.engine.rules import RuleBook
from agent.sim.metrics import max_drawdown, mdd_both
from agent.sim.models import DayMarket, Settlement
from agent.sim.settle import settle

Dd = Decimal


def mk(date, close, vwap_amt_vol, div=None):
    return DayMarket(date, {t: Dd(str(c)) for t, c in close.items()},
                     amount={t: Dd(a) for t, (a, v) in vwap_amt_vol.items()},
                     volume={t: Dd(v) for t, (a, v) in vwap_amt_vol.items()},
                     cash_dividend={t: Dd(str(x)) for t, x in (div or {}).items()})


def golden_days(rb):
    s0 = Settlement.initial("2026-10-23", 10_000_000)
    d1 = mk("2026-10-26", {"2317": 101, "2454": 990},
            {"2317": (1_000_500, 10_000), "2454": (5_005_000, 5_000)})            # VWAP 100.05 / 1001
    s1 = settle(s0, [{"ticker": "2317", "side": "BUY", "shares": 3000},
                     {"ticker": "2454", "side": "BUY", "shares": 2000}], d1, rb)
    d2 = mk("2026-10-27", {"2317": 103, "2454": 1020},
            {"2317": (2_040_000, 20_000), "2454": (10_100_000, 10_000)})          # VWAP 102 / 1010
    s2 = settle(s1, [{"ticker": "2317", "side": "BUY", "shares": 2000},
                     {"ticker": "2454", "side": "SELL", "shares": 1000}], d2, rb)
    d3 = mk("2026-10-28", {"2454": 1000, "2317": 98},
            {"2317": (990_000, 10_000), "2454": (1_000_000, 1_000)}, div={"2454": 5})  # VWAP 99
    s3 = settle(s2, [{"ticker": "2317", "side": "SELL", "shares": 5000}], d3, rb)
    return s1, s2, s3


def test_golden_three_days(golden_rb):
    s1, s2, s3 = golden_days(golden_rb)
    # Day 1: buy 3000@100.05 (fee 427.71375) + 2000@1001 (fee 2852.85)
    assert s1.cash == Dd("7694569.43625")
    assert s1.nav == Dd("9977569.43625")
    assert s1.fees == Dd("3280.56375") and s1.tax == 0
    assert s1.holdings == {"2317": 3000, "2454": 2000}
    # Day 2: add 2000@102 (fee 290.7); trim 1000@1010 (fee 1439.25, tax 3030)
    assert s2.cash == Dd("8495809.48625")
    assert s2.nav == Dd("10030809.48625")
    assert s2.tax == Dd("3030")
    assert s2.holdings == {"2317": 5000, "2454": 1000}
    # Day 3: sell 5000@99 (fee 705.375, tax 1485); 2454 ex-dividend 5/sh accrued, not in cash
    assert s3.cash == Dd("8988619.11125")
    assert s3.nav == Dd("9988619.11125")
    assert s3.accrued_dividends == Dd("5000")
    assert s3.nav_with_accrued == Dd("9993619.11125")
    assert s3.holdings == {"2454": 1000}
    assert s3.cum_fees == Dd("5715.88875") and s3.cum_tax == Dd("4515")
    # MDD: peak 10,030,809.48625 -> 9,988,619.11125
    exp = (Dd("10030809.48625") - Dd("9988619.11125")) / Dd("10030809.48625")
    assert Dd(s3.mdd["include_initial_nav_true"]) == exp
    assert Dd(s3.mdd["include_initial_nav_false"]) == exp
    assert s3.warning_count == 0 and not s3.dq


def test_golden_turnover(golden_rb):
    s1, s2, s3 = golden_days(golden_rb)
    assert s1.turnover == (Dd("300150") + Dd("2002000")) / Dd("10000000")
    assert s2.turnover == (Dd("204000") + Dd("1010000")) / s1.nav


def test_round_half_up_mode(golden_rb):
    rb2 = RuleBook(golden_rb.rules, golden_rb.universe, golden_rb.active_etfs,
                   golden_rb.assumptions.with_overrides(fee_rounding_mode="round_half_up"))
    s1, s2, s3 = golden_days(rb2)
    assert s1.fees == Dd("428") + Dd("2853")
    assert s3.cum_fees == Dd(428 + 2853 + 291 + 1439 + 705)


def test_mdd_definition_from_rules_example():
    # 辦法 §五 example: team A MDD = (10.8-10.2)/10.8
    a = [Dd("10.1"), Dd("10.8"), Dd("10.2"), Dd("10.9"), Dd("10.5")]
    assert max_drawdown(a) == (Dd("10.8") - Dd("10.2")) / Dd("10.8")
    b = [Dd("10.2"), Dd("10.7"), Dd("10.3"), Dd("10.8"), Dd("10.5")]
    assert max_drawdown(b) == (Dd("10.7") - Dd("10.3")) / Dd("10.7")
    both = mdd_both([Dd(9), Dd(10)], Dd(10))
    assert both["include_initial_nav_true"] == Dd("0.1") and both["include_initial_nav_false"] == 0


def test_violation_voids_trades_and_warns(rb):
    # official rules: 2 holdings violates 20-30 -> warning, trades void, NAV from previous portfolio
    s0 = Settlement.initial("2026-10-23", 10_000_000)
    d1 = mk("2026-10-26", {"2317": 101}, {"2317": (1_000_500, 10_000)})
    s1 = settle(s0, [{"ticker": "2317", "side": "BUY", "shares": 3000}], d1, rb)
    assert s1.trades_void and s1.warning_count == 1
    assert s1.cash == Dd(10_000_000) and s1.holdings == {} and s1.nav == Dd(10_000_000)
    assert any(w["rule"] == "R_COUNT" for w in s1.warnings)


def test_no_submission_and_dq_after_three(rb):
    s = Settlement.initial("2026-10-23", 1_000_000)
    for i, d in enumerate(["2026-10-26", "2026-10-27", "2026-10-28"]):
        s = settle(s, None, mk(d, {}, {}), rb)
        assert s.warning_count == i + 1
    assert s.dq and "WARNINGS_3" in s.dq_reasons


def test_oversell_rejected(relaxed_rb):
    s0 = Settlement("2026-10-23", {"2317": 1000}, Dd(1_000_000), Dd(1_100_000), closes={"2317": Dd(100)})
    s1 = settle(s0, [{"ticker": "2317", "side": "SELL", "shares": 2000}],
                mk("2026-10-26", {"2317": 100}, {"2317": (100_000, 1000)}), relaxed_rb)
    assert s1.trades_void and any(w["rule"] == "REJECTED" for w in s1.warnings)


def test_no_trade_price_skip_vs_reject(relaxed_rb):
    s0 = Settlement.initial("2026-10-23", 1_000_000)
    orders = [{"ticker": "2317", "side": "BUY", "shares": 1000}, {"ticker": "2454", "side": "BUY", "shares": 1000}]
    m = mk("2026-10-26", {"2317": 90, "2454": 50}, {"2317": (100_000, 1000)})     # 2454 has no trades
    s1 = settle(s0, orders, m, relaxed_rb)
    assert s1.holdings == {"2317": 1000}
    assert any(e.get("status") == "SKIPPED_NO_TRADE" for e in s1.executions)
    rb2 = RuleBook(relaxed_rb.rules, relaxed_rb.universe, relaxed_rb.active_etfs,
                   relaxed_rb.assumptions.with_overrides(no_trade_execution_mode="reject"))
    s2 = settle(s0, orders, m, rb2)
    assert s2.trades_void and s2.holdings == {}


def test_price_drift_grace(relaxed_rb):
    # 2454 drifts above 10% without buying: warning only on the 6th consecutive day
    h = {"2454": 1000}
    s = Settlement("2026-10-23", h, Dd(1_000_000), Dd(1_100_000), closes={"2454": Dd(100)})
    for i in range(6):
        s = settle(s, [], mk(f"2026-11-0{i + 2}", {"2454": 200}, {}), relaxed_rb)   # 200k / 1.2M = 16.7%
        if i < 5:
            assert s.warning_count == 0, i
    assert s.warning_count == 1 and any(w["rule"] == "R_WEIGHT_DRIFT" for w in s.warnings)


def test_buying_above_cap_warns_immediately(relaxed_rb):
    s0 = Settlement.initial("2026-10-23", 1_000_000)
    s1 = settle(s0, [{"ticker": "2454", "side": "BUY", "shares": 2000}],
                mk("2026-10-26", {"2454": 100}, {"2454": (200_000, 2000)}), relaxed_rb)   # 20% > 10%
    assert s1.trades_void and any(w["rule"] == "R_WEIGHT_ADD" for w in s1.warnings)


def test_active_share_two_days_dq(relaxed_rb):
    s = Settlement.initial("2026-10-23", 1_000_000)
    # official threshold 15% (辦法_1005更新 §六(十三)): < 15% is a breach, exactly 15% is not
    s = settle(s, [], mk("2026-10-26", {}, {}), relaxed_rb, active_share_min=Dd("0.1499"))
    assert not s.dq and s.active_share_breach_days == 1
    s = settle(s, [], mk("2026-10-27", {}, {}), relaxed_rb, active_share_min=Dd("0.15"))
    assert s.active_share_breach_days == 0
    s = settle(s, [], mk("2026-10-28", {}, {}), relaxed_rb, active_share_min=Dd("0.10"))
    s = settle(s, [], mk("2026-10-29", {}, {}), relaxed_rb, active_share_min=Dd("0.1499"))
    assert s.dq and "ACTIVE_SHARE_2D" in s.dq_reasons


def test_settlement_roundtrip(tmp_path, golden_rb):
    _, _, s3 = golden_days(golden_rb)
    p = tmp_path / "s.json"
    s3.save(p)
    s = Settlement.load(p)
    assert s.nav == s3.nav and s.holdings == s3.holdings and s.accrued_dividends == s3.accrued_dividends
