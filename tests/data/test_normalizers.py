"""Parsers against real raw responses saved on 2026-10-04/05 (tests/fixtures/raw_samples)."""
from decimal import Decimal
from pathlib import Path

from agent.data import normalizers as N

RAW = Path(__file__).resolve().parents[1] / "fixtures" / "raw_samples"


def test_twse_mi_index(rb):
    rows = N.parse_twse_mi_index((RAW / "twse_MI_INDEX_20261002.json").read_bytes(), "2026-10-02",
                                 {t for t, v in rb.universe.items() if v["market"] == "TWSE"})
    assert len(rows) == 100
    r = {x["ticker"]: x for x in rows}["2330"]
    assert r["vwap"] == r["amount"] / r["volume"]
    assert r["low"] <= r["vwap"] <= r["high"]
    assert r["market"] == "TWSE"


def test_tpex_daily_quotes(rb):
    rows = N.parse_tpex_daily_quotes((RAW / "tpex_dailyQuotes_20261002.json").read_bytes(), "2026-10-02",
                                     {t for t, v in rb.universe.items() if v["market"] == "TPEx"})
    assert len(rows) == 50
    for r in rows:
        if r["volume"]:
            assert r["low"] <= r["vwap"] <= r["high"], r["ticker"]


def test_institutional_parsers(rb):
    tw = N.parse_twse_t86((RAW / "twse_T86_20261002.json").read_bytes(), "2026-10-02", set(rb.universe))
    ot = N.parse_tpex_insti((RAW / "tpex_dailyTrade_20261002.json").read_bytes(), "2026-10-02", set(rb.universe))
    assert len(tw) == 100 and len(ot) == 50
    for r in tw + ot:
        assert isinstance(r["total_net"], Decimal)


def test_num_parsing():
    assert N._num("1,234") == Decimal(1234)
    assert N._num("--") is None and N._num("") is None
