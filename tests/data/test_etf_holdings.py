"""Offline tests for issuer ETF-holdings parsers, against real responses saved 2026-10-05
(tests/fixtures/etf_samples). No network."""
import json
from pathlib import Path

import pytest

from agent.data.fetchers import etf_holdings as E
from agent.data.loaders import SCHEMAS, HistoryStore

S = Path(__file__).resolve().parents[1] / "fixtures" / "etf_samples"
FETCHED = "2026-10-05T09:00:00+08:00"

# (file, parser, etf, asof, n, top ticker, top weight %, top shares, foreign?)
CASES = [
    ("ezmoney_00981A_20261002_trimmed.html", E.parse_ezmoney, "00981A", "2026-10-02", 50, "2330", 9.79, 11464000, False),
    ("nomura_00980A_20261002.json", E.parse_nomura, "00980A", "2026-10-02", 50, "2330", 9.31, 753000, False),
    ("capital_00982A_20261002.json", E.parse_capital, "00982A", "2026-10-02", 57, "2330", 8.6562, 1794000, False),
    ("fhtrust_00991A_20261002.xlsx", E.parse_fhtrust, "00991A", "2026-10-02", 50, "2330", 13.031, 4200000, False),
    ("fhtrust_00409A_20261001.xlsx", E.parse_fhtrust, "00409A", "2026-10-01", 51, "LITE US", 5.497, 25500, True),
    ("yuanta_00990A_20261001.json", E.parse_yuanta, "00990A", "2026-10-01", 47, "LITE US", 7.63, 87479, True),
    ("cathay_00400A_20261002.json", E.parse_cathay, "00400A", "2026-10-02", 45, "2330", 8.78, 1034000, False),
    ("ab_00404A_20260901.json", E.parse_ab, "00404A", "2026-09-01", 52, "2330", 22.081839, 308000, False),
    ("fubon_00405A_20260901.html", E.parse_fubon, "00405A", "2026-09-01", 50, "3017", 7.7103, 658000, False),
    ("kgi_00407A_20260831.html", E.parse_kgi, "00407A", "2026-08-31", 50, "2330", 8.65, 944000, False),
    ("sinopac_00410A_20260831_trimmed.html", E.parse_sinopac, "00410A", "2026-08-31", 29, "3008", 8.29, 20000, False),
    ("ctbc_00995A.json", E.parse_ctbc, "00995A", "2026-10-02", 57, "2330", 8.9, 174000, False),
    ("allianz_00993A.json", E.parse_nomura, "00993A", "2026-10-02", 51, "2330", 8.32, 349000, False),
    ("tsit_00987A.html", E.parse_tsit, "00987A", "2026-10-02", 29, "2330", 8.6665, 90000, False),
    ("fsitc_00408A.json", E.parse_fsitc, "00408A", "2026-10-02", 50, "2330", 5.65, 33998, False),
    ("mega_00996A_20260831.html", E.parse_mega, "00996A", "2026-08-31", 53, "2330", 10.37, 179000, False),
    ("jpm_00401A_20260901.xlsx", E.parse_jpm, "00401A", "2026-09-01", 60, "2330", 15.14, 202647, False),
    ("jpm_00401A_productdata.json", E.parse_jpm, "00401A", "2026-10-02", 56, "2330", 19.9646, 300960, False),
]


@pytest.mark.parametrize("fname,parser,etf,asof,n,top,topw,topsh,foreign", CASES, ids=[c[2] for c in CASES])
def test_parsers(fname, parser, etf, asof, n, top, topw, topsh, foreign):
    p = parser((S / fname).read_bytes(), etf)
    assert p.asof == asof
    assert len(p.holdings) == n
    best = max(p.holdings, key=lambda h: h.weight_pct)
    assert best.ticker == top and best.weight_pct == pytest.approx(topw)
    assert best.shares == pytest.approx(topsh)
    tot = sum(h.weight_pct for h in p.holdings)
    assert 85 < tot <= 101, tot  # stocks are most, but not all, of NAV
    tw = [h for h in p.holdings if h.ticker.isdigit()]
    assert all(len(h.ticker) in (4, 5, 6) for h in tw)
    if not foreign:
        assert len(tw) == n


@pytest.mark.parametrize("fname,parser,etf,asof,n,top,topw,topsh,foreign", CASES, ids=[c[2] for c in CASES])
def test_to_rows_schema_and_pit(fname, parser, etf, asof, n, top, topw, topsh, foreign):
    p = parser((S / fname).read_bytes(), etf)
    fetched = f"{asof}T23:30:00+08:00"  # pretend fetched the same evening -> not stale
    rows = E.to_rows(p, etf, source_url="https://example.invalid/x", fetched_at=fetched, latest_mode=True)
    assert rows and set(rows[0]) == set(SCHEMAS["etf_holdings"])
    assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))
    ws = [r["weight"] for r in rows]
    assert ws == sorted(ws, reverse=True) and 0 < ws[0] < 1
    assert len({r["ticker"] for r in rows}) == len(rows)
    for r in rows:
        assert r["synthetic"] is False and r["authority"] == "fininst" and r["etf"] == etf
        assert r["date"] == asof and r["is_stale"] is False
        # PIT: never visible before the evening of the holdings date
        assert r["available_at"] >= f"{asof}T22:00:00+08:00"
        assert r["available_at"].endswith("+08:00")


def test_published_at_moves_available_at_later():
    p = E.parse_yuanta((S / "yuanta_00990A_20261001.json").read_bytes(), "00990A")
    assert p.published_at == "2026-10-02T14:11:41+08:00"  # foreign legs published next day
    rows = E.to_rows(p, "00990A", source_url="u", fetched_at=FETCHED, latest_mode=False)
    assert rows[0]["available_at"] == "2026-10-02T14:11:41+08:00"


def test_stale_flag():
    p = E.parse_nomura((S / "nomura_00980A_20261002.json").read_bytes(), "00980A")
    rows = E.to_rows(p, "00980A", source_url="u", fetched_at="2026-10-20T09:00:00+08:00", latest_mode=True)
    assert all(r["is_stale"] for r in rows)
    rows = E.to_rows(p, "00980A", source_url="u", fetched_at="2026-10-20T09:00:00+08:00", latest_mode=False)
    assert not any(r["is_stale"] for r in rows)


def test_empty_responses():
    assert E.parse_nomura(json.dumps({"Entries": {"FundID": "00980A", "Data": {"FundAsset": None, "Table": []}}}).encode(), "x").asof is None
    assert E.parse_cathay(json.dumps({"SearchDate": "2026-10-03", "stock": {"result": None, "success": False}}).encode(), "x").asof is None
    assert E.parse_capital(json.dumps({"code": 200, "data": {"pcf": None, "stocks": []}}).encode(), "x").asof is None
    assert E.parse_ezmoney(b"<html></html>", "x").asof is None
    assert E.to_rows(E.Parsed(None), "x", source_url="u", fetched_at=FETCHED, latest_mode=True) == []


def test_upsert_keeps_synthetic_rows(tmp_path):
    st = HistoryStore(tmp_path)
    st.upsert("etf_holdings", [dict(date="2025-01-02", etf="00981A", ticker="2330", weight=0.1, rank=1,
                                    shares=1.0, source_url="", published_at="", fetched_at="",
                                    authority="other", is_stale=False, available_at="2025-01-02T00:00:00+08:00",
                                    synthetic=True)])
    p = E.parse_ezmoney((S / "ezmoney_00981A_20261002_trimmed.html").read_bytes(), "00981A")
    st.upsert("etf_holdings", E.to_rows(p, "00981A", source_url="u", fetched_at=FETCHED, latest_mode=True))
    df = HistoryStore(tmp_path).load("etf_holdings")
    assert df["synthetic"].sum() == 1 and (~df["synthetic"]).sum() == 50
    assert set(df.loc[~df["synthetic"], "date"]) == {"2026-10-02"}


def test_registry_covers_official_list():
    import csv
    root = Path(__file__).resolve().parents[2]
    with open(root / "config" / "active_etf_list.csv", encoding="utf-8-sig") as f:
        codes = {r["etf_code"] for r in csv.DictReader(f)}
    assert codes == set(E.REGISTRY)
    for etf, src in E.REGISTRY.items():
        assert (src.kind in E.ISSUERS) or (src.kind == "" and src.note), etf


def test_all_official_etfs_have_a_source():
    assert all(src.kind in E.ISSUERS for src in E.REGISTRY.values())


def test_html_table_skips_non_code_rows():
    t = ("<table><tr><th>股票代號</th><th>股票名稱</th><th>股數</th><th>權重(%)</th></tr>"
         "<tr><td>2330 TT</td><td>台積電</td><td>1,000</td><td>8.5%</td></tr>"
         "<tr><td>合計</td><td></td><td></td><td>8.5</td></tr></table>")
    hs = E.html_holdings_table(t)
    assert [(h.ticker, h.shares, h.weight_pct) for h in hs] == [("2330", 1000.0, 8.5)]


def test_iso_and_dates():
    assert E._ymd("2026/9/1") == "2026-09-01" and E._ymd("20261001") == "2026-10-01"
    assert E._ymd("2026-10-02T00:00:00") == "2026-10-02"
    assert E._iso_tpe("2026-10-02T16:38:03") == "2026-10-02T16:38:03+08:00"
    assert E.norm_ticker(" lite  us ") == "LITE US" and E.norm_ticker("2330.TW") == "2330"
