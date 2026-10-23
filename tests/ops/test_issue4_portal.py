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
    return AU.Candidate(date, team, f, sha256_file(f), state, ok, source, mode, {"schema": "PASS" if ok else "FAIL"})


ACC = {"text": f"10-26 08:06 {FNAME} 已收件", "accepted": True, "rejected": False}
REJ = {"text": f"10-26 08:06 {FNAME} 未通過", "accepted": False, "rejected": True}


class FakePortal(PD.PortalDriver):
    def __init__(self, *, login="LOGGED_IN", team=TEAM, date=T1, window="UNKNOWN", attempts=(0, 25), history=None,
                 after_submit=None, validation=("PASS", "檢核通過"), submit_result=("OK", "已送出"), upload_raises=None,
                 submit_raises=None, dialogs=None, validation_timeout=None):
        self.login, self.team, self.date, self.window, self.attempts = login, team, date, window, attempts
        self.history, self.after = history or [], after_submit
        self.validation, self.submit_result = validation, submit_result
        self.upload_raises, self.submit_raises, self.dialogs = upload_raises, submit_raises, dialogs or []
        self.validation_timeout, self.calls, self.closed = validation_timeout, [], False

    def open_portal(self): self.calls.append("open")
    def check_login(self): return self.login
    def read_page_state(self): return {"url": "https://portal/docs", "window_status": self.window, "dialogs": self.dialogs,
                                       "unexpected_dialogs": self.dialogs}
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
    assert ops["auto_upload"]["enabled"] is False                                       # disabled pending REAL_E2E


def test_adapter_unconfirmed_entries_are_pending_and_never_guessed():
    inv = {r["element"]: r for r in PD.selector_inventory(PD.load_adapter())}
    for name in ("upload_button", "server_validation_pass_marker", "submit_confirmation_modal", "history_rows",
                 "trade_date", "team_id", "attempt_count", "accepted_history_marker"):
        assert inv[name]["status"] == "PENDING_REAL_E2E_SELECTOR" and inv[name]["strategies"] == []
    assert not any(r["usable_for_action_competition"] for r in inv.values())          # nothing CONFIRMED_REAL_E2E yet
    a = PD.load_adapter()
    for w in ("validation_pass", "validation_fail", "history_accepted", "submit_success"):
        assert a["wording"][w]["status"] == "PENDING_REAL_E2E_WORDING" and PD.wording_markers(a, w) == []
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
    with pytest.raises(PD.UIUnexpected, match="PENDING_REAL_E2E_SELECTOR"):
        d._locate("upload_button", action=True)
    with pytest.raises(PD.UIUnexpected, match="OWNER_OBSERVED_LABEL"):
        d._locate("submit_button", action=True)                  # COMPETITION needs CONFIRMED_REAL_E2E
    d.official_test = True
    with pytest.raises(PD.UIUnexpected, match="PENDING_REAL_E2E_SELECTOR"):
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
    (FakePortal(validation_timeout=TimeoutError("no panel")), "FAIL_CLOSED", "TimeoutError"),      # timeout
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
    monkeypatch.setattr(DP, "datapack_gate", lambda *a, **k: {"status": "PASS", "file": str(f), "settlement_date": T1})
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
    assert not AU.manual_e2e_completed(cfg)
    OT.record_upload(T1, "sha256:" + "a" * 64, "accepted", "已收件", "auto_upload", submission_id="X", ops_cfg=cfg)
    assert not AU.manual_e2e_completed(cfg)
    OT.record_upload(T1, "sha256:" + "a" * 64, "accepted", "已收件", "Owner", stage="submitted",
                     history_entry=ACC["text"], ops_cfg=cfg)
    assert AU.manual_e2e_completed(cfg)
