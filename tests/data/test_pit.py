"""PIT leakage guards + canary: future data injected into the store must not change features."""
import pandas as pd
import pytest

from agent.data.loaders import HistoryStore
from agent.data.pit import LeakageError, PITView
from agent.features.feature_engine import build_features


def _rows(dates, tickers, px=100.0):
    out = []
    for i, d in enumerate(dates):
        for t in tickers:
            out.append({"date": d, "ticker": t, "market": "TWSE", "open": px + i, "high": px + i, "low": px + i,
                        "close": px + i, "volume": 1000, "amount": 1000 * (px + i), "vwap": px + i,
                        "available_at": f"{d}T15:00:00+08:00"})
    return out


def test_pitview_filters_future(tmp_path):
    st = HistoryStore(tmp_path)
    st.upsert("daily_prices", _rows(["2026-10-01", "2026-10-02", "2026-10-05"], ["2330"]))
    v = PITView(st, "2026-10-05T08:00:00+08:00")
    df = v.prices()
    assert set(df["date"]) == {"2026-10-01", "2026-10-02"}
    v2 = PITView(st, "2026-10-05T15:00:00+08:00")       # same-day close visible only after 15:00
    assert "2026-10-05" in set(v2.prices()["date"])
    assert v.reads and v.reads[0]["rows"] == 2


def test_pitview_requires_taipei_tz(tmp_path):
    with pytest.raises(ValueError):
        PITView(HistoryStore(tmp_path), "2026-10-05T08:00:00Z")


def test_available_at_must_be_taipei(tmp_path):
    st = HistoryStore(tmp_path)
    r = _rows(["2026-10-01"], ["2330"])
    r[0]["available_at"] = "2026-10-01T07:00:00+00:00"
    st.upsert("daily_prices", r)
    with pytest.raises(LeakageError):
        PITView(st, "2026-10-05T08:00:00+08:00").prices()


def test_early_available_but_future_date_blocked(tmp_path):
    # a row dated in the future but (wrongly) stamped as available early must still be blocked
    st = HistoryStore(tmp_path)
    r = _rows(["2026-10-09"], ["2330"])
    r[0]["available_at"] = "2026-10-01T15:00:00+08:00"
    st.upsert("daily_prices", r)
    assert len(PITView(st, "2026-10-05T08:00:00+08:00").prices()) == 0


def test_leakage_canary_features_unchanged(fixture_store, rb, tmp_path):
    """Copy the fixture, inject absurd future rows (prices x100, huge flows, revenue), and verify
    features for trade date T are identical."""
    T = "2026-10-27"
    as_of = f"{T}T07:00:00+08:00"
    uni = sorted(rb.universe)
    base = build_features(PITView(fixture_store, as_of), uni, T).features

    st = HistoryStore(tmp_path)
    for tbl in ("daily_prices", "institutional", "monthly_revenue"):
        st.upsert(tbl, fixture_store.load(tbl))
    fut = []
    for d in ["2026-10-27", "2026-10-28"]:
        for t in uni:
            fut.append({"date": d, "ticker": t, "market": rb.universe[t]["market"], "open": 1e6, "high": 1e6,
                        "low": 1e6, "close": 1e6, "volume": 10**9, "amount": 10**15, "vwap": 1e6,
                        "available_at": f"{d}T15:00:00+08:00"})
    st.upsert("daily_prices", fut)
    st.upsert("institutional", [{"date": "2026-10-27", "ticker": t, "foreign_net": 10**9, "trust_net": 0,
                                 "dealer_net": 0, "total_net": 10**9, "available_at": "2026-10-27T17:00:00+08:00"}
                                for t in uni])
    st.upsert("monthly_revenue", [{"ticker": t, "year": 2026, "month": 10, "revenue": 1e15,
                                   "available_at": "2026-11-10T23:59:00+08:00"} for t in uni])
    poisoned = build_features(PITView(st, as_of), uni, T).features
    pd.testing.assert_frame_equal(base, poisoned)
