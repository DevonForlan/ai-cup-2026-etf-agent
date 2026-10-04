"""market_overnight: parsers (saved raw samples), date mapping (weekend, DST), PIT availability."""
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from agent.data import overnight as O
from agent.data.fetchers import taifex as TX
from agent.data.loaders import HistoryStore
from agent.data.pit import PITView

S = Path(__file__).resolve().parents[1] / "fixtures" / "overnight_samples"


# ------------------------------------------------------------------ TAIFEX
def test_taifex_parse_and_night_rows():
    raw = TX.parse_fut_csv((S / "taifex_TX_20260914_20260918.csv").read_bytes())
    assert {r["session"] for r in raw} == {TX.SESSION_REGULAR, TX.SESSION_NIGHT}
    rows = {r["date"]: r for r in TX.build_night_rows(raw)}
    assert sorted(rows) == ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"]
    # 09-16 is the Sep expiry: the 盤後 row dated 09-16 (session 09-15 15:00 -> 09-16 05:00) still trades 202609
    assert rows["2026-09-16"]["source"].endswith(":202609")
    assert rows["2026-09-17"]["source"].endswith(":202610")       # rolled to next month
    r = rows["2026-09-17"]
    assert (r["close"], r["high"], r["low"], r["volume"]) == (46382, 46626, 46056, 32283)
    # ret vs previous regular-session SETTLEMENT of the same contract (202610 on 09-16: 46060)
    assert r["ret"] == pytest.approx(46382 / 46060 - 1)
    assert rows["2026-09-15"]["ret"] == pytest.approx(45556 / 45777 - 1)   # 202609 settle 09-14 = 45777
    # first date: no previous regular row in file -> fallback close - 漲跌價 (TAIFEX reference)
    assert rows["2026-09-14"]["ret"] == pytest.approx(46588 / (46588 - 401) - 1)
    assert r["available_at"] == "2026-09-17T05:05:00+08:00" and r["symbol"] == "TXF_NIGHT"


def test_taifex_html_error_detected():
    with pytest.raises(ValueError):
        TX.parse_fut_csv(b"<!DOCTYPE HTML PUBLIC><html></html>")


def test_taifex_month_chunks():
    ch = list(TX._month_chunks(date(2024, 2, 20), date(2024, 4, 3)))
    assert ch == [(date(2024, 2, 20), date(2024, 2, 29)), (date(2024, 3, 1), date(2024, 3, 31)),
                  (date(2024, 4, 1), date(2024, 4, 3))]


# ------------------------------------------------------------------ date mapping
def test_us_mapping_weekdays_and_friday():
    assert O.map_us_day(date(2026, 9, 29)) == ("2026-09-30", "2026-09-30T05:30:00+08:00")   # Tue -> Wed
    assert O.map_us_day(date(2026, 10, 2)) == ("2026-10-05", "2026-10-05T05:30:00+08:00")   # Fri -> Mon


def test_us_close_dst_boundary():
    # 2025: DST ended Sun 2025-11-02. 2026: ends Sun 2026-11-01.
    assert O.us_close_taipei(date(2025, 10, 31)).hour == 4      # EDT close = 04:00 Taipei
    assert O.us_close_taipei(date(2025, 11, 3)).hour == 5       # EST close = 05:00 Taipei
    assert O.us_close_taipei(date(2026, 10, 30)).hour == 4
    assert O.us_close_taipei(date(2026, 11, 2)).hour == 5
    # Fri before DST end -> Mon; Mon after DST end -> Tue; available 05:30 is after the 05:00 EST close
    assert O.map_us_day(date(2026, 10, 30))[0] == "2026-11-02"
    T, av = O.map_us_day(date(2026, 11, 2))
    assert T == "2026-11-03" and datetime.fromisoformat(av) > O.us_close_taipei(date(2026, 11, 2))
    # spring forward 2026-03-08
    assert O.us_close_taipei(date(2026, 3, 6)).hour == 5 and O.us_close_taipei(date(2026, 3, 9)).hour == 4


def test_fx_mapping_strictly_before_open():
    T, av = O.map_tw_fx_day(date(2026, 10, 2))
    assert T == "2026-10-05" and av == "2026-10-02T17:00:00+08:00"
    assert av < f"{T}T08:00:00+08:00"


# ------------------------------------------------------------------ parsers
def test_fred_parse_and_rows():
    obs = O.parse_fred_csv((S / "fred_SP500_20251027_20251110.csv").read_bytes())
    assert obs[0] == {"d": date(2025, 10, 27), "close": 6875.16}
    rows = {r["date"]: r for r in O.to_rows("SPX", "fred:SP500", obs, O.map_us_day, "2025-10-28", "2025-11-10")}
    # US Fri 10-31 -> TW Mon 11-03 ; US Mon 11-03 (first EST day) -> TW Tue 11-04
    assert rows["2025-11-03"]["close"] == 6840.20
    assert rows["2025-11-04"]["close"] == 6851.97
    assert rows["2025-11-04"]["ret"] == pytest.approx(6851.97 / 6840.20 - 1)
    assert rows["2025-10-28"]["ret"] is None                       # first obs in sample has no previous close
    assert "2025-11-01" not in rows and "2025-11-10" in rows        # no weekend T; 11-07 Fri -> 11-10 Mon


def test_yahoo_parse_tsm_sox():
    tsm = O.parse_yahoo_chart((S / "yahoo_TSM_20251027_20251110.json").read_bytes())
    ds = [o["d"] for o in tsm]
    assert date(2025, 10, 31) in ds and date(2025, 11, 3) in ds and date(2025, 11, 1) not in ds
    assert all(o["high"] >= o["close"] >= o["low"] for o in tsm)
    sox = O.parse_yahoo_chart((S / "yahoo_SOX_20251027_20251110.json").read_bytes())
    assert sox and all(o["volume"] is None for o in sox)            # index volume 0 -> missing
    # unfinished live bar is dropped
    cut = datetime(2025, 11, 7, 18, 0, tzinfo=timezone.utc)          # 13:00 ET on Fri 11-07
    assert date(2025, 11, 7) not in [o["d"] for o in O.parse_yahoo_chart(
        (S / "yahoo_TSM_20251027_20251110.json").read_bytes(), now=cut)]


def test_cbc_parse():
    obs = O.parse_cbc_html((S / "cbc_lp-645-1-1-60.html").read_bytes())
    assert len(obs) == 60
    d = {o["d"]: o["close"] for o in obs}
    assert d[date(2026, 10, 2)] == 31.830 and d[date(2026, 10, 1)] == 31.842


# ------------------------------------------------------------------ provider plumbing + PIT
class _Fake(O.OvernightProvider):
    name = "fake"
    symbols = {"SOX": "x"}

    def __init__(self, fail=False):
        self.fail = fail

    def get(self, symbols, start, end):
        if self.fail:
            raise RuntimeError("down")
        obs = [{"d": date(2026, 10, 1), "close": 100.0}, {"d": date(2026, 10, 2), "close": 101.0}]
        return O.to_rows("SOX", "fake", obs, O.map_us_day, start, end)


def test_composite_fallback_and_missing():
    cp = O.CompositeProvider({"SOX": [_Fake(fail=True), _Fake()], "TSM": []}, log=None)
    rows = cp.get(["SOX", "TSM"], "2026-10-01", "2026-10-09")
    assert [r["date"] for r in rows] == ["2026-10-02", "2026-10-05"]
    assert rows[1]["ret"] == pytest.approx(0.01)
    assert cp.status["SOX"] == "ok via fake" and "no provider" in cp.status["TSM"]


def test_pit_availability(tmp_path):
    st = HistoryStore(tmp_path)
    raw = TX.parse_fut_csv((S / "taifex_TX_20260914_20260918.csv").read_bytes())
    st.upsert("market_overnight", TX.build_night_rows(raw))
    obs = O.parse_fred_csv((S / "fred_SP500_20251027_20251110.csv").read_bytes())
    st.upsert("market_overnight", O.to_rows("SPX", "fred:SP500", obs, O.map_us_day, "2025-10-28", "2025-11-10"))
    st.upsert("market_overnight", O.to_rows("USDTWD", "cbc", [{"d": date(2026, 9, 16), "close": 31.8},
                                                              {"d": date(2026, 9, 17), "close": 31.9}],
                                            O.map_tw_fx_day, "2026-09-01", "2026-09-30"))

    def visible(as_of):
        return PITView(st, as_of).table("market_overnight")

    v = visible("2026-09-17T05:00:00+08:00")                 # night session not finished yet
    assert v[v.symbol == "TXF_NIGHT"]["date"].max() == "2026-09-16"
    v = visible("2026-09-17T08:00:00+08:00")
    assert v[v.symbol == "TXF_NIGHT"]["date"].max() == "2026-09-17"
    # FX of 09-17 (posted 17:00) is used for T=09-18, invisible on 09-17 evening via date guard, visible 09-18
    assert "2026-09-18" not in set(visible("2026-09-17T20:00:00+08:00")["date"])
    v = visible("2026-09-18T08:00:00+08:00")
    assert v[(v.symbol == "USDTWD") & (v.date == "2026-09-18")]["close"].item() == 31.9
    # US Fri 10-31 close is used Mon 11-03 and visible only from 05:30
    assert "2025-11-03" not in set(visible("2025-11-03T05:00:00+08:00")["date"])
    v = visible("2025-11-03T05:30:00+08:00")
    assert v[(v.symbol == "SPX") & (v.date == "2025-11-03")]["close"].item() == 6840.20


def test_coverage_counts():
    import pandas as pd
    df = pd.DataFrame([{"date": "2026-10-01", "symbol": "SPX", "source": "fred:SP500"},
                       {"date": "2026-10-02", "symbol": "SPX", "source": "fred:SP500"}])
    cov = O.coverage(df, "2026-09-28", "2026-10-04")
    assert cov == [{"symbol": "SPX", "source": "fred", "first": "2026-10-01", "last": "2026-10-02",
                    "rows": 2, "missing_weekdays": 3}]
