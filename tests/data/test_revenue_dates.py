"""Monthly revenue publication-date logic (offline; MOPS / FinMind samples in tests/fixtures/ca_samples)."""
import json
from pathlib import Path

import pandas as pd

from agent.data.fetchers import revenue_dates as R
from agent.data.loaders import HistoryStore
from agent.data.pit import PITView

S = Path(__file__).resolve().parents[1] / "fixtures" / "ca_samples"


def test_statutory_deadline_rolls_forward_never_earlier():
    assert R.statutory_deadline(2025, 5) == "2025-06-10"           # Tuesday
    assert R.statutory_deadline(2024, 9) == "2024-10-11"           # 10-10 National Day
    assert R.statutory_deadline(2024, 10) == "2024-11-11"          # 11-10 Sunday
    assert R.statutory_deadline(2024, 1) == "2024-02-15"           # Lunar New Year closure
    assert R.statutory_deadline(2026, 9) == "2026-10-12"           # 10-10 Saturday
    assert R.statutory_deadline(2024, 12) == "2025-01-10"          # year wrap
    for y in (2023, 2024, 2025, 2026):
        for m in range(1, 13):
            d = R.statutory_deadline(y, m)
            ny, nm = (y, m + 1) if m < 12 else (y + 1, 1)
            assert d >= f"{ny:04d}-{nm:02d}-10"


def test_statutory_deadline_uses_trading_calendar_when_covered():
    cal = [f"2025-03-{d:02d}" for d in (3, 4, 5, 6, 7, 11, 12, 13, 14, 17)]   # pretend 03-10 closed
    assert R.statutory_deadline(2025, 2, cal) == "2025-03-11"
    assert R.statutory_deadline(2025, 2) == "2025-03-10"


def test_placeholder_is_single_rule_and_published_date_overrides():
    assert R.placeholder_available_at(2024, 10) == "2024-11-11T23:59:00+08:00"
    assert R.available_at_for(2024, 10, None) == R.placeholder_available_at(2024, 10)
    assert R.available_at_for(2024, 10, "2024-11-05") == "2024-11-05T23:59:00+08:00"


def test_parse_mops_t21sc03_sample():
    p = R.parse_mops_t21sc03((S / "mops_t21sc03_sii_115_9.html").read_bytes())
    assert p["report_date"] == "2026-10-05" and (p["year"], p["month"]) == (2026, 9)
    assert p["revenue"]["1477"] == 2930592 * 1000.0                   # 聚陽, page unit 千元
    assert len(p["revenue"]) >= 20 and "合計" not in p["revenue"]


def test_apply_observations_first_seen_wins_and_adds_rows():
    df = pd.DataFrame([dict(ticker="1477", year=2026, month=9, revenue=1.0, published_date=None, available_at=None),
                       dict(ticker="2330", year=2026, month=8, revenue=2.0, published_date="2026-09-05",
                            available_at=None)])
    obs = [dict(ticker="1477", year=2026, month=9, revenue=3.0, seen="2026-10-05"),
           dict(ticker="2330", year=2026, month=8, revenue=2.0, seen="2026-09-09"),     # later: ignored
           dict(ticker="1560", year=2026, month=9, revenue=5.0, seen="2026-10-05"),
           dict(ticker="9999", year=2026, month=9, revenue=5.0, seen="2026-10-05")]     # not in universe
    out = R.apply_observations(df, obs, universe={"1477", "2330", "1560"})
    got = {(t, int(m)): p for t, m, p in zip(out["ticker"], out["month"], out["published_date"])}
    assert got == {("1477", 9): "2026-10-05", ("2330", 8): "2026-09-05", ("1560", 9): "2026-10-05"}
    out = R.apply_dates(out)
    assert set(out["available_at"]) == {"2026-10-05T23:59:00+08:00", "2026-09-05T23:59:00+08:00"}


def test_finmind_date_column_is_not_a_publication_date():
    j = json.loads((S / "finmind_revenue_2330.json").read_text(encoding="utf-8"))
    for r in j["data"]:
        y, m = (r["revenue_year"], r["revenue_month"] + 1) if r["revenue_month"] < 12 else (r["revenue_year"] + 1, 1)
        assert r["date"] == f"{y:04d}-{m:02d}-01"        # always the 1st of the following month
        assert r["create_time"] == ""


def test_pit_visibility_with_placeholder(tmp_path):
    st = HistoryStore(tmp_path)
    df = R.apply_dates(pd.DataFrame([dict(ticker="2330", year=2024, month=10, revenue=1.0, published_date=None),
                                     dict(ticker="2317", year=2024, month=10, revenue=1.0,
                                          published_date="2024-11-06")]))
    st.upsert("monthly_revenue", df)
    v = PITView(st, "2024-11-10T23:59:00+08:00").monthly_revenue()
    assert set(v["ticker"]) == {"2317"}                     # 2330 hidden until rolled deadline 11-11
    v = PITView(st, "2024-11-11T23:59:00+08:00").monthly_revenue()
    assert set(v["ticker"]) == {"2317", "2330"}
