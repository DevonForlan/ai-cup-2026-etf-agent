"""Issue #11: 2026-10-23 typhoon closure (Owner decision 2026-10-25). Day 1 = 2026-10-27, T-1 = 2026-10-22.
No 2026-10-23 market data is fabricated; the freshness gate stays fail-closed."""
from datetime import date

import pytest

from agent.ops import scheduled_run as S
from agent.ops.common import load_ops_config
from agent.ops.datapack import calendar_holidays, previous_trading_day
from agent.ops.refresh_daily import expected_prev_trading_day

KNOWN_2026 = ["2026-01-01", "2026-02-12", "2026-02-13", "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19",
              "2026-02-20", "2026-02-27", "2026-04-03", "2026-04-06", "2026-05-01", "2026-06-19", "2026-09-25",
              "2026-09-28", "2026-10-09", "2026-10-26", "2026-12-25"]


def test_20261023_is_non_trading_in_both_calendars_and_they_agree():
    ops_hol, cal_hol = S.holidays(load_ops_config()), calendar_holidays()
    assert "2026-10-23" in ops_hol and "2026-10-23" in cal_hol
    assert ops_hol == cal_hol                          # competition preflight BLOCKS when they differ
    assert not S.is_trading_day(date(2026, 10, 23), ops_hol)


def test_previous_trading_day_of_day1_is_20261022():
    hol = calendar_holidays()
    assert previous_trading_day("2026-10-27") == "2026-10-22"
    assert previous_trading_day("2026-10-27", hol) == "2026-10-22"
    assert expected_prev_trading_day("2026-10-27", S.holidays(load_ops_config())) == "2026-10-22"


def test_scheduler_targets_day1_and_never_expects_1023_data():
    hol = S.holidays(load_ops_config())
    assert S.next_trading_day(date(2026, 10, 22), hol) == date(2026, 10, 27)
    assert S.is_trading_day(date(2026, 10, 27), hol)
    for d in (date(2026, 10, 23), date(2026, 10, 24), date(2026, 10, 25), date(2026, 10, 26)):
        assert not S.is_trading_day(d, hol)


def test_freshness_gate_accepts_1022_data_for_day1_and_still_blocks_stale():
    from agent.ops.refresh_daily import trading_lag
    hol = S.holidays(load_ops_config())
    exp = expected_prev_trading_day("2026-10-27", hol)
    assert trading_lag("2026-10-22", exp, hol) == 0                     # latest = T-1 -> fresh
    assert trading_lag("2026-10-21", exp, hol) == 1                     # one trading day behind -> still stale
    without = hol - {"2026-10-23"}                                      # the old calendar would have expected 10/23
    assert trading_lag("2026-10-22", expected_prev_trading_day("2026-10-27", without), without) == 1


@pytest.mark.parametrize("d", KNOWN_2026)
def test_no_regression_on_other_known_closures(d):
    assert d in calendar_holidays() and d in S.holidays(load_ops_config())
    assert not S.is_trading_day(date.fromisoformat(d), S.holidays(load_ops_config()))


def test_regular_weekdays_around_the_closure_still_trade():
    hol = S.holidays(load_ops_config())
    for d in ("2026-10-21", "2026-10-22", "2026-10-27", "2026-10-28"):
        assert S.is_trading_day(date.fromisoformat(d), hol)
