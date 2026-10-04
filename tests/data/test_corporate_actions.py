"""Corporate actions parsers (offline, saved official TWSE/TPEx samples in tests/fixtures/ca_samples)."""
import math
from pathlib import Path

import pytest

from agent.data.fetchers import corporate_actions as C
from agent.data.loaders import HistoryStore
from agent.data.pit import PITView

S = Path(__file__).resolve().parents[1] / "fixtures" / "ca_samples"
TW = {"2330", "2884", "2344", "3481", "2327", "1101", "6919"}
TP = {"5289", "6187", "3293", "6182", "8069", "5274", "4154"}


def rb(name):
    return (S / name).read_bytes()


def test_roc_dates_and_numbers():
    assert C.roc_to_iso("113年07月01日") == "2024-07-01"
    assert C.roc_to_iso("113/08/26") == "2024-08-26"
    assert C.roc_to_iso("1130902") == "2024-09-02"
    assert C.roc_to_iso("20240814") == "2024-08-14"
    assert C.num("1,215.00") == 1215.0
    assert C.num("1.2 元／股") == 1.2
    assert C.num("880.00000000&nbsp股") == 880.0


def test_prev_trading_day_uses_calendar_or_weekday():
    assert C.prev_trading_day("2024-07-01") == "2024-06-28"          # Monday -> Friday
    cal = ["2024-02-06", "2024-02-07", "2024-02-15"]                  # Lunar NY closure
    assert C.prev_trading_day("2024-02-15", cal) == "2024-02-14"      # gap > 4 days -> weekday fallback
    assert C.prev_trading_day("2024-02-07", cal) == "2024-02-06"


def test_twse_cash_only_and_universe_filter():
    base = C.parse_twse_twt49u(rb("twse_TWT49U.json"), TW)
    assert {b["ticker"] for b in base} <= TW and "2882" not in {b["ticker"] for b in base}
    tsmc = [b for b in base if b["ticker"] == "2330"][0]
    ev = C.event_from_twse(tsmc, None)
    assert ev["ex_date"] == "2024-03-18" and ev["action_type"] == "cash"
    assert ev["cash_dividend"] == pytest.approx(3.499789)
    assert ev["stock_dividend_per_share"] == 0.0 and math.isnan(ev["capital_change_ratio"])
    assert ev["available_at"] == "2024-03-15T18:00:00+08:00"


def test_twse_cash_plus_stock_from_detail():
    base = [b for b in C.parse_twse_twt49u(rb("twse_TWT49U.json"), TW) if b["ticker"] == "2884"][0]
    det = C.parse_twse_twt49u_detail(rb("twse_TWT49UDetail_2884_20240725.json"))
    assert det == {"cash": 1.2, "stock": 0.02, "rights": False}
    ev = C.event_from_twse(base, det)
    assert ev["action_type"] == "cash+stock" and ev["source"].endswith("+detail")
    # consistency with the TWSE reference-price formula: P - (P - c)/(1 + s) ~= 權值+息值
    P = base["prev_close"]
    assert P - (P - 1.2) / 1.02 == pytest.approx(base["value"], abs=0.01)


def test_twse_pure_stock_fallback_derivation():
    base = [b for b in C.parse_twse_twt49u(rb("twse_TWT49U.json"), TW) if b["ticker"] == "2344"][0]
    ev = C.event_from_twse(base, None)
    s = 25.50 / (25.50 - 0.177778) - 1
    assert ev["stock_dividend_per_share"] == pytest.approx(s, rel=1e-6)
    assert ev["action_type"] == "stock" and ev["source"].endswith("+derived")


def test_twse_reduction_with_detail():
    base = C.parse_twse_twtauu(rb("twse_TWTAUU.json"), TW)
    assert [b["ticker"] for b in base] == ["3481"]
    det = C.parse_twse_twtavu_detail(rb("twse_TWTAVUDetail_3481_20240814.json"))
    ev = C.event_from_reduction(base[0], det, "twse_twtauu")
    assert ev["ex_date"] == "2024-08-26" and ev["action_type"] == "reduction"
    assert ev["capital_change_ratio"] == pytest.approx(0.88)
    assert ev["cash_dividend"] == pytest.approx(1.2)             # 退還股款 per old share
    assert ev["available_at"] == "2024-08-14T18:00:00+08:00"     # last cum day (halt starts 08-15)
    # reference price check: (14.55 - 1.2) / 0.88 = 15.17
    assert (base[0]["prev_close"] - 1.2) / 0.88 == pytest.approx(base[0]["ref_price"], abs=0.01)


def test_twse_split():
    ev = C.parse_twse_twtb8u(rb("twse_TWTB8U.json"), TW)
    yageo = [e for e in ev if e["ticker"] == "2327"][0]
    assert yageo["ex_date"] == "2025-08-25" and yageo["action_type"] == "split"
    assert yageo["capital_change_ratio"] == pytest.approx(4.0)
    assert yageo["available_at"] < "2025-08-25"


def test_tpex_exdailyq():
    ev = {(e["ticker"], e["ex_date"]): e for e in C.parse_tpex_exdailyq(rb("tpex_exDailyQ.json"), TP)}
    a = ev[("5289", "2024-07-15")]
    assert a["action_type"] == "cash+stock" and a["cash_dividend"] == pytest.approx(10.2)
    assert a["stock_dividend_per_share"] == pytest.approx(0.02, abs=1e-6)
    assert ev[("3293", "2024-07-24")]["stock_dividend_per_share"] == pytest.approx(1.0)
    assert ev[("6182", "2024-09-24")]["action_type"] == "rights"
    assert ev[("6187", "2024-07-17")]["action_type"] == "cash+rights"
    assert ev[("5274", "2026-07-07")]["action_type"] == "stock"
    assert all(e["available_at"].endswith("T18:00:00+08:00") and e["available_at"][:10] < e["ex_date"]
               for e in ev.values())


def test_tpex_reduction_detail_html():
    ev = C.parse_tpex_revivt(rb("tpex_revivt.json"), TP)
    assert len(ev) == 1 and ev[0]["ticker"] == "4154"
    assert ev[0]["capital_change_ratio"] == pytest.approx(0.69041489)
    assert ev[0]["available_at"] == "2024-08-22T18:00:00+08:00"   # halt starts 2024-08-23


def test_merge_same_day_events():
    a = dict(ex_date="2024-08-26", ticker="X", cash_dividend=1.0, stock_dividend_per_share=0.0,
             capital_change_ratio=float("nan"), action_type="cash", source="a", available_at="2024-08-23T18:00:00+08:00")
    b = dict(a, cash_dividend=0.5, capital_change_ratio=0.9, action_type="reduction", source="b",
             available_at="2024-08-14T18:00:00+08:00")
    m = C.merge_events([a, b])
    assert len(m) == 1 and m[0]["cash_dividend"] == 1.5 and m[0]["capital_change_ratio"] == 0.9
    assert m[0]["action_type"] == "cash+reduction" and m[0]["available_at"] == "2024-08-23T18:00:00+08:00"


def test_fetch_end_to_end_offline(monkeypatch, tmp_path):
    routes = {"TWT49UDetail": "twse_TWT49UDetail_2884_20240725.json", "TWT49U?": "twse_TWT49U.json",
              "TWTAVUDetail": "twse_TWTAVUDetail_3481_20240814.json", "TWTAUU": "twse_TWTAUU.json",
              "TWTB8U": "twse_TWTB8U.json", "exDailyQ": "tpex_exDailyQ.json", "revivt": "tpex_revivt.json"}
    calls = []

    def fake_get(session, url, **kw):
        calls.append(url)
        if "TWT49UDetail" in url and "2884" not in url:
            raise RuntimeError("not in fixtures")
        for k, f in routes.items():
            if k in url:
                from agent.data.http import now_tpe
                return rb(f), now_tpe()
        raise AssertionError(url)

    monkeypatch.setattr(C, "get_bytes", fake_get)
    rows, stats = C.fetch_corporate_actions("2024-03-01", "2024-12-31", TW, TP, session=object(),
                                            raw_dir=tmp_path / "raw")
    keys = {(r["ex_date"], r["ticker"]) for r in rows}
    assert ("2024-07-25", "2884") in keys and ("2024-08-26", "3481") in keys and ("2024-07-15", "5289") in keys
    assert all("2024-03-01" <= r["ex_date"] <= "2024-12-31" for r in rows)
    assert stats["twse_detail"] == 1 and any("2344" in f for f in stats["failed"])

    st = HistoryStore(tmp_path / "hist")
    st.upsert("corporate_actions", rows)
    seen = PITView(st, "2024-07-24T18:00:00+08:00").table("corporate_actions")
    assert ("2024-07-25", "2884") in set(zip(seen["ex_date"], seen["ticker"]))
    before = PITView(st, "2024-07-24T17:59:00+08:00").table("corporate_actions")
    assert ("2024-07-25", "2884") not in set(zip(before["ex_date"], before["ticker"]))
