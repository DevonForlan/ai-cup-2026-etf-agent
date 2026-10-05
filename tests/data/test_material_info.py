"""MOPS material information (t05st02) parser — offline, saved official samples (trimmed)."""
from pathlib import Path

from agent.data.fetchers import material_info as M
from agent.data.loaders import HistoryStore

S = Path(__file__).resolve().parents[1] / "fixtures" / "material_info_samples"
U = {"2327", "2887", "2615", "2330", "2603", "2891"}


def rows(name):
    return M.parse_t05st02((S / name).read_bytes())


def test_roc_date_and_time_conversion():
    assert M.roc_to_iso("114/10/27") == "2025-10-27"
    assert M.roc_to_iso("&nbsp;113/06/03") == "2024-06-03"
    assert M.roc_to_iso("1140213") == "2025-02-13"
    assert M.roc_to_iso("20261004") == "2026-10-04"
    assert M.norm_time("173005") == "17:30:05"
    assert M.norm_time("70004") == "07:00:04"
    assert M.norm_time("17:30:05") == "17:30:05"


def test_parse_fields_and_body():
    r = rows("t05st02_20251027_trim.html")
    assert len(r) == 61
    first = r[0]
    assert first["ticker"] == "2327" and first["typek"] == "sii"
    assert first["published_at"] == "2025-10-27T07:00:04+08:00"
    assert first["subject"].startswith("公告本公司股票面額由「新台幣10元」變更為「新台幣2.5元」")
    assert "\n" not in first["subject"]
    assert first["body"].startswith("1.事實發生日：民國114年07月08日")
    assert "7.其他應敘明事項：無" in first["body"]
    assert first["fact_date"] == "2025-07-08"
    # foreign issuer (DR) section: no hidden body -> empty, still parsed
    assert r[-1]["ticker"] == "912000" and r[-1]["body"] == ""


def test_prior_evening_rows_keep_their_own_date():
    r = rows("t05st02_20250213_trim.html")
    dates = {x["date"] for x in r}
    assert dates == {"2025-02-12", "2025-02-13"}
    tsmc = [x for x in r if x["ticker"] == "2330"][0]
    assert tsmc["published_at"] == "2025-02-12T17:41:33+08:00"
    assert all(x["date"] == "2025-02-13" or x["time"] >= "17:30:00" for x in r)


def test_universe_filter_and_records():
    recs = M.to_records(rows("t05st02_20251027_trim.html"), U)
    assert recs and {x["ticker"] for x in recs} <= U
    assert {"2327", "2887", "2615"} <= {x["ticker"] for x in recs}
    for x in recs:
        assert x["authority"] == "mops" and x["source"] == M.SOURCE
        assert x["available_at"] == x["published_at"]          # PIT: visible from the official 發言時間
        assert x["published_at"].endswith("+08:00")
    assert len(M.to_records(rows("t05st02_20251027_trim.html"), None)) > len(recs)


def test_event_key_stable_and_dedup(tmp_path):
    k1 = M.event_key("2330", "2025-02-12T17:41:33+08:00", "abc")
    assert k1 == M.event_key("2330", "2025-02-12T17:41:33+08:00", "abc")
    assert k1.startswith("sha256:") and k1 != M.event_key("2330", "2025-02-12T17:41:34+08:00", "abc")
    recs = M.to_records(rows("t05st02_20261004.html"), U)
    assert [x["ticker"] for x in recs] == ["2891"]
    assert recs[0]["published_at"] == "2026-10-04T18:04:41+08:00"
    st = HistoryStore(tmp_path)
    st.upsert("material_info", recs)
    st.upsert("material_info", M.to_records(rows("t05st02_20261004.html"), U))   # re-fetch: idempotent
    assert len(HistoryStore(tmp_path).load("material_info")) == 1


def test_day_list_weekends():
    from datetime import date
    assert len(M.day_list(date(2026, 10, 1), date(2026, 10, 7), True)) == 7
    assert [d.isoformat() for d in M.day_list(date(2026, 10, 2), date(2026, 10, 5), False)] == \
        ["2026-10-02", "2026-10-05"]
