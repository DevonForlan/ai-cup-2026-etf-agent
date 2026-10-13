"""Round 08: prediction summary, next-day evaluation (date matching, no cross-day replay, missing data,
BLOCKED handling, duplicate protection, NAV reconciliation, chain integrity), scheduler gap / chain helpers."""
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from agent.ops import daily_evaluation as DE
from agent.ops import scheduled_run as S
from agent.ops.common import TPE, sha256_file
from agent.ops.prediction_summary import build as build_prediction
from tests.ops.conftest import store_without_date
from tests.ops.test_competition_day import CLK1, T1, run

HOL = {"2026-10-09", "2026-10-26"}


def at(s):
    return datetime.fromisoformat(s + "+08:00")


@pytest.fixture
def predicted(fixture_store, ops_cfg, tmp_path):
    s = run(fixture_store, ops_cfg, T1, CLK1, mode="dry-run", initial=True)
    assert s["status"] == "DRY_RUN_OK"
    return s, DE.Paths(ledger=tmp_path / "ledger", reports=tmp_path / "rep", logs=tmp_path / "logs")


# ---------------------------------------------------------------- prediction summary
def test_prediction_summary_is_labelled_readable_and_not_a_dplan(predicted, ops_cfg, tmp_path):
    s, _ = predicted
    p = build_prediction(T1, ops_cfg=ops_cfg, run_summary=s, out_dir=tmp_path / "pred")
    txt = p.read_text(encoding="utf-8")
    assert p.name == f"{T1}_prediction.md" and "PRECOMPETITION_PAPER_RUN" in txt and "不是正式 D-Plan" in txt
    for sec in ("## Portfolio", "## Holdings", "## Orders", "## Quant", "## Claude", "## D-Plan", "## Overall"):
        assert sec in txt
    assert txt.count("| BUY |") >= 20 and "Version: 4.3" in txt and "**READY**" in txt


# ---------------------------------------------------------------- evaluation
def test_evaluation_pass_nav_reconciliation_and_report(predicted, ops_cfg, fixture_store):
    _, paths = predicted
    final = Path(ops_cfg["paths"]["submissions_dir"]) / "20261026" / "FINAL" / f"D-Plan_TEAM_TEST_{T1}.json"
    before = sha256_file(final)
    r = DE.evaluate(T1, ops_cfg=ops_cfg, store=fixture_store, paths=paths)
    assert r["status"] == "PASS" and r["settlement"] == "PASS" and r["return_attribution_check"] == "PASS"
    assert r["start_source"] == "INITIAL_CASH" and r["evaluation_date"] == T1 and r["dplan_version"] == "4.3"
    assert paths.settlement(T1).exists() and Path(r["report_file"]).exists()
    txt = Path(r["report_file"]).read_text(encoding="utf-8")
    assert "PRECOMPETITION_PAPER_RUN" in txt and "diagnostic only" in txt and "Largest negative contributors" in txt
    for k in ("nav", "daily_return", "cumulative_return", "mdd", "turnover", "fees", "tax", "cash_weight",
              "holding_count", "active_share", "compliance"):
        assert k in r
    assert sha256_file(final) == before                      # evaluation never changes the decision
    assert DE.evaluate(T1, ops_cfg=ops_cfg, store=fixture_store, paths=paths)["status"] == "PASS"   # no history yet


def test_duplicate_run_protection(predicted, monkeypatch, ops_cfg, fixture_store):
    _, paths = predicted
    monkeypatch.setattr(DE, "load_ops_config", lambda *a, **k: ops_cfg)
    from agent.data import loaders
    monkeypatch.setattr(loaders, "HistoryStore", lambda *a, **k: fixture_store)
    r1 = DE.run(ev_date=T1, paths=paths)
    r2 = DE.run(ev_date=T1, paths=paths)
    assert r1["status"] == "PASS" and r2["status"] == "SKIPPED" and r2["blocked_reason"] == "SKIP_ALREADY_PASSED"
    latest = json.loads(paths.latest.read_text(encoding="utf-8"))
    assert latest["label"] == "PRECOMPETITION_PAPER_RUN" and latest["status"] == "SKIPPED"
    assert DE.check(at("2026-10-26T18:00:00"), paths)["recommended_action"] == "NONE"


def test_missing_market_data_is_blocked_not_guessed(predicted, ops_cfg, fixture_store, tmp_path):
    _, paths = predicted
    st = store_without_date(fixture_store, tmp_path / "st", T1)
    r = DE.evaluate(T1, ops_cfg=ops_cfg, store=st, paths=paths)
    assert r["status"] == "BLOCKED" and r["blocked_reason"] == "MARKET_DATA_NOT_AVAILABLE"
    assert not paths.settlement(T1).exists()


def test_chain_mismatch_blocks(predicted, ops_cfg, fixture_store):
    _, paths = predicted
    from agent.ops.package_submission import active_final
    rec = active_final(T1, ops_cfg)
    meta_p = Path(ops_cfg["paths"]["submissions_dir"]) / "20261026" / "candidates" / rec["run_id"] / "run_metadata.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    meta["settlement_hash"] = "sha256:" + "0" * 64            # prediction built from an unknown starting point
    meta_p.write_text(json.dumps(meta), encoding="utf-8")
    r = DE.evaluate(T1, ops_cfg=ops_cfg, store=fixture_store, paths=paths)
    assert r["status"] == "BLOCKED" and r["blocked_reason"] == "SETTLEMENT_CHAIN_MISMATCH"


def test_no_prediction_is_skipped(ops_cfg, fixture_store, tmp_path):
    r = DE.evaluate(T1, ops_cfg=ops_cfg, store=fixture_store, paths=DE.Paths(tmp_path / "l", tmp_path / "r", tmp_path / "g"))
    assert r["status"] == "SKIPPED" and r["blocked_reason"] == "NO_PREDICTION_FOR_DATE"


def test_concurrent_evaluation_is_skipped(tmp_path):
    paths = DE.Paths(tmp_path / "l", tmp_path / "r", tmp_path / "g")
    paths.logs.mkdir(parents=True)
    (paths.logs / "evaluation.lock").write_text("busy", encoding="utf-8")
    r = DE.run(ev_date="2026-10-14", paths=paths)
    assert r["status"] == "SKIPPED" and r["blocked_reason"] == "ANOTHER_EVALUATION_RUNNING"


# ---------------------------------------------------------------- date matching / no cross-day replay
def test_evaluation_dates():
    p = DE.plan(at("2026-10-14T17:00:00"), HOL)
    assert p["action"] == "RUN" and p["evaluation_date"] == "2026-10-14"
    assert DE.plan(at("2026-10-14T22:30:00"), HOL)["evaluation_date"] == "2026-10-14"            # same-day catch-up
    m = DE.plan(at("2026-10-15T00:30:00"), HOL)
    assert m["action"] == "SKIP" and m["reason"] == "MISSED_PREVIOUS_DAY"                          # no cross-day replay
    assert DE.plan(at("2026-10-17T17:05:00"), HOL)["reason"] == "NO_TRADING_DAY"                   # Saturday
    assert DE.plan(at("2026-10-26T17:05:00"), HOL)["reason"] == "NO_TRADING_DAY"                   # market closed


def test_check_reports_missed(tmp_path):
    paths = DE.Paths(tmp_path / "l", tmp_path / "r", tmp_path / "g")
    c = DE.check(at("2026-10-14T18:00:00"), paths)
    assert c["status"] == "MISSED" and c["recommended_action"] == "MANUAL_RERUN_RECOMMENDED"


# ---------------------------------------------------------------- scheduler helpers
def test_gap_detection_and_trading_day_navigation():
    stored = {"2026-10-01", "2026-10-02", "2026-10-05", "2026-10-12", "2026-10-13"}
    assert S.missing_trading_days("2026-10-14", stored, HOL) == ["2026-10-06", "2026-10-07", "2026-10-08"]
    assert S.prev_trading_day(date(2026, 10, 12), HOL) == date(2026, 10, 8)
    assert S.next_trading_day(date(2026, 10, 8), HOL) == date(2026, 10, 12)
    assert S.next_trading_day(date(2026, 10, 23), HOL) == date(2026, 10, 27)


def test_paper_start_chain_or_reset(tmp_path, monkeypatch):
    paths = DE.Paths(tmp_path / "ledger", tmp_path / "rep", tmp_path / "logs")
    monkeypatch.setattr(DE, "Paths", lambda *a, **k: paths)
    monkeypatch.setattr(S, "holidays", lambda cfg=None: HOL)
    from agent.ops import package_submission
    monkeypatch.setattr(package_submission, "active_final", lambda *a, **k: None)
    log = S.RunLog.__new__(S.RunLog)
    log.path = tmp_path / "x.log"
    assert S.paper_start("2026-10-14", log)["source"].startswith("RESET_INITIAL")
    paths.settlement("2026-10-13").parent.mkdir(parents=True)
    paths.settlement("2026-10-13").write_text("{}", encoding="utf-8")
    st = S.paper_start("2026-10-14", log)
    assert st["source"] == "CHAIN:2026-10-13" and st["ledger"] == str(paths.ledger)
