"""Cross-day catch-up, 08:30 decision cutoff, 08:55 official close, deadline warnings, evidence-based submission
status, receipts and the browser-open-only portal helper (2026-10-20 operational round)."""
import json
from datetime import datetime
from pathlib import Path

import pytest

from agent.ops import scheduled_run as S
from agent.ops import submission_window as SW
from agent.ops.common import TPE
from agent.submission import status as ST
from agent.submission.portal import open_submission_portal
from agent.submission.receipt import Receipt, record_receipt
from tests.ops.test_competition_day import CLK1, T1, T2, run
from tests.ops.test_p1_p2_p5 import partial_store

HOL = {"2026-10-09", "2026-10-26"}


@pytest.fixture(autouse=True)
def _release_ops_loggers():
    """ops_logger caches one FileHandler per (name, date); drop them so later tests log into their own tmp dirs."""
    yield
    import logging
    for name, lg in list(logging.Logger.manager.loggerDict.items()):
        if name.startswith("ops.") and isinstance(lg, logging.Logger):
            for h in list(lg.handlers):
                h.close()
                lg.removeHandler(h)
            del logging.Logger.manager.loggerDict[name]       # next ops_logger() call builds a fresh logger


def at(s):
    return datetime.fromisoformat(s + "+08:00")


# ---------------------------------------------------------------- 1-9: trade-date / window planning (pure)
@pytest.mark.parametrize("now,action,reason,trade,kind", [
    ("2026-10-19T19:30:00", "RUN", None, "2026-10-20", "NORMAL"),                         # 1 normal 19:30
    ("2026-10-19T23:00:00", "RUN", None, "2026-10-20", "SAME_DAY_CATCHUP"),               # 2 23:00 catch-up
    ("2026-10-20T07:30:00", "RUN", None, "2026-10-20", "CROSS_DAY_CATCHUP"),              # 3 next-morning boot
    ("2026-10-20T08:15:00", "RUN", None, "2026-10-20", "CROSS_DAY_CATCHUP"),              # 4 (+ high warning)
    ("2026-10-20T08:29:59", "RUN", None, "2026-10-20", "CROSS_DAY_CATCHUP"),              # 5 last decision second
    ("2026-10-20T08:30:00", "NO_DECISION", "DECISION_WINDOW_CLOSED", "2026-10-20", "CROSS_DAY_CATCHUP"),   # 6
    ("2026-10-20T08:45:00", "NO_DECISION", "DECISION_WINDOW_CLOSED", "2026-10-20", "CROSS_DAY_CATCHUP"),   # 7
    ("2026-10-20T08:55:00", "SKIP", "SUBMISSION_WINDOW_CLOSED", "2026-10-20", "CROSS_DAY_CATCHUP"),        # 8
    ("2026-10-17T07:30:00", "SKIP", "NO_TRADING_DAY", None, "NORMAL"),                    # 9 Saturday
    ("2026-10-16T19:31:00", "SKIP", "NO_SUBMISSION_WINDOW_TONIGHT", None, "NORMAL"),      # 9 Friday night
])
def test_plan_timeline(now, action, reason, trade, kind):
    p = S.plan(at(now), HOL)
    assert (p["action"], p["reason"], p["trade_date"], p["run_kind"]) == (action, reason, trade, kind)


def test_cross_day_catch_up_never_targets_yesterday():
    p = S.plan(at("2026-10-20T06:00:00"), HOL)
    assert p["scheduled_date"] == "2026-10-19" and p["trade_date"] == "2026-10-20"


@pytest.mark.parametrize("now,state,expected", [
    ("2026-10-20T07:59:59", "NOT_GENERATED", []),
    ("2026-10-20T08:00:00", "NOT_GENERATED", ["SUBMISSION_WARNING_0800"]),
    ("2026-10-20T08:15:00", "VALIDATED", ["SUBMISSION_WARNING_0800", "SUBMISSION_HIGH_WARNING_0815"]),        # 4
    ("2026-10-20T08:15:00", "READY_FOR_UPLOAD", []),
    ("2026-10-20T08:45:00", "READY_FOR_UPLOAD", ["SUBMISSION_CRITICAL_WARNING_0845"]),                       # 7
    ("2026-10-20T08:45:00", "NOT_GENERATED", ["SUBMISSION_WARNING_0800", "SUBMISSION_HIGH_WARNING_0815",
                                              "SUBMISSION_CRITICAL_WARNING_0845"]),
    ("2026-10-20T08:50:00", "ACCEPTED", []),
    ("2026-10-20T08:55:00", "NOT_GENERATED", []),                                     # window closed: state says so
])
def test_deadline_warnings(now, state, expected):
    assert SW.warnings("2026-10-20", at(now), state) == expected


def test_phases():
    assert SW.phase("2026-10-20", at("2026-10-19T19:29:59")) == "WINDOW_NOT_OPEN"
    assert SW.phase("2026-10-20", at("2026-10-19T19:30:00")) == "DECISION_OPEN"
    assert SW.phase("2026-10-20", at("2026-10-20T08:30:00")) == "DECISION_WINDOW_CLOSED"
    assert SW.phase("2026-10-20", at("2026-10-20T08:55:00")) == "SUBMISSION_WINDOW_CLOSED"


# ---------------------------------------------------------------- scheduler run(): no quant after the cutoff
@pytest.fixture
def sched(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "LOG_DIR", tmp_path)
    monkeypatch.setattr(S, "LATEST", tmp_path / "latest_status.json")
    monkeypatch.setattr(S, "HISTORY", tmp_path / "history.jsonl")
    monkeypatch.setattr(S, "holidays", lambda cfg=None: HOL)
    monkeypatch.setattr(S, "network_check", lambda *a, **k: (_ for _ in ()).throw(AssertionError("QUANT_STARTED")))
    return tmp_path


def _snap(state):
    return lambda d, now: {"state": state, "deadline_warnings": SW.warnings(d, now, state)}


def test_20261020_case_0854_is_decision_window_closed_no_quant(sched, monkeypatch):
    """Regression: scheduled 2026-10-19 19:30, machine started 2026-10-20 08:54:17 (was MISSED_PREVIOUS_DAY)."""
    monkeypatch.setattr(S, "submission_snapshot", _snap("NOT_GENERATED"))
    r = S.run(now=datetime(2026, 10, 20, 8, 54, 17, tzinfo=TPE))
    assert r["status"] == "SKIPPED" and r["blocked_reason"] == "DECISION_WINDOW_CLOSED"
    assert r["scheduled_date"] == "2026-10-19" and r["trade_date"] == "2026-10-20"
    assert r["run_kind"] == "CROSS_DAY_CATCHUP" and r["window_phase"] == "DECISION_WINDOW_CLOSED"
    assert r["submission_state"] == "NOT_GENERATED"
    assert "SUBMISSION_CRITICAL_WARNING_0845" in r["deadline_warnings"]


def test_0845_existing_candidate_is_reported_not_regenerated(sched, monkeypatch):            # 7
    monkeypatch.setattr(S, "submission_snapshot", _snap("READY_FOR_UPLOAD"))
    r = S.run(now=datetime(2026, 10, 20, 8, 45, tzinfo=TPE))
    assert r["blocked_reason"] == "DECISION_WINDOW_CLOSED" and r["submission_state"] == "READY_FOR_UPLOAD"
    assert r["deadline_warnings"] == ["SUBMISSION_CRITICAL_WARNING_0845"]


def test_0855_submission_window_closed(sched, monkeypatch):                                  # 8
    monkeypatch.setattr(S, "submission_snapshot", _snap("SUBMISSION_WINDOW_CLOSED"))
    r = S.run(now=datetime(2026, 10, 20, 8, 55, tzinfo=TPE))
    assert r["status"] == "SKIPPED" and r["blocked_reason"] == "SUBMISSION_WINDOW_CLOSED"


def test_accepted_submission_is_never_redecided(sched, monkeypatch):                          # 10
    monkeypatch.setattr(S, "submission_snapshot", _snap("ACCEPTED"))
    r = S.run(now=datetime(2026, 10, 20, 7, 30, tzinfo=TPE))
    assert r["status"] == "SKIPPED" and r["blocked_reason"] == "SUBMISSION_ALREADY_ACCEPTED"


def test_existing_final_is_not_reproduced_unless_safe_retry(sched, monkeypatch):              # 11
    monkeypatch.setattr(S, "submission_snapshot", _snap("READY_FOR_UPLOAD"))
    r = S.run(now=datetime(2026, 10, 20, 7, 30, tzinfo=TPE))
    assert r["status"] == "SKIPPED" and r["blocked_reason"].startswith("FINAL_ALREADY_EXISTS")
    with pytest.raises(AssertionError, match="QUANT_STARTED"):                                 # retry goes on
        S.run(now=datetime(2026, 10, 20, 7, 31, tzinfo=TPE), safe_retry=True)


def test_catch_up_in_competition_without_datapack_is_blocked(sched, monkeypatch):             # 12
    monkeypatch.setattr(S, "submission_snapshot", _snap("NOT_GENERATED"))
    monkeypatch.setattr(S, "network_check", lambda *a, **k: {"ok": True, "retries": 0, "detail": {}})
    monkeypatch.setattr(S, "claude_check", lambda: {"ready": False, "version": None, "version_check": None, "line": "x"})
    monkeypatch.setattr(S, "run_mode", lambda cfg=None: "COMPETITION")
    monkeypatch.setattr(S, "backfill_gaps", lambda *a, **k: [])
    import agent.ops.team as TEAM
    monkeypatch.setattr(TEAM, "resolve", lambda mode=None, cfg=None: {"status": "OK", "team_id": "TEAM_042",
                                                                     "source": "test", "configured_value": "TEAM_042"})
    r = S.run(now=datetime(2026, 10, 28, 7, 30, tzinfo=TPE))
    assert r["run_kind"] == "CROSS_DAY_CATCHUP" and r["trade_date"] == "2026-10-28"
    assert r["status"] == "BLOCKED" and r["blocked_reason"] == "DATAPACK_MISSING"


# ---------------------------------------------------------------- competition_day hard stops + catch-up gates
def test_competition_day_catch_up_before_0830_runs_for_today(fixture_store, ops_cfg):
    s = run(fixture_store, ops_cfg, T1, "2026-10-26T07:30:00+08:00", mode="dry-run", initial=True)
    assert s["status"] == "DRY_RUN_OK" and s["window_phase"] == "DECISION_OPEN" and s["trade_date"] == T1


@pytest.mark.parametrize("clock,status", [("2026-10-26T08:30:00+08:00", "DECISION_WINDOW_CLOSED"),
                                          ("2026-10-26T08:54:17+08:00", "DECISION_WINDOW_CLOSED"),
                                          ("2026-10-26T08:55:00+08:00", "SUBMISSION_WINDOW_CLOSED")])
def test_competition_day_refuses_new_decisions_after_cutoff(fixture_store, ops_cfg, clock, status):
    s = run(fixture_store, ops_cfg, T1, clock, initial=True)
    assert s["status"] == status and "final_file" not in s and "decisions" not in s


def test_catch_up_market_incomplete_blocks(fixture_store, ops_cfg, tmp_path):                  # 13
    st = partial_store(fixture_store, tmp_path / "p", T1, keep_market="TPEx")
    s = run(st, ops_cfg, T2, "2026-10-27T07:30:00+08:00", mode="dry-run", initial=True)
    assert s["status"] == "BLOCKED" and "MARKET_DATA_INCOMPLETE" in s["reason"]


def test_catch_up_active_share_unavailable_blocks_in_competition(fixture_store, ops_cfg):     # 14
    s = run(fixture_store, ops_cfg, T1, "2026-10-26T07:30:00+08:00", initial=True, data_faults={"etf"})
    assert s["status"] == "BLOCKED" and s["reason"].startswith("ACTIVE_SHARE_DATA_MISSING")


def test_competition_day_refuses_when_already_accepted(fixture_store, ops_cfg):                # 10
    from agent.submission.base import CONFIRMED, READY, set_state
    set_state(T1, READY, reason="test", cfg=ops_cfg)
    set_state(T1, CONFIRMED, reason="test receipt", cfg=ops_cfg)
    s = run(fixture_store, ops_cfg, T1, "2026-10-26T07:30:00+08:00", initial=True)
    assert s["status"] == "BLOCKED" and s["reason"].startswith("SUBMISSION_ALREADY_ACCEPTED")


# ---------------------------------------------------------------- submission status (evidence only)
def test_status_not_generated(ops_cfg):
    r = ST.compute(T1, now=at("2026-10-26T07:00:00"), ops_cfg=ops_cfg)
    assert r["state"] == "NOT_GENERATED" and r["uploadable"] is False


def test_status_lifecycle_ready_uploaded_accepted(fixture_store, ops_cfg):
    s = run(fixture_store, ops_cfg, T1, CLK1, initial=True)                 # competition FINAL
    assert s["status"] == "READY_TO_SUBMIT"
    now = at("2026-10-26T08:10:00")
    r = ST.compute(T1, now=now, ops_cfg=ops_cfg)
    assert r["state"] == "READY_FOR_UPLOAD" and r["uploadable"] and r["sha256"] == s["sha256"]
    assert r["generated_at"] and r["validated_at"] and r["accepted_at"] is None   # READY is not ACCEPTED
    record_receipt(Receipt(T1, "TEAM_TEST", s["sha256"], "2026-10-26T08:12:00+08:00", "manual_web", "op",
                           official_status="pending"), ops_cfg)
    r = ST.compute(T1, now=now, ops_cfg=ops_cfg)
    assert r["state"] == "UPLOADED" and r["uploaded_at"].startswith("2026-10-26T08:12") and r["accepted_at"] is None
    record_receipt(Receipt(T1, "TEAM_TEST", s["sha256"], "2026-10-26T08:14:00+08:00", "manual_web", "op",
                           official_receipt_id="R-1", official_status="accepted",
                           accepted_at="2026-10-26T08:14:30+08:00", evidence_files=["receipt.png"]), ops_cfg)
    r = ST.compute(T1, now=at("2026-10-26T09:00:00"), ops_cfg=ops_cfg)
    assert r["state"] == "ACCEPTED" and r["submission_id"] == "R-1" and r["accepted_at"] == "2026-10-26T08:14:30+08:00"


def test_status_rejected_and_window_closed(fixture_store, ops_cfg):
    s = run(fixture_store, ops_cfg, T1, CLK1, initial=True)
    assert ST.compute(T1, now=at("2026-10-26T08:56:00"), ops_cfg=ops_cfg)["state"] == "SUBMISSION_WINDOW_CLOSED"
    record_receipt(Receipt(T1, "TEAM_TEST", s["sha256"], "2026-10-26T08:20:00+08:00", "manual_web", "op",
                           official_status="rejected", failure_reason="C6 timestamp"), ops_cfg)
    r = ST.compute(T1, now=at("2026-10-26T08:30:00"), ops_cfg=ops_cfg)
    assert r["state"] == "REJECTED" and r["failure_reason"] == "C6 timestamp"


def test_status_ui_unavailable_and_dry_run_not_uploadable(fixture_store, ops_cfg):
    run(fixture_store, ops_cfg, T1, CLK1, mode="dry-run", initial=True)
    r = ST.compute(T1, now=at("2026-10-26T08:00:00"), ops_cfg=ops_cfg)
    assert r["state"] == "READY_FOR_UPLOAD" and r["uploadable"] is False          # paper FINAL: never uploadable
    cfg = dict(ops_cfg, submission={"ui_status": "UNAVAILABLE"})
    assert ST.compute(T1, now=at("2026-10-26T08:00:00"), ops_cfg=cfg)["state"] == "SUBMISSION_UI_UNAVAILABLE"


# ---------------------------------------------------------------- portal: browser-open only
def test_portal_url_not_configured(ops_cfg):
    r = open_submission_portal(T1, ops_cfg=ops_cfg, now=at("2026-10-26T08:00:00"), opener=lambda u: 1 / 0)
    assert r["opened"] is False and r["result"] == "SUBMISSION_PORTAL_URL_NOT_CONFIGURED"
    assert r["SUBMISSION_UI_STATUS"] in ("NOT_YET_VERIFIED", "LOGIN_REQUIRED") and r["auto_upload"].startswith("DISABLED")


def test_portal_opens_only_for_a_competition_final(fixture_store, ops_cfg):
    cfg = dict(ops_cfg, submission={"portal_url": "https://example.invalid/backoffice", "ui_status": "AVAILABLE"})
    opened = []
    r = open_submission_portal(T1, ops_cfg=cfg, now=at("2026-10-26T08:00:00"), opener=opened.append)
    assert not r["opened"] and r["result"].startswith("NOT_READY_FOR_UPLOAD") and not opened
    run(fixture_store, ops_cfg, T1, CLK1, initial=True)
    r = open_submission_portal(T1, ops_cfg=cfg, now=at("2026-10-26T08:00:00"), opener=opened.append)
    assert r["opened"] and opened == ["https://example.invalid/backoffice"]


def test_no_upload_login_or_credential_code():
    root = Path(__file__).resolve().parents[2] / "agent" / "submission"
    src = "\n".join(p.read_text(encoding="utf-8") for p in root.glob("*.py"))
    # network / browser-automation / cookie-store code (official_test.py only REFUSES credential-like text)
    for bad in ("import requests", "import urllib", "urlopen(", ".post(", "selenium", "playwright", "pyautogui",
                "http.cookiejar", "browser_cookie", "import http.client", "sqlite3"):
        assert bad not in src.lower(), bad
    from agent.submission.future_api import PORTAL_STATUS, OfficialPortalProvider
    assert PORTAL_STATUS == "DISABLED_PENDING_OFFICIAL_PORTAL_VALIDATION"
    with pytest.raises(NotImplementedError):
        OfficialPortalProvider().submit({})
