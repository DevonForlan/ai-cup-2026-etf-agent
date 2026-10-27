"""Issue #4 — portal binding, lifecycle, sealed-test preparation, guarded automated upload (fake portal only:
nothing here touches the real portal), adapter policy, manual fallback, signals, DataPack handoff, scheduler stage."""
import json
from datetime import datetime
from pathlib import Path

import pytest

from agent.ops.common import Clock, load_ops_config, sha256_file
from agent.submission import auto_upload as AU
from agent.submission import official_test as OT
from agent.submission import portal_driver as PD
from agent.submission import status as ST
from agent.submission.receipt import Receipt, record_receipt
from tests.ops.conftest import CLEAN_GIT
from tests.ops.test_competition_day import CLK1, T1, run

TEAM = "TEAM_11442"
FNAME = f"D-Plan_{TEAM}_{T1}.json"


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
                        "acceptance_timeout_s": 0, "acceptance_poll_s": 0}
    c["team"] = {"competition_team_id": TEAM, "precompetition_team_id": "TEAM_TEST"}
    return c


def cand(tmp_path, *, team=TEAM, date=T1, name=None, pad=0, state="READY_FOR_UPLOAD", ok=True,
         source="official_test_package", mode="dry-run"):
    doc = {"schema_version": "4.3", "team_id": team, "trade_date": date, "orders": [], "decisions": [], "pad": "x" * pad}
    f = tmp_path / (name or f"D-Plan_{team}_{date}.json")
    f.write_text(json.dumps(doc), encoding="utf-8")
    checks = {k: "PASS" for k in AU.REQUIRED_CHECKS}
    if not ok:
        checks["schema"] = "FAIL"
    return AU.Candidate(date, team, f, sha256_file(f), state, ok, source, mode, checks, "2026-10-26T19:40:00+08:00",
                        "2026-10-26T19:41:00+08:00")


ACC = {"text": f"10-26 08:06 {FNAME} 已收件", "accepted": True, "rejected": False}
REJ = {"text": f"10-26 08:06 {FNAME} 未通過", "accepted": False, "rejected": True}


class FakePortal(PD.PortalDriver):
    def __init__(self, *, login="LOGGED_IN", team=TEAM, date=T1, window="UNKNOWN", attempts=(0, 25), history=None,
                 after_submit=None, validation=("PASS", "檢核通過"), submit_result=("OK", "已送出"), upload_raises=None,
                 submit_raises=None, dialogs=None, validation_timeout=None, raises_after_click=False):
        self.login, self.team, self.date, self.window, self.attempts = login, team, date, window, attempts
        self.history, self.after = history or [], after_submit
        self.validation, self.submit_result = validation, submit_result
        self.upload_raises, self.submit_raises, self.dialogs = upload_raises, submit_raises, dialogs or []
        self.validation_timeout, self.calls, self.closed = validation_timeout, [], False
        self.raises_after_click = raises_after_click          # Issue #20: refused before the click vs result unknown

    def open_portal(self): self.calls.append("open")
    def check_login(self):                     # a list = successive answers (e.g. session expiring mid-run)
        if isinstance(self.login, list):
            return self.login.pop(0) if len(self.login) > 1 else self.login[0]
        return self.login
    def read_page_state(self): return {"url": "https://portal/docs", "window_status": self.window, "dialogs": self.dialogs,
                                       "unexpected_dialogs": self.dialogs}
    def read_window_status(self): return self.window
    def read_team_id(self): return self.team
    def read_trade_date(self): return self.date
    def read_attempts(self): return self.attempts
    def read_history(self): return self.after if ("submit" in self.calls and self.after is not None) else self.history

    def upload_file(self, path):
        self.calls.append("upload")
        if self.upload_raises:
            raise self.upload_raises

    def wait_for_server_validation(self, timeout_s):
        if self.validation_timeout:
            raise self.validation_timeout

    def read_validation_result(self): return self.validation

    def submit(self):
        self.calls.append("submit")
        if self.submit_raises:
            self.submit_clicked = self.raises_after_click
            raise self.submit_raises

    def read_submit_result(self): return self.submit_result

    def verify_acceptance(self, file_name, sha256, trade_date, timeout_s, poll_s):
        return [r for r in self.read_history() if r.get("accepted") and file_name in r["text"]]

    def capture_evidence(self, tag): return [f"evidence/{tag}.png"]
    def close(self): self.closed = True


def go(c, drv, cfg, *, now="2026-10-26T07:00:00", official_test=True, used=0, e2e=True, mode="PRECOMPETITION",
       prior=()):
    rec = []
    o = AU.run(c, drv, now_fn=lambda: at(now), ops_cfg=cfg, run_mode=mode, official_test=official_test,
               attempts_used=used, manual_e2e_done=e2e, record=lambda stage, **kw: rec.append((stage, kw)),
               prior_shas=prior)
    return o, rec


# ---------------------------------------------------------------- config / adapter
def test_team_portal_bound_and_auto_upload_disabled():
    ops = load_ops_config()
    assert ops["team"]["competition_team_id"] == TEAM
    assert ops["submission"]["portal_url"] == "https://fundaiagent.esun-ai-challenge.tw/docs"
    assert ops["submission"]["ui_status"] == "AVAILABLE" and ops["submission"]["max_upload_bytes"] == 2097152
    # Owner Decision 2026-10-27 (Issue #20): enabled after the Day-1 manual E2E reached SUBMISSION_CONFIRMED
    assert ops["auto_upload"]["enabled"] is True and ops["auto_upload"]["method"] == "browser"


def test_adapter_unconfirmed_entries_are_pending_and_never_guessed():
    inv = {r["element"]: r for r in PD.selector_inventory(PD.load_adapter())}
    # window-only elements (not visible on 2026-10-23, no window open): no strategy, never guessed
    for name in ("upload_button", "server_validation_pass_marker",
                 "submit_confirmation_modal", "submit_confirm_button", "accepted_history_marker", "rejected_marker"):
        assert inv[name]["status"] == "PENDING_WINDOW_ONLY" and inv[name]["strategies"] == [], name
    # confirmed on the real logged-in page (read-only discovery 2026-10-23)
    for name in ("team_id", "trade_date", "attempt_count", "dplan_file_input", "upload_area", "validation_result_panel",
                 "submission_history_table", "history_rows", "strategy_document_status", "datapack_download",
                 "nav_docs_link", "no_window_marker", "server_validation_fail_marker"):
        assert inv[name]["status"] == "CONFIRMED_REAL_E2E" and inv[name]["usable_for_read"], name
    # Issue #20 (2026-10-27): the 送出繳交 <button> is confirmed on the real DOM (read-only discovery + the Owner's real
    # submit that produced the 10/27 history row) -> usable; the confirmation modal / its button are still unseen
    assert inv["submit_button"]["usable_for_action_competition"]
    assert "Issue #20" in PD.load_adapter()["selectors"]["submit_button"]["confirmed"]
    assert not inv["submit_confirm_button"]["usable_for_action_competition"]
    a = PD.load_adapter()
    assert a["wording"]["history_accepted"]["status"] in PD.PENDING and PD.wording_markers(a, "history_accepted") == []
    # Issue #20 live observation 2026-10-27 21:04: validation_pass / submit_success confirmed from the real submit
    for w in ("validation_pass", "submit_success"):
        assert a["wording"][w]["status"] == "CONFIRMED_REAL_E2E" and "_observe" in a["wording"][w]["source"], w
    for st in a["selectors"].values():                                                 # no xpath / nth-child selectors
        for s in st.get("strategies") or []:
            assert "xpath" not in json.dumps(s).lower() and "nth-child" not in json.dumps(s)


def test_validation_classification_is_verbatim_only():
    a = PD.load_adapter()
    assert PD.classify("檢核通過", a, "validation_pass", "validation_fail") == "UNKNOWN"     # pending wording
    b = dict(a, wording=dict(a["wording"], validation_pass={"status": "CONFIRMED_REAL_E2E", "markers": ["檢核通過"]},
                                            validation_fail={"status": "CONFIRMED_REAL_E2E", "markers": ["檢核未通過"]}))
    assert PD.classify("結果：檢核通過", b, "validation_pass", "validation_fail") == "PASS"
    assert PD.classify("結果：檢核未通過", b, "validation_pass", "validation_fail") == "FAIL"
    assert PD.classify("通過?", b, "validation_pass", "validation_fail") == "UNKNOWN"   # no fuzzy guessing


def test_driver_refuses_pending_selectors_for_actions():
    d = object.__new__(PD.PlaywrightPortalDriver)
    d.adapter, d.official_test = PD.load_adapter(), False
    with pytest.raises(PD.UIUnexpected, match="PENDING_"):
        d._locate("upload_button", action=True)
    import copy                                                   # Issue #20 confirmed the real 送出繳交 button; the rule
    d.adapter = copy.deepcopy(d.adapter)                          # itself is still tested on an OWNER_OBSERVED_LABEL entry
    d.adapter["selectors"]["submit_button"]["status"] = "OWNER_OBSERVED_LABEL"
    with pytest.raises(PD.UIUnexpected, match="OWNER_OBSERVED_LABEL"):
        d._locate("submit_button", action=True)                  # COMPETITION needs CONFIRMED_REAL_E2E
    d.adapter = PD.load_adapter()
    d.official_test = True
    with pytest.raises(PD.UIUnexpected, match="PENDING_"):
        d._locate("submit_confirm_button", action=True)


# ---------------------------------------------------------------- lifecycle from evidence (competition receipts)
def _receipt(sha, stage, status="pending", **kw):
    return Receipt(T1, "TEAM_TEST", sha, "2026-10-26T08:05:00+08:00", "browser_automation", "auto",
                   official_status=status, stage=stage, **kw)


def test_lifecycle_stages_and_acceptance_needs_evidence(fixture_store, ops_cfg):
    s = run(fixture_store, ops_cfg, T1, CLK1, initial=True)
    sha, now = s["sha256"], at("2026-10-26T08:10:00")
    record_receipt(_receipt(sha, "file_uploaded"), ops_cfg)
    assert ST.compute(T1, now=now, ops_cfg=ops_cfg)["state"] == "FILE_UPLOADED"
    record_receipt(_receipt(sha, "server_validated", server_validation_result="UNKNOWN"), ops_cfg)
    assert ST.compute(T1, now=now, ops_cfg=ops_cfg)["state"] == "FILE_UPLOADED"
    record_receipt(_receipt(sha, "server_validated", server_validation_result="PASS"), ops_cfg)
    assert ST.compute(T1, now=now, ops_cfg=ops_cfg)["state"] == "SERVER_VALIDATED"
    record_receipt(_receipt(sha, "submitted", server_validation_result="PASS"), ops_cfg)
    assert ST.compute(T1, now=now, ops_cfg=ops_cfg)["state"] == "SUBMITTED"
    record_receipt(_receipt(sha, "accepted", "accepted"), ops_cfg)                     # wording, no evidence
    assert ST.compute(T1, now=now, ops_cfg=ops_cfg)["state"] == "SUBMITTED"
    record_receipt(_receipt(sha, "accepted", "accepted", history_entry=ACC["text"]), ops_cfg)
    assert ST.compute(T1, now=at("2026-10-26T09:00:00"), ops_cfg=ops_cfg)["state"] == "ACCEPTED"


def test_accepted_then_later_rejected_keeps_accepted(fixture_store, ops_cfg):
    s = run(fixture_store, ops_cfg, T1, CLK1, initial=True)
    record_receipt(_receipt(s["sha256"], "accepted", "accepted", official_receipt_id="R-1"), ops_cfg)
    assert record_receipt(_receipt(s["sha256"], "rejected", "rejected", server_validation_result="FAIL"),
                          ops_cfg)["state"] == "SUBMISSION_CONFIRMED"
    st = ST.compute(T1, now=at("2026-10-26T08:40:00"), ops_cfg=ops_cfg)
    assert st["state"] == "ACCEPTED" and st["submission_id"] == "R-1" and st["last_upload_is_effective"] is False


# ---------------------------------------------------------------- mocked portal scenarios (§20)
def test_happy_path_logged_in_window_open_attempts_remaining(cfg, tmp_path):
    drv = FakePortal(after_submit=[ACC])
    o, rec = go(cand(tmp_path), drv, cfg)
    assert o.status == "ACCEPTED" and [r[0] for r in rec] == ["file_uploaded", "server_validated", "submitted", "accepted"]
    assert rec[-1][1]["history_entry"] == ACC["text"] and o.portal["attempts_remaining"] == 25 and o.evidence


@pytest.mark.parametrize("drv,status,needle", [
    (FakePortal(login="LOGIN_REQUIRED"), "LOGIN_REQUIRED", "LOGIN_STATE_LOGIN_REQUIRED"),          # logged out
    (FakePortal(login="UNKNOWN"), "LOGIN_REQUIRED", "LOGIN_STATE_UNKNOWN"),                        # unexpected page
    (FakePortal(team="TEAM_99999"), "FAIL_CLOSED", "PAGE_TEAM_ID"),                                # wrong team
    (FakePortal(team=None), "FAIL_CLOSED", "PAGE_TEAM_ID"),                                        # team unreadable
    (FakePortal(date="2026-10-27"), "FAIL_CLOSED", "PAGE_TRADE_DATE"),                             # wrong trade date
    (FakePortal(window="CLOSED"), "WINDOW_CLOSED", "closed"),                                      # no window
    (FakePortal(attempts=(None, None)), "FAIL_CLOSED", "ATTEMPTS_UNREADABLE"),
    (FakePortal(attempts=(25, 0)), "FAIL_CLOSED", "OFFICIAL_ATTEMPT_LIMIT_REACHED"),
    (FakePortal(upload_raises=TimeoutError("input missing")), "FAIL_CLOSED", "TimeoutError"),      # upload failure
    (FakePortal(validation=("UNKNOWN", "???")), "FAIL_CLOSED", "VALIDATION_RESULT_UNKNOWN"),
    (FakePortal(validation_timeout=TimeoutError("no panel")), "FAIL_CLOSED",                       # timeout
     "MANUAL_CHECK_REQUIRED: VALIDATION_TIMEOUT"),
    (FakePortal(login=["LOGGED_IN", "LOGIN_REQUIRED"]), "LOGIN_REQUIRED", "LOGIN_EXPIRED_MID_RUN"),  # expiry mid-run
    (FakePortal(dialogs=["系統公告：請稍候"]), "FAIL_CLOSED", "UNEXPECTED_MODAL"),
    (FakePortal(submit_raises=RuntimeError("button disabled")), "FAIL_CLOSED", "button disabled"), # submit failure
])
def test_fail_closed_scenarios(cfg, tmp_path, drv, status, needle):
    o, _ = go(cand(tmp_path), drv, cfg)
    assert o.status == status and needle in o.reason
    assert o.status == "FAIL_CLOSED" or "submit" not in drv.calls


def test_validation_fail_is_rejected_without_submit(cfg, tmp_path):
    drv = FakePortal(validation=("FAIL", "C3 權重超限"))
    o, rec = go(cand(tmp_path), drv, cfg)
    assert o.status == "REJECTED" and "submit" not in drv.calls and rec[-1][1]["validation_result"] == "FAIL"


def test_submit_refused_by_portal_is_rejected(cfg, tmp_path):
    o, rec = go(cand(tmp_path), FakePortal(submit_result=("FAIL", "目前不在繳交時間內，本次未送出。")), cfg)
    assert o.status == "REJECTED" and rec[-1][0] == "rejected"


@pytest.mark.parametrize("after,needle", [
    ([], "no official acceptance evidence"),                                   # history delayed / timeout
    ([REJ], "no official acceptance evidence"),                                # history rejected row only
    ([ACC, ACC], "ambiguous"),                                                 # duplicate rows
])
def test_submitted_without_clear_evidence_is_not_accepted(cfg, tmp_path, after, needle):
    o, rec = go(cand(tmp_path), FakePortal(after_submit=after), cfg)
    assert o.status == "SUBMITTED_UNVERIFIED" and needle in o.reason and rec[-1][0] == "submitted"
    assert o.manual_action_required


def test_already_accepted_in_history_never_uploads(cfg, tmp_path):
    drv = FakePortal(history=[ACC])
    o, _ = go(cand(tmp_path), drv, cfg)
    assert o.status == "ALREADY_ACCEPTED" and "upload" not in drv.calls
    o2, _ = go(cand(tmp_path, state="ACCEPTED"), FakePortal(), cfg)               # duplicate accepted (state)
    assert o2.status == "ALREADY_ACCEPTED"


def test_submitted_state_only_verifies(cfg, tmp_path):
    drv = FakePortal(history=[], after_submit=None)
    drv.history = []
    o, rec = go(cand(tmp_path, state="SUBMITTED"), drv, cfg, used=3)               # attempt cap irrelevant for verify
    assert "upload" not in drv.calls and "submit" not in drv.calls and o.status == "SUBMITTED_UNVERIFIED"


def test_server_validated_state_submits_without_reupload(cfg, tmp_path):
    drv = FakePortal(after_submit=[ACC])
    o, rec = go(cand(tmp_path, state="SERVER_VALIDATED"), drv, cfg)
    assert o.status == "ACCEPTED" and "upload" not in drv.calls and [r[0] for r in rec] == ["submitted", "accepted"]


def test_retry_same_sha_allowed_different_sha_blocked(cfg, tmp_path):
    c = cand(tmp_path)
    assert go(c, FakePortal(after_submit=[ACC]), cfg, used=1, prior=(c.sha256,))[0].status == "ACCEPTED"
    o, _ = go(c, FakePortal(), cfg, used=1, prior=("sha256:" + "0" * 64,))
    assert o.status == "FAIL_CLOSED" and "DIFFERENT_SHA_RETRY_BLOCKED" in o.reason


def test_max_automated_attempts(cfg, tmp_path):
    o, _ = go(cand(tmp_path), FakePortal(), cfg, used=3)
    assert "MAX_AUTOMATED_ATTEMPTS" in o.reason and cfg["auto_upload"]["max_automated_attempts"] < AU.OFFICIAL_DAILY_LIMIT


@pytest.mark.parametrize("kw,needle", [
    (dict(team="TEAM_00001"), "TEAM_ID_MISMATCH"), (dict(name="dplan.json"), "FILENAME_MISMATCH"),
    (dict(pad=2 * 1024 * 1024), "FILE_TOO_LARGE"), (dict(ok=False), "LOCAL_VALIDATION_FAIL"),
    (dict(date="2026-10-27"), "WINDOW_NOT_OPEN"),
])
def test_gate_blocks_bad_candidates(cfg, tmp_path, kw, needle):
    drv = FakePortal()
    o, _ = go(cand(tmp_path, **kw), drv, cfg)
    assert o.status == "FAIL_CLOSED" and needle in o.reason and drv.calls == []      # browser never touched


def test_sha_mismatch_and_precompetition(cfg, tmp_path):
    c = cand(tmp_path)
    c.sha256 = "sha256:" + "0" * 64
    assert "SHA_MISMATCH" in go(c, FakePortal(), cfg)[0].reason
    o, _ = go(cand(tmp_path, source="competition_final", mode="dry-run"), FakePortal(), cfg, official_test=False)
    assert "PRECOMPETITION_AUTO_SUBMIT_FORBIDDEN" in o.reason
    o, _ = go(cand(tmp_path, source="competition_final", mode="dry-run"), FakePortal(), cfg, official_test=False,
              mode="COMPETITION")
    assert "NOT_A_COMPETITION_FINAL" in o.reason


def test_disabled_and_missing_manual_e2e(cfg, tmp_path):
    off = dict(cfg, auto_upload=dict(cfg["auto_upload"], enabled=False))
    assert "AUTO_UPLOAD_DISABLED" in go(cand(tmp_path), FakePortal(), off)[0].reason
    assert "MANUAL_E2E_NOT_COMPLETED" in go(cand(tmp_path), FakePortal(), cfg, e2e=False)[0].reason


def test_0830_cutoff_existing_final_only(cfg, tmp_path, fixture_store):
    assert run(fixture_store, cfg, T1, "2026-10-26T08:31:00+08:00", initial=True)["status"] == "DECISION_WINDOW_CLOSED"
    assert OT.prepare(T1, clock=Clock("2026-10-26T08:31:00+08:00"), ops_cfg=cfg)["reason"].startswith("DECISION_WINDOW_CLOSED")
    assert go(cand(tmp_path), FakePortal(after_submit=[ACC]), cfg, now="2026-10-26T08:40:00")[0].status == "ACCEPTED"


def test_0855_cutoff_including_mid_run(cfg, tmp_path):
    assert go(cand(tmp_path), FakePortal(), cfg, now="2026-10-26T08:55:00")[0].status == "WINDOW_CLOSED"
    times = iter([at("2026-10-26T08:54:00")] * 3 + [at("2026-10-26T08:55:01")] * 5)
    drv = FakePortal()
    o = AU.run(cand(tmp_path), drv, now_fn=lambda: next(times), ops_cfg=cfg, run_mode="PRECOMPETITION",
               official_test=True, attempts_used=0, manual_e2e_done=True, record=lambda *a, **k: None)
    assert o.status == "WINDOW_CLOSED" and "submit" not in drv.calls


# ---------------------------------------------------------------- manual fallback / signals / execute
def test_manual_fallback_contains_everything_and_signals(cfg, tmp_path):
    from agent.ops import signals
    c = cand(tmp_path)
    info = AU.manual_fallback(c, AU.Outcome("FAIL_CLOSED", "VALIDATION_RESULT_UNKNOWN", portal={"attempts_used": 2,
                              "attempts_remaining": 23}), ops_cfg=cfg, now=at("2026-10-26T08:20:00"), attempts_used=1)
    for k in ("trade_date", "team_id", "dplan_path", "filename", "sha256", "file_bytes", "local_validation",
              "submission_state", "failure_reason", "attempts_used_automation", "portal_attempts_remaining",
              "window_minutes_left", "manual_steps"):
        assert info[k] is not None, k
    assert info["window_minutes_left"] == 35.0 and info["signal"] == "MANUAL_UPLOAD_REQUIRED"
    assert any(s["signal"] == "MANUAL_UPLOAD_REQUIRED" for s in signals.read(T1, cfg))
    assert (AU.evidence_dir(T1, cfg) / "MANUAL_UPLOAD_REQUIRED.json").exists()


def test_execute_end_to_end_with_fake_driver(cfg, tmp_path, monkeypatch):
    from agent.ops import signals
    c = cand(tmp_path)
    monkeypatch.setattr(AU, "candidate_from_official_test", lambda t, o: c)
    monkeypatch.setattr(AU, "manual_e2e_completed", lambda o: True)
    drv = FakePortal(after_submit=[ACC])
    r = AU.execute(T1, official_test=True, ops_cfg=cfg, now_fn=lambda: at("2026-10-26T07:00:00"),
                   driver_factory=lambda o, t: drv)
    assert r["outcome"]["status"] == "ACCEPTED" and drv.closed
    assert any(s["signal"] == "SUBMISSION_ACCEPTED" for s in signals.read(T1, cfg))
    audit = (AU.evidence_dir(T1, cfg) / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["stage"] for x in audit] == ["file_uploaded", "server_validated", "submitted", "accepted"]
    r2 = AU.execute(T1, official_test=True, ops_cfg=cfg, now_fn=lambda: at("2026-10-26T07:00:00"),
                    driver_factory=lambda o, t: FakePortal(login="LOGIN_REQUIRED"))
    assert r2["outcome"]["status"] == "LOGIN_REQUIRED" and r2["manual"]["signal"] == "MANUAL_UPLOAD_REQUIRED"
    assert any(s["signal"] == "LOGIN_REQUIRED" for s in signals.read(T1, cfg))


def test_execute_gate_failure_never_starts_browser(cfg, tmp_path, monkeypatch):
    c = cand(tmp_path)
    monkeypatch.setattr(AU, "candidate_from_official_test", lambda t, o: c)
    monkeypatch.setattr(AU, "manual_e2e_completed", lambda o: False)
    started = []
    r = AU.execute(T1, official_test=True, ops_cfg=cfg, now_fn=lambda: at("2026-10-26T07:00:00"),
                   driver_factory=lambda o, t: started.append(1))
    assert r["outcome"]["status"] == "FAIL_CLOSED" and not started and "manual" in r


# ---------------------------------------------------------------- DataPack handoff
def test_datapack_handoff(cfg, fixture_store, monkeypatch):
    from agent.ops import signals
    from agent.submission import handoff as H
    pre = H.datapack_handoff(T1, ops_cfg=cfg, run_mode="PRECOMPETITION", now=at("2026-10-26T20:00:00"))
    assert pre["datapack_status"] == "NOT_APPLICABLE_PRECOMPETITION"
    monkeypatch.setattr(ST, "compute", lambda *a, **k: {"state": "ACCEPTED"})
    comp = H.datapack_handoff(T1, ops_cfg=cfg, run_mode="COMPETITION", now=at("2026-10-26T20:00:00"))
    assert comp["datapack_status"] == "DATAPACK_REQUIRED" and comp["start_source_next"] is None   # no paper fallback
    assert any(s["signal"] == "DATAPACK_REQUIRED" for s in signals.read(comp["next_trade_date"], cfg))
    import agent.ops.datapack as DP
    dp = Path(cfg["paths"]["official_datapack_dir"])
    dp.mkdir(parents=True, exist_ok=True)
    f = dp / f"DataPack_{TEAM}_{comp['next_trade_date']}.json"
    f.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(DP, "datapack_gate", lambda *a, **k: {"status": "PASS", "file": str(f),
                        "settlement_date": T1, "schema_version": "3.0", "freshness": "FRESH",
                        "official": {"nav": 1.0, "cash": 1.0, "holdings": {}}})
    ready = H.datapack_handoff(T1, ops_cfg=cfg, run_mode="COMPETITION", now=at("2026-10-26T20:00:00"))
    assert ready["datapack_status"] == "DATAPACK_READY" and ready["start_source_next"] == "OFFICIAL_DATAPACK"
    assert ready["datapack_sha256"] == sha256_file(f)
    monkeypatch.setattr(DP, "datapack_gate", lambda *a, **k: {"status": "FAIL", "reason": "DATAPACK_SCHEMA_INVALID"})
    bad = H.datapack_handoff(T1, ops_cfg=cfg, run_mode="COMPETITION", now=at("2026-10-26T20:00:00"))
    assert bad["datapack_status"] == "DATAPACK_SCHEMA_INVALID" and bad["start_source_next"] is None


# ---------------------------------------------------------------- scheduler submission stage / latest_status
def test_scheduler_submission_stage(cfg, monkeypatch, tmp_path):
    from agent.ops import scheduled_run as S
    rec = {}
    S.submission_stage(T1, "PRECOMPETITION", rec, ops_cfg=cfg)
    assert rec["auto_upload_status"] == "NOT_APPLICABLE_PRECOMPETITION" and rec["manual_action_required"] is False
    off = dict(cfg, auto_upload=dict(cfg["auto_upload"], enabled=False))
    monkeypatch.setattr(AU, "candidate_from_competition", lambda t, o: cand(tmp_path, source="competition_final",
                                                                             mode="competition"))
    rec = {}
    S.submission_stage(T1, "COMPETITION", rec, ops_cfg=off)
    assert rec["auto_upload_status"] == "DISABLED" and rec["manual_action_required"] is True
    monkeypatch.setattr(S, "LATEST", tmp_path / "latest_status.json")
    monkeypatch.setattr(S, "LOG_DIR", tmp_path)
    fake = lambda t, **k: {"outcome": {"status": "ACCEPTED", "reason": "ok", "portal": {"login_state": "LOGGED_IN",  # noqa: E731
                                       "attempts_used": 1, "attempts_remaining": 24, "window_status": "UNKNOWN"}}}
    rec = {"trade_date": T1}
    S.submission_stage(T1, "COMPETITION", rec, ops_cfg=cfg, executor=fake)
    assert rec["auto_upload_status"] == "ACCEPTED" and rec["manual_action_required"] is False
    assert rec["attempts_remaining"] == 24 and rec["login_state"] == "LOGGED_IN"
    st = S.ops_status_fields(dict(rec, quant="PASS", dplan_validation="PASS", final_candidate="x"), {"state": "ACCEPTED"})
    for k in ("decision_status", "validation_status", "final_status", "submission_state", "portal_state", "login_state",
              "attempts_used", "attempts_remaining", "auto_upload_status", "last_error", "manual_action_required",
              "accepted"):
        assert k in st, k
    assert st["accepted"] is True and st["final_status"] == "FINAL"


# ---------------------------------------------------------------- sealed-test preparation + manual E2E flag
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
    assert p["final"]["filename"] == FNAME and p["final"]["team_id_in_file"] == TEAM
    assert all(v == "PASS" for v in p["local_validation"].values()) and p["file_bytes"] <= 2 * 1024 * 1024
    assert str(iso_root) in p["final"]["file"]
    c = AU.candidate_from_official_test(T1, cfg)
    assert c.state == "READY_FOR_UPLOAD" and c.local_validation_ok and c.team_id == TEAM


def test_manual_e2e_flag_requires_human_accepted_record(cfg):
    """Sealed-test path: a manual record counts only with official evidence AND the package's SHA / team;
    an automation record never counts (ChatGPT review on PR #8, 2026-10-24)."""
    sha = "sha256:" + "a" * 64
    assert not AU.manual_e2e_completed(cfg)
    rep = OT.dirs(T1, cfg)["reports"]
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "TEST_SUBMISSION_PACKAGE.json").write_text(json.dumps({"final": {"sha256": sha, "team_id_in_file": TEAM}}),
                                                      encoding="utf-8")
    OT.record_upload(T1, sha, "accepted", "已收件", "auto_upload", submission_id="X", ops_cfg=cfg)
    assert not AU.manual_e2e_completed(cfg)                                        # automation record
    OT.record_upload(T1, "sha256:" + "b" * 64, "accepted", "已收件", "Owner", stage="submitted",
                     history_entry=ACC["text"], ops_cfg=cfg)
    assert not AU.manual_e2e_completed(cfg)                                        # SHA not the package's
    OT.record_upload(T1, sha, "accepted", "已收件", "Owner", stage="submitted", history_entry=ACC["text"], ops_cfg=cfg)
    ev = AU.manual_e2e_evidence(cfg)
    assert ev["completed"] and ev["evidence"][0]["source"] == "official_test_record"


# ---------------------------------------------------------------- manual-E2E prerequisite from the competition path
T_COMP = "2026-10-27"
FINAL_SHA = "sha256:" + "c" * 64


def _final(monkeypatch, *, team=TEAM, sha=FINAL_SHA, mode="competition"):
    import agent.ops.package_submission as PS
    monkeypatch.setattr(PS, "active_final", lambda t, o=None: {"trade_date": t, "team_id": team, "sha256": sha,
                                                              "mode": mode} if t == T_COMP else None)


def _comp_receipt(cfg, **kw):
    from dataclasses import asdict
    from agent.submission.receipt import receipts_path
    r = dict(asdict(Receipt(T_COMP, TEAM, FINAL_SHA, "2026-10-27T08:10:00+08:00", "manual_web", "Owner",
                            official_status="accepted", stage="accepted", history_entry=ACC["text"])), **kw)
    p = receipts_path(r["trade_date"], cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def test_e2e_prereq_a_no_manual_acceptance_blocks_gate(cfg, tmp_path, monkeypatch):
    _final(monkeypatch)
    assert AU.manual_e2e_evidence(cfg) == {"completed": False, "evidence": [], "rejected": []}
    o, _ = go(cand(tmp_path), FakePortal(), cfg, e2e=AU.manual_e2e_completed(cfg))
    assert o.status == "FAIL_CLOSED" and "MANUAL_E2E_NOT_COMPLETED" in o.reason


def test_e2e_prereq_b_competition_manual_acceptance_with_evidence_passes(cfg, monkeypatch):
    _final(monkeypatch)
    _comp_receipt(cfg)                                                          # history row as evidence
    ev = AU.manual_e2e_evidence(cfg)
    assert ev["completed"] and ev["evidence"][0] == {"source": "competition_receipt", "trade_date": T_COMP,
                                                     "sha256": FINAL_SHA, "evidence": ACC["text"]}


def test_e2e_prereq_b2_receipt_id_is_also_evidence(cfg, monkeypatch):
    _final(monkeypatch)
    _comp_receipt(cfg, history_entry=None, official_receipt_id="R-0001")
    assert AU.manual_e2e_completed(cfg)


def test_e2e_prereq_c_automation_receipt_never_satisfies_itself(cfg, monkeypatch):
    _final(monkeypatch)
    _comp_receipt(cfg, submission_method="browser_automation", confirmed_by="auto_upload")
    _comp_receipt(cfg, confirmed_by="auto_upload")                              # even if mislabelled manual_web
    ev = AU.manual_e2e_evidence(cfg)
    assert not ev["completed"] and len(ev["rejected"]) == 2
    assert all("not a manual portal submission" in r["reason"] for r in ev["rejected"])


@pytest.mark.parametrize("kw,needle", [
    (dict(history_entry=None), "no official acceptance evidence"),                  # "accepted" without evidence
    (dict(official_status="pending"), "no official acceptance evidence"),
    (dict(stage="server_validated"), "no official acceptance evidence"),            # stage below submitted
    (dict(stage="file_uploaded", official_status="unknown"), "no official acceptance evidence"),
])
def test_e2e_prereq_d_accepted_wording_without_evidence_is_not_enough(cfg, monkeypatch, kw, needle):
    _final(monkeypatch)
    _comp_receipt(cfg, **kw)
    ev = AU.manual_e2e_evidence(cfg)
    assert not ev["completed"] and needle in ev["rejected"][0]["reason"]


@pytest.mark.parametrize("final_kw,receipt_kw,needle", [
    ({}, dict(team_id="TEAM_99999"), "team"),                                       # wrong team on the receipt
    (dict(team="TEAM_99999"), {}, "no competition FINAL"),                          # FINAL of another team
    ({}, dict(trade_date="2026-10-28"), "no competition FINAL"),                    # no FINAL for that date
    ({}, dict(dplan_sha256="sha256:" + "d" * 64), "does not match the FINAL"),      # different SHA
    (dict(mode="dry-run"), {}, "no competition FINAL"),                             # paper / dry-run FINAL
])
def test_e2e_prereq_e_team_date_sha_must_match_the_final(cfg, monkeypatch, final_kw, receipt_kw, needle):
    _final(monkeypatch, **final_kw)
    _comp_receipt(cfg, **receipt_kw)
    ev = AU.manual_e2e_evidence(cfg)
    assert not ev["completed"] and needle in ev["rejected"][0]["reason"]


def test_e2e_prereq_ambiguity_rule_direct(cfg, monkeypatch):
    """Two accepted manual records for one trade date with different SHAs (e.g. FINAL replaced): ambiguous."""
    import agent.ops.package_submission as PS
    shas = iter([FINAL_SHA, "sha256:" + "e" * 64])
    monkeypatch.setattr(PS, "active_final", lambda t, o=None: {"team_id": TEAM, "mode": "competition",
                                                              "sha256": next(shas)})
    _comp_receipt(cfg)
    _comp_receipt(cfg, dplan_sha256="sha256:" + "e" * 64)
    ev = AU.manual_e2e_evidence(cfg)
    assert not ev["completed"] and all("ambiguous" in r["reason"] for r in ev["rejected"])


def test_e2e_prereq_does_not_enable_auto_upload(cfg, monkeypatch, tmp_path):
    """The prerequisite only removes one gate failure; Owner approval (auto_upload.enabled) is still required."""
    _final(monkeypatch)
    _comp_receipt(cfg)
    off = dict(cfg, auto_upload=dict(cfg["auto_upload"], enabled=False))
    o, _ = go(cand(tmp_path), FakePortal(), off, e2e=AU.manual_e2e_completed(off))
    assert o.status == "FAIL_CLOSED" and "AUTO_UPLOAD_DISABLED" in o.reason and "MANUAL_E2E" not in o.reason
    # the switch itself is an explicit Owner decision recorded next to it (Issue #20), never set by the prerequisite
    assert "Owner Decision 2026-10-27 (Issue #20)" in (Path(__file__).resolve().parents[2] / "config" /
                                                       "ops.yaml").read_text(encoding="utf-8")


# ---------------------------------------------------------------- pre-E2E finalization (gate, resume, audit, signals)
def test_gate_unknown_local_check_fails_closed(cfg, tmp_path):
    c = cand(tmp_path)
    del c.validation_checks["active_share_ge_15"]
    drv = FakePortal()
    o, _ = go(c, drv, cfg)
    assert o.status == "FAIL_CLOSED" and "LOCAL_VALIDATION_UNKNOWN" in o.reason and drv.calls == []
    for k in ("json_parse", "schema", "ticker", "numeric", "whole_lot", "holdings_20_30", "tsmc_le_25", "other_le_10",
              "cash_lt_25", "active_share_ge_15", "dplan_order_consistency", "quant_fingerprint"):
        assert k in AU.REQUIRED_CHECKS


def test_file_uploaded_state_resumes_without_reupload(cfg, tmp_path):
    drv = FakePortal(after_submit=[ACC])
    o, rec = go(cand(tmp_path, state="FILE_UPLOADED"), drv, cfg)
    assert o.status == "ACCEPTED" and "upload" not in drv.calls
    assert [r[0] for r in rec] == ["server_validated", "submitted", "accepted"]
    drv2 = FakePortal(after_submit=[ACC], validation=("UNKNOWN", ""))       # page lost the result -> upload again
    o2, _ = go(cand(tmp_path, state="FILE_UPLOADED"), drv2, cfg)
    assert "upload" in drv2.calls and o2.status == "FAIL_CLOSED"


def test_page_identity_change_before_submit_fails_closed(cfg, tmp_path):
    class Flip(FakePortal):
        def read_trade_date(self):
            return T1 if "upload" not in self.calls else "2026-10-28"
    drv = Flip()
    o, _ = go(cand(tmp_path), drv, cfg)
    assert o.status == "FAIL_CLOSED" and "PAGE_IDENTITY_CHANGED_BEFORE_SUBMIT" in o.reason and "submit" not in drv.calls


def test_final_sha_change_before_submit_fails_closed(cfg, tmp_path):
    c = cand(tmp_path)

    class Tamper(FakePortal):
        def upload_file(self, path):
            super().upload_file(path)
            Path(path).write_text("{}", encoding="utf-8")
    drv = Tamper()
    o, _ = go(c, drv, cfg)
    assert "FINAL_SHA_CHANGED_BEFORE_SUBMIT" in o.reason and "submit" not in drv.calls


def test_execute_stage_signals_audit_and_fallback_fields(cfg, tmp_path, monkeypatch):
    from agent.ops import signals
    c = cand(tmp_path)
    monkeypatch.setattr(AU, "candidate_from_official_test", lambda t, o: c)
    monkeypatch.setattr(AU, "manual_e2e_completed", lambda o: True)
    drv = FakePortal(after_submit=[])
    r = AU.execute(T1, official_test=True, ops_cfg=cfg, now_fn=lambda: at("2026-10-26T08:20:00"),
                   driver_factory=lambda o, t: drv)
    assert r["outcome"]["status"] == "SUBMITTED_UNVERIFIED"
    names = [s["signal"] for s in signals.read(T1, cfg)]
    for sig in ("AUTO_UPLOAD_RUNNING", "FILE_UPLOADED", "SERVER_VALIDATED", "SUBMITTED", "MANUAL_UPLOAD_REQUIRED"):
        assert sig in names, sig
    rows = [json.loads(x) for x in (AU.evidence_dir(T1, cfg) / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["file_uploaded_at"] and rows[1]["server_validated_at"] and rows[2]["submitted_at"]
    assert rows[0]["generated_at"] and rows[0]["validated_at"] and rows[0]["portal_state"]["team_id"] == TEAM
    assert rows[0]["screenshot_references"] == ["evidence/file_uploaded.png"] and "page_text_references" in rows[0]
    m = r["manual"]
    assert m["login_state"] == "LOGGED_IN" and m["window_closes_at"].startswith("2026-10-26T08:55")
    assert m["portal_attempts_remaining"] == 25 and "portal_state" in m and m["window_minutes_left"] == 35.0
    assert any(c.sha256 in step for step in m["manual_steps"])


def test_execute_rejected_and_window_closed_signals(cfg, tmp_path, monkeypatch):
    from agent.ops import signals
    c = cand(tmp_path)
    monkeypatch.setattr(AU, "candidate_from_official_test", lambda t, o: c)
    monkeypatch.setattr(AU, "manual_e2e_completed", lambda o: True)
    AU.execute(T1, official_test=True, ops_cfg=cfg, now_fn=lambda: at("2026-10-26T07:00:00"),
               driver_factory=lambda o, t: FakePortal(validation=("FAIL", "C3 權重超限")))
    assert "REJECTED" in [s["signal"] for s in signals.read(T1, cfg)]
    AU.execute(T1, official_test=True, ops_cfg=cfg, now_fn=lambda: at("2026-10-26T07:00:00"),
               driver_factory=lambda o, t: FakePortal(window="CLOSED"))
    assert "WINDOW_CLOSED" in [s["signal"] for s in signals.read(T1, cfg)]


def test_datapack_stale_and_ready_checks(cfg, monkeypatch):
    import agent.ops.datapack as DP
    from agent.submission import handoff as H
    monkeypatch.setattr(ST, "compute", lambda *a, **k: {"state": "ACCEPTED"})
    monkeypatch.setattr(DP, "datapack_gate", lambda *a, **k: {"status": "BLOCKED", "reason": "DATAPACK_STALE"})
    st = H.datapack_handoff(T1, ops_cfg=cfg, run_mode="COMPETITION", now=at("2026-10-26T20:00:00"))
    assert st["datapack_status"] == "DATAPACK_REQUIRED" and st["start_source_next"] is None
    d = Path(cfg["paths"]["official_datapack_dir"])
    d.mkdir(parents=True, exist_ok=True)
    f = d / "dp.json"
    f.write_text("{}", encoding="utf-8")
    good = {"status": "PASS", "file": str(f), "settlement_date": T1, "schema_version": "3.0", "freshness": "FRESH",
            "official": {"nav": 1.0, "cash": 1.0, "holdings": {}}}
    monkeypatch.setattr(DP, "datapack_gate", lambda *a, **k: good)
    ok = H.datapack_handoff(T1, ops_cfg=cfg, run_mode="COMPETITION", now=at("2026-10-26T20:00:00"))
    assert ok["datapack_status"] == "DATAPACK_READY" and set(ok["datapack_checks"]) == {
        "team_id", "as_of_date", "schema", "nav", "cash", "holdings", "freshness", "sha256"}
    monkeypatch.setattr(DP, "datapack_gate", lambda *a, **k: dict(good, settlement_date="2026-10-21"))
    bad = H.datapack_handoff(T1, ops_cfg=cfg, run_mode="COMPETITION", now=at("2026-10-26T20:00:00"))
    assert bad["datapack_status"] == "DATAPACK_INVALID" and bad["start_source_next"] is None


def test_next_action_and_latest_status_fields():
    from agent.ops import scheduled_run as S
    base = {"run_mode": "COMPETITION", "status": "PASS"}
    assert S.next_action(dict(base), "ACCEPTED").startswith("WAIT_FOR_OFFICIAL_DATAPACK")
    assert S.next_action(dict(base, login_state="LOGIN_REQUIRED"), "READY_FOR_UPLOAD").startswith("LOGIN_REQUIRED")
    assert S.next_action(dict(base, manual_action_required=True), "READY_FOR_UPLOAD").startswith("MANUAL_UPLOAD")
    assert S.next_action(dict(base), "SUBMITTED").startswith("MANUAL_CHECK_REQUIRED")
    assert S.next_action(dict(base, blocked_reason="DATAPACK_MISSING"), None).startswith("DOWNLOAD_OFFICIAL_DATAPACK")
    st = S.ops_status_fields(dict(base, trade_date=T1), {"state": "READY_FOR_UPLOAD"})
    assert "datapack_status" in st and st["next_action"] and "NEXT_ACTION" in S.LOG_KEYS


def test_all_operational_signals_supported(cfg):
    from agent.ops import signals
    want = {"LOGIN_REQUIRED", "READY_FOR_UPLOAD", "AUTO_UPLOAD_RUNNING", "FILE_UPLOADED", "SERVER_VALIDATED",
            "SUBMITTED", "SUBMISSION_ACCEPTED", "REJECTED", "MANUAL_UPLOAD_REQUIRED", "SUBMISSION_WARNING_0800",
            "SUBMISSION_HIGH_WARNING_0815", "SUBMISSION_CRITICAL_WARNING_0845", "DATAPACK_REQUIRED", "WINDOW_CLOSED"}
    assert want <= set(signals.SIGNALS)
    with pytest.raises(ValueError):
        signals.emit("MADE_UP", T1, ops_cfg=cfg)


def test_driver_interface_aliases_and_window_only_status():
    drv = FakePortal(dialogs=["彈窗"], window="CLOSED")
    assert drv.read_window_state() == "CLOSED" and drv.detect_unexpected_modal() == ["彈窗"]
    for m in ("open_portal", "check_login", "read_team_id", "read_trade_date", "read_window_state", "read_attempts",
              "read_history", "read_strategy_doc_status", "detect_unexpected_modal", "detect_error_banner",
              "upload_file", "wait_upload_complete", "wait_server_validation", "read_validation_result", "submit",
              "read_submit_result", "verify_acceptance", "capture_screenshot", "capture_page_text", "close"):
        assert callable(getattr(PD.PlaywrightPortalDriver, m)), m
    a = PD.load_adapter()
    a = dict(a, wording=dict(a["wording"], x={"status": "PENDING_WINDOW_ONLY", "markers": ["送出成功"]}),
             selectors=dict(a["selectors"], y={"status": "PENDING_WINDOW_ONLY", "strategies": [{"by": "text", "text": "y"}]}))
    assert PD.wording_markers(a, "x") == []
    d = object.__new__(PD.PlaywrightPortalDriver)
    d.adapter, d.official_test = a, True
    with pytest.raises(PD.UIUnexpected, match="PENDING_WINDOW_ONLY"):
        d._locate("y", action=True)
    with pytest.raises(PD.UIUnexpected, match="PENDING_WINDOW_ONLY"):
        d._locate("y")


def test_adapter_entries_carry_source_and_confidence():
    for name, s in PD.load_adapter()["selectors"].items():
        assert s.get("status") in PD.ALL_STATUSES, name
        assert s.get("source") and s.get("confidence"), name
        if s["status"] not in PD.PENDING:
            assert s.get("strategies"), name
    for name, w in PD.load_adapter()["wording"].items():
        assert w.get("status") in PD.ALL_STATUSES, name


def test_e2e_plan_next_window(cfg, tmp_path):
    from agent.submission import e2e_plan as E
    plan = E.build_plan(at("2026-10-23T19:00:00"), cfg)
    assert plan["target_trade_date"] == "2026-10-27" and plan["is_first_competition_trade_date"]
    assert plan["window_opens"] == "2026-10-26T19:30:00+08:00" and plan["window_closes"] == "2026-10-27T08:55:00+08:00"
    assert plan["expected_filename"] == "D-Plan_TEAM_11442_2026-10-27.json"
    assert plan["E2E_PREPARATION_STATUS"] == "WAITING_FOR_DECISION_WINDOW"
    for k in ("preflight", "prepare_manual", "portal_discovery", "portal_readonly_test", "real_upload_manual",
              "verification_record", "datapack"):
        assert plan["commands"][k], k
    assert "--initial" in plan["commands"]["prepare_manual"]
    assert E.build_plan(at("2026-10-26T20:00:00"), cfg)["E2E_PREPARATION_STATUS"] == "DECISION_WINDOW_OPEN"
    assert E.build_plan(at("2026-10-27T08:40:00"), cfg)["E2E_PREPARATION_STATUS"] == "DECISION_WINDOW_CLOSED"
    pp, rp = E.write(plan, tmp_path / "plan.json", tmp_path / "runbook.md")
    md = rp.read_text(encoding="utf-8")
    assert "2026-10-27" in md and "readonly-test" in md and "MANUAL_UPLOAD_REQUIRED" in md
    assert json.loads(pp.read_text(encoding="utf-8"))["team_id"] == TEAM


# ---------------------------------------------------------------- real logged-in page observations (2026-10-23)
def test_login_classification_sso_hop_is_not_logged_out():
    a = PD.load_adapter()
    host = "fundaiagent.esun-ai-challenge.tw"
    kw = dict(nav_visible=False, login_marker_visible=False, adapter=a)
    assert PD.classify_login("https://esun-ai-challenge.tw/sso", host, **kw) == "IN_TRANSIT"   # logged-in sessions hop too
    assert PD.classify_login("https://esun-ai-challenge.tw/login", host, **kw) == "LOGIN_REQUIRED"
    assert PD.classify_login(f"https://{host}/docs", host, nav_visible=True, login_marker_visible=False,
                             adapter=a) == "LOGGED_IN"
    assert PD.classify_login(f"https://{host}/docs", host, nav_visible=True, login_marker_visible=True,
                             adapter=a) == "LOGIN_REQUIRED"
    assert PD.classify_login(f"https://{host}/docs", host, **kw) == "IN_TRANSIT"             # SPA still loading


def test_observed_page_texts_parse_exactly():
    a = PD.load_adapter()
    assert PD.parse_attempts("當日決策文件 D-Plan（單一 JSON）· 今日已繳交 0 / 25 次") == (0, 25)
    assert PD.parse_attempts("今日已繳交 3 / 25 次") == (3, 22)
    assert PD.parse_attempts("今日已繳交 25 / 25 次") == (25, 0)
    assert PD.parse_attempts("今日繳交次數") == (None, None)                                   # unreadable
    assert PD.parse_trade_date("本次繳交對應交易日 — · 目前沒有開放中的繳交窗口") is None
    assert PD.parse_trade_date("本次繳交對應交易日 2026-10-27 · 窗口開放中") == "2026-10-27"
    assert PD.parse_doc_status("ETF 投資策略說明文件\n未繳交", a) == "未繳交"
    assert PD.parse_doc_status("ETF 投資策略說明文件\n已繳交\n繳交期間", a) == "已繳交"          # observed 2026-10-24
    assert PD.parse_doc_status("ETF 投資策略說明文件\n處理中", a) is None                      # unseen status: not guessed
    assert PD.wording_markers(a, "no_open_window") == ["目前沒有開放中的繳交窗口"]
    assert "目前沒有繳交紀錄" in PD.wording_markers(a, "history_empty")
    for w in ("history_accepted", "history_rejected"):
        assert a["wording"][w]["status"] == "PENDING_WINDOW_ONLY" and PD.wording_markers(a, w) == []
    assert PD.wording_markers(a, "validation_pass") == ["檢核通過，待送出"]          # Issue #20, real submit 2026-10-27
    assert PD.wording_markers(a, "submit_success") == ["已收件"]


def test_real_rehearsal_validation_texts_classify_safely():
    """Verbatim panel texts from the real rehearsal upload (2026-10-23 23:28 / 23:31)."""
    a = PD.load_adapter()
    fail = ("檢核結果\n文件檢查未通過\n上傳即時檢查要項 · 送出後回報收件檢核\n目前為開賽前試繳：只檢核、不收件，"
            "正式繳交窗口開啟後才能送出。\n文件檢查未通過\n缺少下列項目：文件類型、① 資料來源 sources\n"
            "請修正後重新上傳；本次未存檔，也不計入當日繳交次數。")
    idle = "檢核結果\n待上傳\n上傳即時檢查要項 · 送出後回報收件檢核\n尚未上傳 · 上傳後於此顯示檢核結果\n試繳期間不收件"
    assert PD.classify(fail, a, "validation_pass", "validation_fail") == "FAIL"
    assert PD.classify(idle, a, "validation_pass", "validation_fail") == "UNKNOWN"   # idle panel is never a PASS
    assert PD.wording_markers(a, "validation_fail") == ["文件檢查未通過"]
    assert any(m in fail for m in PD.wording_markers(a, "rehearsal_not_collected"))
    assert any(m in idle for m in PD.wording_markers(a, "validation_pending"))
    assert a["selectors"]["validation_result_panel"]["strategies"][0] == {"by": "anchor_ancestor", "text": "檢核結果",
                                                                          "levels": 2}
