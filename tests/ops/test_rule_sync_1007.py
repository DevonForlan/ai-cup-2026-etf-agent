"""Official rule sync 2026-10-07/12: Active Share (top-15, NAV weights, cash, 15%), first trade date,
first submission window, last-successful-submission rule, D-Plan v4.3 and the official DataPack."""
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from agent.config import load_official_rules
from agent.engine.active_share import (OFFICIAL_MODE, compute_active_share, compute_official_active_share,
                                       official_active_share)
from agent.engine.compliance import check_active_share
from agent.ops import deadline as DL
from agent.ops.datapack import import_datapack, parse_datapack
from agent.submission.receipt import effective_submission

ROOT = Path(__file__).resolve().parents[2]
D = Decimal


def _bench(n=20, w="0.04"):
    return {f"{1000 + i}": D(w) for i in range(n)}


# ---------------------------------------------------------------- Active Share
def _res_for(value: str, rb):
    """A portfolio/benchmark pair whose official Active Share is exactly `value`."""
    from agent.engine.active_share import ActiveShareResult
    return ActiveShareResult(OFFICIAL_MODE, D(value), "00999A", {OFFICIAL_MODE: D(value)}, {}, [], None, False,
                             "NEED_CONFIRMATION")


@pytest.mark.parametrize("value,status", [("0.1499", "FAIL"), ("0.15", "WARNING"), ("0.2999", "WARNING"),
                                          ("0.30", "PASS")])
def test_official_threshold_15pct_and_internal_target_30pct(rb, value, status):
    rep = check_active_share(_res_for(value, rb), rb, D("0.30"))
    c = rep.checks[-1]
    assert c.status.value == status
    if status == "FAIL":
        assert "官方門檻 15%" in c.message
    assert load_official_rules().raw["official_rules"]["active_share"]["official_threshold"] == 0.15


def test_top15_union_calculation():
    # portfolio holds 16 names; only its top 15 count. Benchmark 20 names; only its top 15 count.
    port = {f"{1000 + i}": D("0.05") for i in range(10)} | {f"{2000 + i}": D("0.06") for i in range(5)}
    port["9999"] = D("0.01")                                             # 16th -> excluded
    bench = {f"{1000 + i}": D("0.05") for i in range(15)} | {f"{3000 + i}": D("0.01") for i in range(5)}
    v, cs = official_active_share(port, bench, 15)
    # overlap 1000-1009 identical (0); 2000-2004 only in port (5 x 0.06); 1010-1014 only in bench (5 x 0.05)
    assert v == (D("0.30") + D("0.25")) / 2 and cs == "NEED_CONFIRMATION"
    v16, _ = official_active_share(port, bench, 16)   # 16th names (9999 in port, a 3000 in bench) each add 0.01/2
    assert v16 == v + D("0.01")


def test_cash_included_when_both_known_and_never_guessed():
    port = {"2330": D("0.20"), "2317": D("0.70")}
    bench = {"2330": D("0.30"), "2317": D("0.60")}
    base, cs = official_active_share(port, bench, 15, port_cash=D("0.10"), bench_cash=None)
    assert base == D("0.10") and cs == "NEED_CONFIRMATION"              # benchmark cash unknown -> no 0 filled
    v, cs = official_active_share(port, bench, 15, port_cash=D("0.10"), bench_cash=D("0.04"))
    assert v == D("0.10") + D("0.03") and cs == "INCLUDED"                # |0.10 - 0.04| / 2
    assert v >= base                                                     # leaving the term out is conservative
    v0, cs0 = official_active_share(port, bench, 15, D("0.10"), D("0.04"), include_cash=False)
    assert v0 == base and cs0 == "EXCLUDED_BY_CONFIG"


def test_every_official_etf_compared_minimum_used():
    port = {f"{1000 + i}": D("0.04") for i in range(25)}
    etfs = {"A": _bench(20), "B": {f"{5000 + i}": D("0.04") for i in range(20)}, "C": {}}
    r = compute_official_active_share(port, etfs, ["A", "B", "C"])
    assert set(r.per_etf) == {"A", "B"} and r.missing_benchmarks == ["C"]
    assert r.benchmark_ticker == "A" and r.minimum_active_share == min(v[OFFICIAL_MODE] for v in r.per_etf.values())


def test_legacy_internal_guard_metric_unchanged():
    """Quant Core v1's internal guard still uses the frozen top-10 interpretations (decision path unchanged)."""
    port = {f"{1000 + i}": D("0.04") for i in range(25)}
    r = compute_active_share(port, {"A": _bench(20)}, ["A"], "UNKNOWN")
    assert set(r.min_by_mode) == {"NAV_WEIGHT", "TOP10_NORMALIZED", "FULL_PORTFOLIO"}


# ---------------------------------------------------------------- calendar / window / submissions
def test_first_trade_date_and_market_closed_1026():
    r = load_official_rules().raw["official_rules"]
    assert r["first_trade_date"] == "2026-10-27"
    cal = yaml.safe_load((ROOT / "config/trading_calendar_2026.yaml").read_text(encoding="utf-8"))
    days = [str(x) for x in cal["competition_period_trading_days"]]
    assert days[0] == "2026-10-27" and "2026-10-26" not in days and len(days) == 24
    assert date(2026, 10, 26).weekday() == 0                             # a Monday, but a market holiday


def test_first_submission_window_opens_1026_1930():
    opens, closes = DL.opening_for("2026-10-27"), DL.cutoff_for("2026-10-27")
    assert opens.isoformat() == "2026-10-26T19:30:00+08:00" and closes.isoformat() == "2026-10-27T08:55:00+08:00"
    w = load_official_rules().raw["official_rules"]["first_submission_window"]
    assert (w["opens"], w["closes"]) == (opens.isoformat(), closes.isoformat())


def _rcpt(t, status, sha="a"):
    return {"trade_date": "2026-10-27", "team_id": "T", "dplan_sha256": f"sha256:{sha * 64}",
            "submitted_at": f"2026-10-{t}+08:00", "official_status": status}


def test_last_successful_submission_wins_not_last_upload():
    rs = [_rcpt("26T19:40:00", "accepted", "a"), _rcpt("27T07:10:00", "accepted", "b"),
          _rcpt("27T08:30:00", "rejected", "c"), _rcpt("27T09:00:00", "accepted", "d")]
    e = effective_submission(rs, "2026-10-27")
    assert e["effective"]["dplan_sha256"].endswith("b" * 64)            # last ACCEPTED before 08:55
    assert e["last_upload"]["dplan_sha256"].endswith("c" * 64) and not e["last_upload_is_effective"]
    assert e["late_ignored"] == 1 and e["uploads"] == 3 and not e["limit_reached"]
    assert load_official_rules().raw["official_rules"]["multiple_submission_rule"].startswith("last_successful")
    assert effective_submission([_rcpt("26T20:00:00", "accepted")] * 25, "2026-10-27")["limit_reached"]


# ---------------------------------------------------------------- D-Plan v4.3
def test_dplan_runtime_is_official_v43():
    import jsonschema
    r = load_official_rules()
    assert r.schema_path.name == "D-Plan.schema_v4.3.json" and r.raw["dplan"]["schema_version"] == "4.3"
    schema = json.loads(r.schema_path.read_text(encoding="utf-8"))
    ex = json.loads((ROOT / "research/official_updates/D-Plan_TEAM_042_2026-10-28.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(ex)                 # official positive example passes
    assert (ROOT / "D-Plan.schema_v4.2.json").exists()                  # root official files untouched


# ---------------------------------------------------------------- DataPack
SPEC_HOLDINGS = [{"code": "2330", "shares": 73000, "receivable_shares": 0, "close_price": 2585.0},
                 {"code": "2317", "shares": 267000, "receivable_shares": 0, "close_price": 256.0},
                 {"code": "6669", "shares": 0, "receivable_shares": 9913, "close_price": 2610.0}]


def _dp(**over):
    cash = 135237741.0
    nav = cash + 73000 * 2585.0 + 267000 * 256.0
    d = {"schema_version": "3.0", "doc_type": "DataPack", "team_id": "TEAM_042", "trade_date": "2026-10-28",
         "as_of_date": "2026-10-27", "generated_at": "2026-10-27T18:58:18+08:00", "missing": [],
         "prev_day_orders": {"outcome": "executed", "void_reasons": [], "excluded_codes": []},
         "account": {"cash": cash, "cash_ratio_tradable": cash / nav, "nav_tradable": nav, "aum": nav,
                     "receivable_cash": 0.0, "holdings_count": 2},
         "holdings": SPEC_HOLDINGS, "compliance": {"violations": 0, "notices": 0, "incidents": []}}
    d.update(over)
    return d


def test_datapack_parses_to_official_settlement():
    off, probs, warns, info = parse_datapack(_dp(), "TEAM_042", "2026-10-28")
    assert probs == [] and off["date"] == "2026-10-27"
    assert off["holdings"] == {"2330": 73000, "2317": 267000}            # receivable shares are not tradable
    assert info["receivable_shares"] == {"6669": 9913} and any("receivable" in w for w in warns)


@pytest.mark.parametrize("over,needle", [
    ({"team_id": "TEAM_043"}, "team_id"),
    ({"trade_date": "2026-10-29"}, "trade_date"),
    ({"missing": ["prev_settlement"], "account": None, "holdings": None, "as_of_date": None}, "prev_settlement"),
    ({"doc_type": "D-Plan"}, "doc_type"),
])
def test_datapack_refused(over, needle):
    off, probs, _, _ = parse_datapack(_dp(**over), "TEAM_042", "2026-10-28")
    assert off is None and any(needle in p for p in probs)


def test_datapack_nav_identity_checked():
    d = _dp()
    d["account"] = dict(d["account"], nav_tradable=d["account"]["nav_tradable"] + 1000)
    off, probs, _, _ = parse_datapack(d, "TEAM_042", "2026-10-28")
    assert off is None and any("nav_tradable" in p for p in probs)


def test_datapack_first_day_and_import(tmp_path, ops_cfg):
    first = _dp(trade_date="2026-10-27", as_of_date=None, holdings=[],
                account={"cash": 1e9, "cash_ratio_tradable": 1.0, "nav_tradable": 1e9, "aum": 1e9,
                         "receivable_cash": 0.0, "holdings_count": 0},
                prev_day_orders={"outcome": "none", "void_reasons": [], "excluded_codes": []})
    f0 = tmp_path / "dp0.json"
    f0.write_text(json.dumps(first), encoding="utf-8")
    assert import_datapack(f0, "TEAM_042", "2026-10-27", "operator A", ops_cfg)["status"] == "INITIAL_DAY"
    f1 = tmp_path / "dp1.json"
    f1.write_text(json.dumps(_dp()), encoding="utf-8")
    r = import_datapack(f1, "TEAM_042", "2026-10-28", "operator A", ops_cfg)
    assert r["status"] == "IMPORTED" and r["as_of_date"] == "2026-10-27"
    from agent.ops.settlement import ManualFileSettlementProvider
    from agent.ops.settlement_entry import confirmation_status
    assert ManualFileSettlementProvider(ops_cfg).get("2026-10-27")["holdings"]["2330"] == 73000
    cs = confirmation_status("2026-10-27", ops_cfg)
    assert cs["confirmed"] and cs["double_entry"] == "NOT_NEEDED_OFFICIAL_DATAPACK"
    assert import_datapack(f1, "TEAM_042", "2026-10-28", "", ops_cfg)["status"] == "BLOCK"   # operator required


def test_daily_compliance_summary_in_operator_output(fixture_store, ops_cfg):
    from agent.competition_day import operator_summary
    from tests.ops.test_competition_day import CLK1, T1, run
    s = run(fixture_store, ops_cfg, T1, CLK1, mode="dry-run", initial=True)
    cs = s["compliance_summary"]
    for k in ("Universe 150", "Holdings 20-30", "2330 <= 25%", "Other stocks <= 10%", "Cash < 25%",
              "Active Share official >= 15%", "Active Share internal safety target", "Strategy consistency",
              "D-Plan validation", "Manual override", "Claude runtime"):
        assert k in cs
    assert cs["Manual override"] == "NO" and cs["Claude runtime"] == "TEMPLATE" and cs["D-Plan validation"] == "PASS"
    txt = operator_summary(s)
    assert "COMPLIANCE" in txt and "Overall" in txt and "READY" in txt
