"""Issue #4 — official portal binding, refined submission lifecycle, sealed-test D-Plan preparation and the guarded
(fail-closed) automated upload. All driver interaction is a fake: nothing here touches the real portal."""
import json
from datetime import datetime
from pathlib import Path

import pytest

from agent.ops.common import TPE, Clock, load_ops_config
from agent.submission import auto_upload as AU
from agent.submission import official_test as OT
from agent.submission import status as ST
from agent.submission.receipt import Receipt, record_receipt
from tests.ops.conftest import CLEAN_GIT
from tests.ops.test_competition_day import CLK1, T1, run

TEAM = "TEAM_11442"


@pytest.fixture(autouse=True)
def _release_ops_loggers():
    yield
    import logging
    for name, lg in list(logging.Logger.manager.loggerDict.items()):
        if name.startswith("ops.") and isinstance(lg, logging.Logger):
            for h in list(lg.handlers):
                h.close()
                lg.removeHandler(h)
            del logging.Logger.manager.loggerDict[name]


def at(s):
    return datetime.fromisoformat(s + "+08:00")


@pytest.fixture
def cfg(ops_cfg, tmp_path):
    c = dict(ops_cfg)
    c["submission"] = dict(c.get("submission") or {}, official_test_reports_dir=str(tmp_path / "rep"),
                           official_test_receipts_dir=str(tmp_path / "rcpt"),
                           official_test_datapack_dir=str(tmp_path / "dp"))
    c["auto_upload"] = {"enabled": True, "method": "browser", "max_automated_attempts": 3,
                        "selectors": {}, "accepted_markers": ["已收件"]}
    c["team"] = {"competition_team_id": TEAM, "precompetition_team_id": "TEAM_TEST"}
    return c


def make_file(tmp_path, team=TEAM, date=T1, name=None, pad=0):
    doc = {"schema_version": "4.3", "team_id": team, "trade_date": date, "orders": [], "decisions": [], "pad": "x" * pad}
    f = tmp_path / (name or f"D-Plan_{team}_{date}.json")
    f.write_text(json.dumps(doc), encoding="utf-8")
    from agent.ops.common import sha256_file
    return f, sha256_file(f)


def cand(tmp_path, *, team=TEAM, date=T1, name=None, pad=0, state="READY_FOR_UPLOAD", ok=True,
         source="official_test_package", mode="dry-run"):
    f, h = make_file(tmp_path, team, date, name, pad)
    return AU.Candidate(date, team, f, h, state, ok, source, mode)


class FakeDriver:
    def __init__(self, *, session="LOGGED_IN", date=T1, team=TEAM, history=None, after_submit_history=None,
                 attempts=25, validation=("PASS", "檢核通過"), submit_raises=None, upload_raises=None):
        self.session, self.date, self.team = session, date, team
        self._hist, self._after = history or [], after_submit_history
        self.attempts, self.validation = attempts, validation
        self.submit_raises, self.upload_raises = submit_raises, upload_raises
        self.calls = []

    def session_state(self):
        return self.session

    def open_submission_page(self):
        self.calls.append("open")

    def shown_trade_date(self):
        return self.date

    def shown_team_id(self):
        return self.team

    def history(self):
        return self._after if ("submit" in self.calls and self._after is not None) else self._hist

    def attempts_remaining(self):
        return self.attempts

    def upload(self, f):
        self.calls.append("upload")
        if self.upload_raises:
            raise self.upload_raises

    def validation_result(self):
        return self.validation

    def submit(self):
        self.calls.append("submit")
        if self.submit_raises:
            raise self.submit_raises
        return "已送出"


def go(c, drv, cfg, *, now="2026-10-26T07:00:00", official_test=True, used=0, e2e=True, run_mode="PRECOMPETITION",
       rec=None):
    rec = rec if rec is not None else []
    o = AU.run(c, drv, now_fn=lambda: at(now), ops_cfg=cfg, run_mode=run_mode, official_test=official_test,
               attempts_used=used, manual_e2e_done=e2e, record=lambda stage, **kw: rec.append((stage, kw)))
    return o, rec


# ---------------------------------------------------------------- 1-2 config binding
def test_team_and_portal_bound_in_ops_config():
    ops = load_ops_config()
    assert ops["team"]["competition_team_id"] == TEAM
    assert ops["submission"]["portal_url"] == "https://fundaiagent.esun-ai-challenge.tw/docs"
    assert ops["submission"]["ui_status"] == "AVAILABLE" and ops["submission"]["max_upload_bytes"] == 2097152
    assert ops["auto_upload"]["enabled"] is False and ops["auto_upload"]["accepted_markers"] == []   # off by default


# ---------------------------------------------------------------- 3-6 lifecycle from evidence (competition receipts)
def _receipt(sha, stage, status="pending", **kw):
    return Receipt(T1, "TEAM_TEST", sha, "2026-10-26T08:05:00+08:00", "browser_automation", "auto", official_status=status,
                   stage=stage, **kw)


def test_lifecycle_file_uploaded_server_validated_submitted_accepted(fixture_store, ops_cfg):
    s = run(fixture_store, ops_cfg, T1, CLK1, initial=True)
    sha, now = s["sha256"], at("2026-10-26T08:10:00")
    record_receipt(_receipt(sha, "file_uploaded"), ops_cfg)
    assert ST.compute(T1, now=now, ops_cfg=ops_cfg)["state"] == "FILE_UPLOADED"                       # 3
    record_receipt(_receipt(sha, "server_validated", server_validation_result="UNKNOWN"), ops_cfg)
    assert ST.compute(T1, now=now, ops_cfg=ops_cfg)["state"] == "FILE_UPLOADED"       # not explicit PASS
    record_receipt(_receipt(sha, "server_validated", server_validation_result="PASS"), ops_cfg)
    assert ST.compute(T1, now=now, ops_cfg=ops_cfg)["state"] == "SERVER_VALIDATED"                    # 4
    record_receipt(_receipt(sha, "submitted", server_validation_result="PASS"), ops_cfg)
    r = ST.compute(T1, now=now, ops_cfg=ops_cfg)
    assert r["state"] == "SUBMITTED" and r["accepted_at"] is None                                     # 5
    record_receipt(_receipt(sha, "accepted", "accepted"), ops_cfg)                     # accepted wording, NO evidence
    assert ST.compute(T1, now=now, ops_cfg=ops_cfg)["state"] == "SUBMITTED"                           # 6
    record_receipt(_receipt(sha, "accepted", "accepted", history_entry="2026-10-26 08:06 D-Plan 已收件"), ops_cfg)
    r = ST.compute(T1, now=at("2026-10-26T09:00:00"), ops_cfg=ops_cfg)
    assert r["state"] == "ACCEPTED" and r["state"] != "SUBMISSION_WINDOW_CLOSED"


def test_accepted_then_later_rejected_keeps_accepted(fixture_store, ops_cfg):                     # 10
    s = run(fixture_store, ops_cfg, T1, CLK1, initial=True)
    record_receipt(_receipt(s["sha256"], "accepted", "accepted", official_receipt_id="R-1"), ops_cfg)
    r = record_receipt(_receipt(s["sha256"], "rejected", "rejected", server_validation_result="FAIL"), ops_cfg)
    assert r["state"] == "SUBMISSION_CONFIRMED"
    st = ST.compute(T1, now=at("2026-10-26T08:40:00"), ops_cfg=ops_cfg)
    assert st["state"] == "ACCEPTED" and st["submission_id"] == "R-1" and st["last_upload_is_effective"] is False


# ---------------------------------------------------------------- 7-9, 18-20 runner behaviour
def test_happy_path_reaches_accepted_only_with_history_marker(cfg, tmp_path):
    hist = [{"filename": f"D-Plan_{TEAM}_{T1}.json", "status_text": "已收件", "text": "08:06 D-Plan_TEAM_11442 已收件"}]
    o, rec = go(cand(tmp_path), FakeDriver(after_submit_history=hist), cfg)
    assert o.status == "ACCEPTED" and [r[0] for r in rec] == ["file_uploaded", "server_validated", "submitted", "accepted"]
    assert rec[-1][1]["history_entry"].endswith("已收件")


def test_submitted_without_marker_is_not_accepted(cfg, tmp_path):
    hist = [{"filename": f"D-Plan_{TEAM}_{T1}.json", "status_text": "處理中"}]
    o, rec = go(cand(tmp_path), FakeDriver(after_submit_history=hist), cfg)
    assert o.status == "SUBMITTED" and rec[-1][0] == "submitted"


def test_upload_ok_validation_fail_is_rejected_no_submit(cfg, tmp_path):                         # 7
    drv = FakeDriver(validation=("FAIL", "C3 權重超限"))
    o, rec = go(cand(tmp_path), drv, cfg)
    assert o.status == "REJECTED" and "submit" not in drv.calls and rec[-1][1]["validation_result"] == "FAIL"


def test_validation_unknown_fails_closed_no_submit(cfg, tmp_path):
    drv = FakeDriver(validation=("UNKNOWN", ""))
    o, _ = go(cand(tmp_path), drv, cfg)
    assert o.status == "FAIL_CLOSED" and "VALIDATION_RESULT_UNKNOWN" in o.reason and "submit" not in drv.calls


def test_validation_pass_then_submit_failure_fails_closed(cfg, tmp_path):                         # 8
    o, rec = go(cand(tmp_path), FakeDriver(submit_raises=RuntimeError("button disabled")), cfg)
    assert o.status == "FAIL_CLOSED" and [r[0] for r in rec] == ["file_uploaded", "server_validated"]


def test_already_accepted_in_history_prevents_retry(cfg, tmp_path):                              # 9
    hist = [{"filename": f"D-Plan_{TEAM}_{T1}.json", "status_text": "已收件"}]
    drv = FakeDriver(history=hist)
    o, _ = go(cand(tmp_path), drv, cfg)
    assert o.status == "ALREADY_ACCEPTED" and "upload" not in drv.calls
    o2, _ = go(cand(tmp_path, state="ACCEPTED"), FakeDriver(), cfg)
    assert o2.status == "ALREADY_ACCEPTED"


@pytest.mark.parametrize("drv,needle", [
    (FakeDriver(session="LOGIN_REQUIRED"), "LOGIN_STATE"),
    (FakeDriver(session="UNKNOWN"), "LOGIN_STATE"),
    (FakeDriver(date="2026-10-27"), "PAGE_TRADE_DATE"),
    (FakeDriver(team="TEAM_99999"), "PAGE_TEAM"),
    (FakeDriver(attempts=None), "ATTEMPTS_REMAINING_UNREADABLE"),
    (FakeDriver(attempts=0), "OFFICIAL_ATTEMPT_LIMIT_REACHED"),
    (FakeDriver(upload_raises=TimeoutError("no file input")), "TimeoutError"),
])
def test_unexpected_ui_fails_closed(cfg, tmp_path, drv, needle):                                 # 18
    o, _ = go(cand(tmp_path), drv, cfg)
    assert o.status == "FAIL_CLOSED" and needle in o.reason and "submit" not in drv.calls


def test_duplicate_protection(cfg, tmp_path):                                                    # 19
    o, _ = go(cand(tmp_path, state="SUBMITTED"), FakeDriver(), cfg)
    assert o.status == "FAIL_CLOSED" and "SUBMITTED_AWAITING_EVIDENCE" in o.reason
    two = [{"filename": f"D-Plan_{TEAM}_{T1}.json", "status_text": "已收件"}] * 2
    o, _ = go(cand(tmp_path), FakeDriver(after_submit_history=two), cfg)
    assert o.status == "SUBMITTED" and "DUPLICATE_AMBIGUITY" in o.reason


def test_max_automated_attempts(cfg, tmp_path):                                                  # 20
    o, _ = go(cand(tmp_path), FakeDriver(), cfg, used=3)
    assert o.status == "FAIL_CLOSED" and "MAX_AUTOMATED_ATTEMPTS" in o.reason
    assert cfg["auto_upload"]["max_automated_attempts"] < AU.OFFICIAL_DAILY_LIMIT


# ---------------------------------------------------------------- 11-17 safety gate
@pytest.mark.parametrize("kw,needle", [
    (dict(team="TEAM_00001"), "TEAM_ID_MISMATCH"),                                                  # 11
    (dict(date="2026-10-27"), "WINDOW_NOT_OPEN"),                                                   # 12 (file for another day)
    (dict(name="dplan.json"), "FILENAME_MISMATCH"),                                                 # 13
    (dict(pad=2 * 1024 * 1024), "FILE_TOO_LARGE"),                                                  # 14
    (dict(ok=False), "LOCAL_VALIDATION_FAIL"),
])
def test_gate_blocks_bad_candidates(cfg, tmp_path, kw, needle):
    o, _ = go(cand(tmp_path, **kw), FakeDriver(), cfg)
    assert o.status == "FAIL_CLOSED" and needle in o.reason


def test_trade_date_mismatch_inside_file_blocks(cfg, tmp_path):                                   # 12
    c = cand(tmp_path)
    c.file.write_text(json.dumps({"team_id": TEAM, "trade_date": "2026-10-27"}), encoding="utf-8")
    from agent.ops.common import sha256_file
    c.sha256 = sha256_file(c.file)
    o, _ = go(c, FakeDriver(), cfg)
    assert "TRADE_DATE_MISMATCH" in o.reason


def test_sha_mismatch_blocks(cfg, tmp_path):
    c = cand(tmp_path)
    c.sha256 = "sha256:" + "0" * 64
    assert "SHA_MISMATCH" in go(c, FakeDriver(), cfg)[0].reason


def test_precompetition_cannot_auto_submit(cfg, tmp_path):                                       # 15
    o, _ = go(cand(tmp_path, source="competition_final", mode="dry-run"), FakeDriver(), cfg, official_test=False)
    assert o.status == "FAIL_CLOSED" and "PRECOMPETITION_AUTO_SUBMIT_FORBIDDEN" in o.reason
    o, _ = go(cand(tmp_path, source="competition_final", mode="dry-run"), FakeDriver(), cfg, official_test=False,
              run_mode="COMPETITION")
    assert "NOT_A_COMPETITION_FINAL" in o.reason          # a paper (dry-run) FINAL is never uploadable


def test_disabled_config_and_missing_manual_e2e_block(cfg, tmp_path):
    off = dict(cfg, auto_upload=dict(cfg["auto_upload"], enabled=False))
    assert "AUTO_UPLOAD_DISABLED" in go(cand(tmp_path), FakeDriver(), off)[0].reason
    assert "MANUAL_E2E_NOT_COMPLETED" in go(cand(tmp_path), FakeDriver(), cfg, e2e=False)[0].reason


def test_0830_no_new_quant_but_existing_final_may_upload(cfg, tmp_path, fixture_store):            # 16
    s = run(fixture_store, cfg, T1, "2026-10-26T08:31:00+08:00", initial=True)
    assert s["status"] == "DECISION_WINDOW_CLOSED"                                     # no new decision
    r = OT.prepare(T1, clock=Clock("2026-10-26T08:31:00+08:00"), ops_cfg=cfg)
    assert r["status"] == "BLOCKED" and r["reason"].startswith("DECISION_WINDOW_CLOSED")
    o, _ = go(cand(tmp_path), FakeDriver(), cfg, now="2026-10-26T08:40:00")             # upload of an EXISTING file
    assert o.status in ("SUBMITTED", "ACCEPTED")


def test_0855_no_submit(cfg, tmp_path):                                                            # 17
    o, _ = go(cand(tmp_path), FakeDriver(), cfg, now="2026-10-26T08:55:00")
    assert o.status == "FAIL_CLOSED" and "SUBMISSION_WINDOW_CLOSED" in o.reason
    times = iter([at("2026-10-26T08:54:00"), at("2026-10-26T08:55:01")])           # crosses 08:55 mid-run
    drv = FakeDriver()
    o = AU.run(cand(tmp_path), drv, now_fn=lambda: next(times), ops_cfg=cfg, run_mode="PRECOMPETITION",
               official_test=True, attempts_used=0, manual_e2e_done=True, record=lambda *a, **k: None)
    assert o.status == "FAIL_CLOSED" and "submit" not in drv.calls


def test_playwright_driver_refuses_without_observed_selectors():
    with pytest.raises(AU.UIUnexpected, match="SELECTORS_NOT_CONFIGURED"):
        AU.PlaywrightDriver(load_ops_config())


# ---------------------------------------------------------------- sealed-test preparation + manual E2E gate
def test_prepare_generates_official_team_dplan_isolated_and_validated(cfg, fixture_store, tmp_path, monkeypatch):
    iso_root = tmp_path / "iso"

    def iso(t, ops=None):
        import copy
        c = copy.deepcopy(ops or cfg)
        for k, v in c["paths"].items():
            c["paths"][k] = str(iso_root / Path(v).name)
        return c
    monkeypatch.setattr(OT, "isolated_ops", iso)
    r = OT.prepare(T1, clock=Clock(CLK1), ops_cfg=cfg, store=fixture_store, skip_refresh=True, git=CLEAN_GIT)
    p = r["package"]
    assert r["status"] == "READY_FOR_MANUAL_TEST_UPLOAD", (r.get("reason"), p.get("problems"), p.get("local_validation"))
    assert p["final"]["filename"] == f"D-Plan_{TEAM}_{T1}.json" and p["final"]["team_id_in_file"] == TEAM
    assert all(v == "PASS" for v in p["local_validation"].values()) and p["file_bytes"] <= 2 * 1024 * 1024
    assert str(iso_root) in p["final"]["file"]                                        # never the paper-run folders
    c = AU.candidate_from_official_test(T1, cfg)
    assert c.state == "READY_FOR_UPLOAD" and c.local_validation_ok and c.team_id == TEAM


def test_manual_e2e_flag_requires_human_accepted_record(cfg):
    assert not AU.manual_e2e_completed(cfg)
    OT.record_upload(T1, "sha256:" + "a" * 64, "accepted", "已收件", "auto_upload", submission_id="X", ops_cfg=cfg)
    assert not AU.manual_e2e_completed(cfg)                                           # automation does not count
    OT.record_upload(T1, "sha256:" + "a" * 64, "accepted", "已收件", "Owner", stage="submitted",
                     history_entry="08:06 D-Plan 已收件", ops_cfg=cfg)
    assert AU.manual_e2e_completed(cfg)
