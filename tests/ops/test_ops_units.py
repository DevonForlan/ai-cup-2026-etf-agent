"""Round 05 operational units: provider parsers, settlement import, reconciliation, data health, preflight,
deadline guard, package / manifest / FINAL_CANDIDATE / archive, first-seen ledger."""
import dataclasses
import json
from pathlib import Path
from decimal import Decimal

import pytest

from agent.llm.base import LLMFormatError
from agent.llm.providers.http_providers import AnthropicProvider, GeminiProvider, OpenAIProvider
from agent.ops import deadline as DL
from agent.ops.archive_run import archive_run, run_id_for
from agent.ops.common import BLOCK, PASS, WARN, Clock, sha256_file
from agent.ops.package_submission import build_package, mark_final, verify_package
from agent.ops.preflight import previous_portfolio_check, run_preflight
from agent.ops.reconcile import reconcile
from agent.ops.refresh_daily import append_first_seen, first_seen_available, refresh
from agent.ops.settlement import ManualFileSettlementProvider, path_for, save_official
from agent.pipeline import run_day
from agent.sim.calendar import TradingCalendar
from agent.sim.models import Settlement
from tests.ops.conftest import CLEAN_GIT, DIRTY_GIT

T1 = "2026-10-26"


# ----------------------------------------------------------------------------- real-provider parsers
def test_gemini_parser_ok_and_usage():
    j = {"candidates": [{"content": {"parts": [{"text": '{"a":'}, {"text": " 1}"}]}, "finishReason": "STOP"}],
         "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 30}, "modelVersion": "gemini-x-001"}
    assert GeminiProvider.parse(j) == ('{"a": 1}', 120, 30, "gemini-x-001")


@pytest.mark.parametrize("j", [
    {"promptFeedback": {"blockReason": "SAFETY"}},
    {"candidates": [{"finishReason": "SAFETY"}]},
    {"candidates": [{"content": {"parts": []}, "finishReason": "MAX_TOKENS"}]},
])
def test_gemini_parser_blocked_or_empty_is_format_error(j):
    with pytest.raises(LLMFormatError):
        GeminiProvider.parse(j)


def test_openai_anthropic_parsers():
    assert OpenAIProvider.parse({"choices": [{"message": {"content": "x"}}], "usage": {"prompt_tokens": 5,
                                "completion_tokens": 2}, "model": "m"}) == ("x", 5, 2, "m")
    with pytest.raises(LLMFormatError):
        OpenAIProvider.parse({"choices": [{"message": {"content": None}, "finish_reason": "content_filter"}]})
    assert AnthropicProvider.parse({"content": [{"type": "text", "text": "y"}], "usage": {"input_tokens": 3,
                                   "output_tokens": 1}, "model": "c"}) == ("y", 3, 1, "c")
    with pytest.raises(LLMFormatError):
        AnthropicProvider.parse({"content": [], "stop_reason": "max_tokens"})


def test_gemini_accepts_google_api_key_name(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy-not-a-key")
    assert GeminiProvider("m").available()
    monkeypatch.delenv("GOOGLE_API_KEY")
    assert not GeminiProvider("m").available()


# ----------------------------------------------------------------------------- settlement import + reconciliation
OFFICIAL = {"date": T1, "holdings": {"2330": 17000, "2317": 50000}, "cash": "1000000", "nav": "30000000",
            "accrued_dividends": "0", "warnings": [], "source": "test"}


def test_manual_settlement_json_and_csv(ops_cfg, tmp_path):
    save_official(OFFICIAL, ops_cfg)
    got = ManualFileSettlementProvider(ops_cfg).get(T1)
    assert got["holdings"] == {"2330": 17000, "2317": 50000} and got["cash"] == "1000000"
    path_for(T1, "official", ops_cfg).unlink()
    c = tmp_path / "off.csv"
    c.write_text("ticker,shares\n2330,\"17,000\"\n2317,50000\n__CASH__,1000000\n__NAV__,30000000\n", encoding="utf-8")
    got2 = ManualFileSettlementProvider(ops_cfg, csv_path=c).get(T1)
    assert got2["holdings"] == got["holdings"] and got2["nav"] == "30000000"
    c.write_text("ticker,shares\n2330,17000\n", encoding="utf-8")
    with pytest.raises(ValueError):
        ManualFileSettlementProvider(ops_cfg, csv_path=c).get(T1)


def test_reconcile_levels(ops_cfg):
    assert reconcile(dict(OFFICIAL), OFFICIAL, ops_cfg)["status"] == "MATCH"
    minor = dict(OFFICIAL, cash="1000500", nav="30000500")
    assert reconcile(minor, OFFICIAL, ops_cfg)["status"] == "MINOR_DIFFERENCE"
    shares = dict(OFFICIAL, holdings={"2330": 16000, "2317": 50000})
    r = reconcile(shares, OFFICIAL, ops_cfg)
    assert r["status"] == "BLOCK" and r["diffs"][0]["ticker"] == "2330"
    assert reconcile(dict(OFFICIAL, cash="900000"), OFFICIAL, ops_cfg)["status"] == "BLOCK"
    assert reconcile(dict(OFFICIAL, warnings=["cash"]), OFFICIAL, ops_cfg)["status"] == "BLOCK"


# ----------------------------------------------------------------------------- data health / refresh policy
def _fake(latest="2026-10-23", fail=()):
    def mk(name):
        def f(ctx):
            if name in fail:
                raise RuntimeError(f"{name} down")
            return {"records": 1, "latest_available_date": latest, "content_as_of": latest}
        return f
    names = ["twse_prices", "tpex_prices", "twse_institutional", "tpex_institutional", "etf_holdings",
             "corporate_actions", "mops_revenue_first_seen", "mops_material_info", "taifex_night", "us_market"]
    return {n: mk(n) for n in names}


def test_refresh_optional_failure_is_warn_critical_is_block(ops_cfg, fixture_store):
    clk = Clock("2026-10-25T20:00:00+08:00")
    ok = refresh(T1, store=fixture_store, fetchers=_fake(), ops_cfg=ops_cfg, clock=clk)
    assert ok["level"] == PASS
    assert {"source", "requested_date", "latest_available_date", "status", "records", "fetched_at", "content_as_of",
            "stale", "error", "duration"} <= set(ok["sources"][0])
    w = refresh(T1, store=fixture_store, fetchers=_fake(fail={"us_market", "taifex_night"}), ops_cfg=ops_cfg, clock=clk)
    assert w["level"] == WARN
    c = refresh(T1, store=fixture_store, fetchers=_fake(fail={"twse_prices"}), ops_cfg=ops_cfg, clock=clk)
    assert c["level"] == WARN                # fetch failed but T-1 prices already in the store -> CACHED
    assert next(x for x in c["sources"] if x["source"] == "twse_prices")["status"] == "CACHED"
    from tests.ops.conftest import store_without_date
    st2 = store_without_date(fixture_store, Path(ops_cfg["paths"]["settlement_dir"]).parent / "st2", "2026-10-23")
    b = refresh(T1, store=st2, fetchers=_fake(fail={"twse_prices"}), ops_cfg=ops_cfg, clock=clk)
    assert b["level"] == BLOCK               # T-1 missing: never use an outdated critical price
    stale = refresh(T1, store=fixture_store, fetchers=_fake(latest="2026-10-21"), ops_cfg=ops_cfg, clock=clk)
    assert stale["level"] == BLOCK          # T-1 prices missing (stale) is critical
    assert (tmp := ops_cfg["paths"]["ops_logs_dir"]) and json.loads(
        (__import__("pathlib").Path(tmp) / "20261026" / "data_health.json").read_text(encoding="utf-8"))["level"] == BLOCK


def test_refresh_deadline_skips_heavy_noncritical(ops_cfg, fixture_store):
    r = refresh(T1, store=fixture_store, fetchers=_fake(), ops_cfg=ops_cfg, allow_noncritical=False,
                clock=Clock("2026-10-26T08:30:00+08:00"))
    st = {s["source"]: s["status"] for s in r["sources"]}
    assert st["etf_holdings"] == "SKIPPED" and st["mops_material_info"] == "SKIPPED"
    assert st["twse_prices"] == "OK" and r["level"] == PASS


def test_first_seen_ledger_append_only_and_pit(tmp_path):
    led = tmp_path / "fs.parquet"
    obs = [{"ticker": "2330", "year": 2026, "month": 9, "revenue": 100.0}]
    assert append_first_seen(obs, led, "2026-10-05T20:00:00+08:00", "t") == 1
    assert append_first_seen(obs + [{"ticker": "2317", "year": 2026, "month": 9, "revenue": 5.0}], led,
                             "2026-10-06T20:00:00+08:00", "t") == 1
    df = first_seen_available(led, "2026-10-05T23:59:59+08:00")
    assert list(df["ticker"]) == ["2330"]                      # 2317 first seen later -> invisible
    full = first_seen_available(led, "2026-10-07T00:00:00+08:00")
    assert full.set_index("ticker").loc["2330", "first_seen_at"] == "2026-10-05T20:00:00+08:00"   # never rewritten


# ----------------------------------------------------------------------------- deadline guard
@pytest.mark.parametrize("now,phase", [("2026-10-25T20:00", "NORMAL"), ("2026-10-26T08:30", "RESTRICTED"),
                                       ("2026-10-26T08:42", "NO_LLM"), ("2026-10-26T08:47", "PACKAGE_ONLY"),
                                       ("2026-10-26T08:56", "PAST_CUTOFF")])
def test_deadline_phases(ops_cfg, now, phase):
    s = DL.status(T1, Clock(now + ":00+08:00"), ops_cfg)
    assert s.phase == phase
    assert s.allow_llm == (phase in ("NORMAL", "RESTRICTED"))
    assert s.allow_noncritical_refresh == (phase == "NORMAL")


# ----------------------------------------------------------------------------- preflight
def test_preflight_git_dirty_blocks_only_competition(ops_cfg, fixture_store):
    kw = dict(ops_cfg=ops_cfg, clock=Clock("2026-10-25T20:00:00+08:00"), store=fixture_store,
              settlement_status={"previous_available": True, "initial_day": True})
    comp = run_preflight(T1, mode="competition", git=DIRTY_GIT, **kw)
    dry = run_preflight(T1, mode="dry-run", git=DIRTY_GIT, **kw)
    lv = lambda r, n: next(c["level"] for c in r["checks"] if c["name"] == n)  # noqa: E731
    assert lv(comp, "git_clean") == BLOCK and comp["level"] == BLOCK
    assert lv(dry, "git_clean") == WARN
    assert lv(run_preflight(T1, mode="competition", git=CLEAN_GIT, **kw), "strategy_freeze") == PASS


def test_preflight_settlement_rules(ops_cfg, fixture_store):
    kw = dict(ops_cfg=ops_cfg, clock=Clock("2026-10-25T20:00:00+08:00"), store=fixture_store, git=CLEAN_GIT)
    lv = lambda r, n: next(c["level"] for c in r["checks"] if c["name"] == n)  # noqa: E731
    r = run_preflight(T1, mode="competition", settlement_status={"previous_available": False}, **kw)
    assert lv(r, "settlement_available") == BLOCK
    r = run_preflight(T1, mode="competition", settlement_status={"previous_available": True,
                                                                  "reconciliation": "BLOCK"}, **kw)
    assert lv(r, "settlement_reconciled") == BLOCK
    r = run_preflight(T1, mode="competition", settlement_status={"previous_available": True,
                                                                  "reconciliation": "UNAVAILABLE"}, **kw)
    assert lv(r, "settlement_reconciled") == BLOCK           # competition requires official settlement
    r = run_preflight(T1, mode="dry-run", settlement_status={"previous_available": True,
                                                              "reconciliation": "UNAVAILABLE"}, **kw)
    assert lv(r, "settlement_reconciled") == WARN


def test_previous_portfolio_cash_drift_detected(rb):
    closes = {t: Decimal(100) for t in list(rb.universe)[:22]}
    holdings = {t: 1000 * 10 for t in closes}               # 22 names × 1,000,000 = 22M
    c = previous_portfolio_check(holdings, Decimal(12_000_000), closes, rb)   # cash 35% > 25%
    assert c.level == WARN and "must rebalance" in c.detail
    ok = previous_portfolio_check(holdings, Decimal(2_000_000), closes, rb)
    assert ok.level in (PASS, WARN) and "must rebalance" not in ok.detail
    miss = previous_portfolio_check({"9999": 1000}, Decimal(1), {}, rb)
    assert miss.level == BLOCK


# ----------------------------------------------------------------------------- package / FINAL / archive
@pytest.fixture(scope="module")
def day1(fixture_store, rb, tmp_path_factory):
    from agent.config import load_strategy
    cal = TradingCalendar(fixture_store.dates())
    s0 = Settlement.initial(cal.prev(T1), rb.rules.initial_cash)
    d = tmp_path_factory.mktemp("d1")
    return run_day(T1, fixture_store, s0, rb, load_strategy("config/strategy_quant_v1.yaml"), team_id="TEAM_TEST",
                   out_dir=d / "o", log_dir=d / "l", store_is_fixture=True, calendar=cal)


def _pkg(day1, ops_cfg, run_id="r1", team="TEAM_TEST", date=T1, r=None):
    return build_package(r or day1, team_id=team, trade_date=date, run_id=run_id, mode="competition", data_health=None,
                         reconciliation=None, preflight=None, run_metadata={"git_sha": "git:test"}, ops_cfg=ops_cfg,
                         extra_json={"agent_state.json": day1.agent_state})


def test_package_contents_and_manifest(day1, ops_cfg):
    assert day1.validation.ok
    p = _pkg(day1, ops_cfg)
    names = {x.name for x in p.iterdir()}
    assert {f"D-Plan_TEAM_TEST_{T1}.json", "validation_report.json", "validation_report.md", "portfolio.csv",
            "orders.csv", "facts.json", "sources_manifest.json", "data_health.json", "reconciliation.json",
            "run_metadata.json", "README.txt", "manifest.json", "agent_state.json"} <= names
    m = json.loads((p / "manifest.json").read_text(encoding="utf-8"))
    assert all({"filename", "sha256", "size", "created_at"} <= set(f) for f in m["files"])
    assert verify_package(p) == []
    meta = json.loads((p / "run_metadata.json").read_text(encoding="utf-8"))
    assert meta["dplan_sha256"] == sha256_file(p / f"D-Plan_TEAM_TEST_{T1}.json")
    with pytest.raises(FileExistsError):
        _pkg(day1, ops_cfg)                                   # immutable: same run_id refused
    (p / "orders.csv").write_text("tampered", encoding="utf-8")
    assert verify_package(p) == ["hash mismatch orders.csv"]


def test_final_candidate_single_and_conspicuous(day1, ops_cfg):
    a = mark_final(_pkg(day1, ops_cfg, "r1"), team_id="TEAM_TEST", trade_date=T1, mode="competition", ops_cfg=ops_cfg)
    kept = mark_final(_pkg(day1, ops_cfg, "r2"), team_id="TEAM_TEST", trade_date=T1, mode="competition", ops_cfg=ops_cfg)
    assert not kept["ok"] and kept["kept"]                     # frozen: never replaced silently
    p2 = Path(ops_cfg["paths"]["submissions_dir"]) / "20261026" / "candidates" / "r2"
    assert not mark_final(p2, team_id="TEAM_TEST", trade_date=T1, mode="competition", ops_cfg=ops_cfg,
                          replace=True, reason="")["ok"]                # replacement needs operator + reason
    b = mark_final(p2, team_id="TEAM_TEST", trade_date=T1, mode="competition", ops_cfg=ops_cfg, replace=True,
                   reason="test replacement", operator="operator A")
    assert a["ok"] and b["ok"] and b["event"] == "REPLACED" and b["old_sha256"] == a["sha256"]
    day = Path(ops_cfg["paths"]["submissions_dir"]) / "20261026"
    assert [x.name for x in (day / "FINAL").glob("*.json")] == [f"D-Plan_TEAM_TEST_{T1}.json"]
    txt = (day / "FINAL_CANDIDATE.txt").read_text(encoding="utf-8")
    assert b["sha256"] in txt and "TEAM_TEST" in txt and T1 in txt and "VALIDATION       : PASS" in txt
    assert "UPLOAD THIS FILE" in txt and "DRY-RUN" not in txt
    assert "RUN ID           : r2" in txt
    events = [json.loads(x)["event"] for x in (day / "final_history.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events == ["MARKED", "REFUSED_FROZEN", "REPLACED"]          # nothing deleted
    assert json.loads((day / "FINAL_FREEZE.json").read_text(encoding="utf-8"))["operator"] == "operator A"


def test_final_refused_for_wrong_team_date_hash_or_invalid(day1, ops_cfg):
    day = Path(ops_cfg["paths"]["submissions_dir"]) / "20261026"
    p = _pkg(day1, ops_cfg, "w1")
    assert not mark_final(p, team_id="TEAM_OTHER", trade_date=T1, mode="competition", ops_cfg=ops_cfg)["ok"]
    assert not mark_final(p, team_id="TEAM_TEST", trade_date="2026-10-27", mode="competition", ops_cfg=ops_cfg)["ok"]
    f = p / f"D-Plan_TEAM_TEST_{T1}.json"
    f.write_text(f.read_text(encoding="utf-8").replace('"orders"', '"orders" ', 1), encoding="utf-8")
    bad = mark_final(p, team_id="TEAM_TEST", trade_date=T1, mode="competition", ops_cfg=ops_cfg)
    assert not bad["ok"] and any("hash" in r for r in bad["reasons"])

    class FailVal:
        ok = False

        def to_dict(self):
            return {"ok": False, "summary": {"FAIL": 1}, "checks": [{"status": "FAIL", "rule_id": "C1", "message": "x"}]}
    inv = _pkg(day1, ops_cfg, "w2", r=dataclasses.replace(day1, validation=FailVal()))
    res = mark_final(inv, team_id="TEAM_TEST", trade_date=T1, mode="competition", ops_cfg=ops_cfg)
    assert not res["ok"] and "validation FAIL" in res["reasons"]
    assert not (day / "FINAL").exists() and not (day / "FINAL_CANDIDATE.txt").exists()


def test_archive_immutable_with_manifest(day1, ops_cfg):
    from datetime import datetime
    p = _pkg(day1, ops_cfg, "a1")
    rid = run_id_for(datetime(2026, 10, 25, 20, 0, 1), "git:abc1234")
    assert rid == "20261025_200001_gitabc1234"
    a = archive_run(T1, rid, package_dir=p, config_files=["config/strategy_quant_v1.yaml"], ops_cfg=ops_cfg,
                    readonly=False)
    m = json.loads((a / "ARCHIVE_MANIFEST.json").read_text(encoding="utf-8"))
    for f in m["files"]:
        assert sha256_file(a / f["path"]) == f["sha256"]
    assert (a / "config" / "strategy_quant_v1.yaml").exists()
    with pytest.raises(FileExistsError):
        archive_run(T1, rid, package_dir=p, config_files=[], ops_cfg=ops_cfg, readonly=False)


def test_refresh_observation_times_use_wall_clock_not_simulated_clock(ops_cfg, fixture_store):
    """Round 05 dry-run B finding: a simulated (past) clock must never become an observation timestamp."""
    seen = {}

    def f(ctx):
        seen["wall"] = ctx["wall"].now().isoformat()
        return {"records": 1, "latest_available_date": "2026-10-23"}
    r = refresh(T1, store=fixture_store, fetchers={"twse_prices": f}, ops_cfg=ops_cfg,
                clock=Clock("2026-10-25T20:00:00+08:00"), wall_clock=Clock("2026-10-26T12:00:00+08:00"))
    st = next(s for s in r["sources"] if s["source"] == "twse_prices")
    assert st["fetched_at"].startswith("2026-10-26T12:00") and seen["wall"].startswith("2026-10-26T12:00")


def test_staleness_is_holiday_aware():
    """Round 06 rehearsal finding: 2026-09-25 and 09-28 were market holidays; 09-29's T-1 is 09-24."""
    from agent.ops.refresh_daily import expected_prev_trading_day, trading_lag
    closures = {"2026-09-25", "2026-09-28"}
    assert expected_prev_trading_day("2026-09-29", closures) == "2026-09-24"
    assert trading_lag("2026-09-24", "2026-09-24", closures) == 0
    assert trading_lag("2026-09-23", "2026-09-24", closures) == 1
    assert expected_prev_trading_day("2026-09-29", set()) == "2026-09-28"     # unknown holiday -> conservative


def test_refresh_after_holiday_not_stale(ops_cfg, fixture_store):
    import copy
    cfg = copy.deepcopy(ops_cfg)
    cfg["market_holidays"] = ["2026-10-23"]                    # configured official holiday on T-1
    r = refresh(T1, store=fixture_store, fetchers=_fake(latest="2026-10-22"), ops_cfg=cfg, clock=Clock("2026-10-25T20:00:00+08:00"))
    assert r["level"] == PASS
    r2 = refresh(T1, store=fixture_store, fetchers=_fake(latest="2026-10-22"), ops_cfg=ops_cfg, clock=Clock("2026-10-25T20:00:00+08:00"))
    assert r2["level"] == BLOCK                                # not a known closure -> T-1 prices stale
