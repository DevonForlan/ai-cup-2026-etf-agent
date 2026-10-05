from decimal import Decimal

from agent.engine.active_share import ActiveShareMode, active_share_mode, compute_active_share
from agent.engine.compliance import check_active_share
from agent.engine.models import Status

BENCH = {"2330": 0.20, "2454": 0.07, "2317": 0.06, "2308": 0.05, "3711": 0.045, "2382": 0.04,
         "2345": 0.035, "6669": 0.035, "2383": 0.03, "3017": 0.03}


def test_identical_top10_is_zero():
    for m in (ActiveShareMode.NAV_WEIGHT, ActiveShareMode.TOP10_NORMALIZED, ActiveShareMode.FULL_PORTFOLIO):
        assert active_share_mode(BENCH, BENCH, m) == 0


def test_disjoint_normalized_is_one():
    port = {t: 0.05 for t in ["2603", "2609", "2615", "1101", "2002", "1301", "1303", "1326", "2912", "1216"]}
    assert abs(active_share_mode(port, BENCH, ActiveShareMode.TOP10_NORMALIZED) - Decimal(1)) < Decimal("1e-20")
    # NAV-weight mode: 1/2*(0.5 + 0.595) on disjoint sets
    assert active_share_mode(port, BENCH, ActiveShareMode.NAV_WEIGHT) == Decimal("0.5475")


def test_full_portfolio_includes_tail():
    port = dict(BENCH)
    port["2603"] = 0.01                     # 11th name only counts in FULL_PORTFOLIO
    assert active_share_mode(port, BENCH, ActiveShareMode.NAV_WEIGHT) == 0
    assert active_share_mode(port, BENCH, ActiveShareMode.FULL_PORTFOLIO) == Decimal("0.005")


def test_unknown_mode_takes_minimum_over_modes_and_etfs(rb):
    port = {"2330": 0.235, "2454": 0.09, "2317": 0.09, "2308": 0.09, "2603": 0.09, "2609": 0.09,
            "1101": 0.09, "2002": 0.05, "1301": 0.05, "1303": 0.05, "1326": 0.03}
    etfs = {"00980A": BENCH, "00989A": {"AAPL": 0.1, "MSFT": 0.1}}
    res = compute_active_share(port, etfs, rb.active_etfs, ActiveShareMode.UNKNOWN)
    assert res.benchmark_ticker == "00980A"
    assert res.minimum_active_share == min(res.min_by_mode.values())
    assert len(res.missing_benchmarks) == len(rb.active_etfs) - 2
    assert set(res.per_etf["00980A"]) == {"NAV_WEIGHT", "TOP10_NORMALIZED", "FULL_PORTFOLIO"}


def test_threshold_checks(rb):
    # below 20% -> FAIL; near 20% but above -> WARNING vs 30% strategy target
    near = {"2330": 0.20, "2454": 0.07, "2317": 0.06, "2308": 0.05, "3711": 0.045, "2382": 0.04,
            "2603": 0.10, "2609": 0.10, "1101": 0.10, "2002": 0.10}
    res = compute_active_share(near, {"00980A": BENCH}, ["00980A"], ActiveShareMode.NAV_WEIGHT)
    v = res.minimum_active_share
    assert Decimal("0.20") <= v < Decimal("0.30")
    rep = check_active_share(res, rb, Decimal("0.30"))
    assert rep.statuses("R_ACTIVE_SHARE") == {Status.WARNING}
    clone = {k: v * 1.0 for k, v in BENCH.items()}
    clone["2330"] = 0.25
    res2 = compute_active_share(clone, {"00980A": BENCH}, ["00980A"], ActiveShareMode.NAV_WEIGHT)
    assert res2.minimum_active_share < Decimal("0.20")
    assert check_active_share(res2, rb).statuses("R_ACTIVE_SHARE") == {Status.FAIL}


def test_no_benchmark_data_is_unknown(rb):
    res = compute_active_share({"2330": 0.2}, {}, rb.active_etfs)
    assert res.minimum_active_share is None
    assert check_active_share(res, rb).statuses("R_ACTIVE_SHARE") == {Status.UNKNOWN}
