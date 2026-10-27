"""Issue #20 — production auto-submission (fake portal only; nothing here touches the real portal):
SUBMISSION_CONFIRMED semantics, manual-E2E gate, idempotency, retry, locks, 08:30 / 08:55 hard stops, 07:30 morning
FINAL (supersede rules), PREDICTION_STATUS vs SUBMISSION_STATUS, scheduler scripts."""
import copy
import json
from datetime import datetime
from pathlib import Path

import pytest

import agent.ops.final  # noqa: F401  (bound to the real active_final before any test patches it)
from agent.ops import morning_final as MF
from agent.ops import scheduled_run as S
from agent.ops.production_lock import production_lock
from agent.submission import auto_upload as AU
from agent.submission import confirmation as C
from agent.submission import portal_driver as PD
from agent.submission.receipt import CONFIRMATION_KEYS, Receipt, has_submission_confirmation, is_confirmed
from tests.ops.test_issue4_portal import TEAM, FakePortal, at, cand, cfg  # noqa: F401  (fixture re-export)

T = "2026-10-28"
ROOT = Path(__file__).resolve().parents[2]


def _row(date=T, status="已繳交", when="2026-10-27 19:52"):
    return {"text": f"第 2\t{date}\t{status}\t{when}\t回看", "cells": ["第 2", date, status, when, "回看"]}


def _evidence(doc, *, team=TEAM, rows=None, header=None, page="", json_text=None, review=True):
    return {"team_id": team, "page_trade_date": T, "dplan_status": "已繳交",
            "history_rows": [_row()] if rows is None else rows,
            "review": ({"header": header or f"第 2 交易日 · {T}\n2026-10-27 19:52 繳交",
                        "json_text": json_text if json_text is not None else json.dumps(doc, ensure_ascii=False)}
                       if review else None),
            "page_text": page}


def _doc(team=TEAM, date=T):
    return {"schema_version": "4.3", "team_id": team, "trade_date": date, "orders": [], "decisions": [], "pad": ""}


# ---------------------------------------------------------------- SUBMISSION_CONFIRMED (pure)
def test_confirmed_needs_every_check():
    r = C.evaluate(_evidence(_doc()), trade_date=T, team_id=TEAM, final_doc=_doc())
    assert r["status"] == C.CONFIRMED and all(r["checks"].values()) and tuple(r["checks"]) == CONFIRMATION_KEYS
    assert r["history_entry"].startswith("第 2\t2026-10-28\t已繳交")


def test_portal_key_reorder_and_number_types_still_match():
    d = _doc() | {"orders": [{"shares": 1000, "ticker": "2330"}]}
    reordered = json.dumps({"orders": [{"ticker": "2330", "shares": 1000.0}], "trade_date": T, "team_id": TEAM,
                            "schema_version": "4.3", "decisions": [], "pad": ""})
    r = C.evaluate(_evidence(d, json_text=reordered), trade_date=T, team_id=TEAM, final_doc=d)
    assert r["status"] == C.CONFIRMED


@pytest.mark.parametrize("kw, failed", [
    (dict(rows=[_row(status="未繳交")]), "submitted_marker_present"),                 # submitted marker missing
    (dict(rows=[]), "unique_matching_history_row"),                                    # history missing
    (dict(rows=[_row(date="2026-10-27")]), "unique_matching_history_row"),             # only another day's row
    (dict(review=False), "review_content_present"),                                    # review missing
    (dict(json_text="{not json"), "review_content_present"),
    (dict(team="TEAM_99999"), "team_match"),                                           # wrong TEAM on the page
    (dict(header="第 1 交易日 · 2026-10-27"), "trade_date_match"),                     # wrong trade date in review
    (dict(page="文件檢查未通過 缺少下列項目"), "no_validation_failure_marker"),          # validation failed marker
])
def test_not_confirmed_cases(kw, failed):
    r = C.evaluate(_evidence(_doc(), **kw), trade_date=T, team_id=TEAM, final_doc=_doc())
    assert r["status"] == C.NOT_CONFIRMED and failed in r["reasons"]


def test_sha_mismatch_review_content_differs():
    other = _doc() | {"orders": [{"ticker": "2330", "shares": 1000}]}
    r = C.evaluate(_evidence(other), trade_date=T, team_id=TEAM, final_doc=_doc())
    assert r["status"] == C.NOT_CONFIRMED and r["reasons"] == ["review_content_matches_final"]


def test_wrong_trade_date_in_final_json():
    r = C.evaluate(_evidence(_doc(date="2026-10-27")), trade_date=T, team_id=TEAM, final_doc=_doc(date="2026-10-27"))
    assert r["status"] == C.NOT_CONFIRMED and "trade_date_match" in r["reasons"]


def test_duplicate_history_rows_are_ambiguous():
    r = C.evaluate(_evidence(_doc(), rows=[_row(), _row(when="2026-10-28 07:40")]), trade_date=T, team_id=TEAM,
                   final_doc=_doc())
    assert r["status"] == C.AMBIGUOUS and r["matching_rows"] == 2


def test_rejection_marker_blocks_once_wording_is_confirmed():
    a = copy.deepcopy(PD.load_adapter())
    a["wording"]["history_rejected"] = {"status": "CONFIRMED_REAL_E2E", "markers": ["未通過"]}
    r = C.evaluate(_evidence(_doc(), rows=[{"text": f"第 2\t{T}\t已繳交 未通過\t-\t回看",
                                            "cells": ["第 2", T, "已繳交 未通過", "-", "回看"]}]),
                   trade_date=T, team_id=TEAM, final_doc=_doc(), adapter=a)
    assert r["status"] == C.NOT_CONFIRMED and "no_rejection_marker" in r["reasons"]


def test_pending_wording_never_matches_accepted():
    a = PD.load_adapter()
    assert PD.wording_markers(a, "history_accepted") == []                 # the portal shows no "accepted" word
    assert PD.wording_markers(a, "history_submitted") == ["已繳交"]


# ---------------------------------------------------------------- receipts / manual-E2E gate
def _conf_receipt(sha, **kw):
    base = dict(official_status="submitted", stage="submitted", history_entry=_row()["text"],
                confirmation={k: True for k in CONFIRMATION_KEYS})
    base.update(kw)
    return Receipt(T, TEAM, sha, "2026-10-27T19:52:00+08:00", "manual_web", "Owner", **base)


def test_receipt_confirmation_semantics():
    from dataclasses import asdict
    sha = "sha256:" + "d" * 64
    good = asdict(_conf_receipt(sha))
    assert not good.get("official_status") == "accepted" and has_submission_confirmation(good) and is_confirmed(good)
    assert _conf_receipt(sha).validate() == []
    for k in CONFIRMATION_KEYS:                                               # every single check is mandatory
        bad = dict(good, confirmation={**good["confirmation"], k: False})
        assert not is_confirmed(bad), k
    assert not is_confirmed(dict(good, history_entry=None))
    assert not is_confirmed(dict(good, official_status="pending"))


def _final(monkeypatch, sha, *, team=TEAM, mode="competition"):
    import agent.ops.package_submission as PS
    monkeypatch.setattr(PS, "active_final", lambda t, o=None: {"trade_date": t, "team_id": team, "sha256": sha,
                                                              "mode": mode, "file": f"D-Plan_{team}_{t}.json"}
                        if t == T else None)


def _write_receipt(cfg, r):
    from dataclasses import asdict
    from agent.submission.receipt import receipts_path
    p = receipts_path(T, cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(r) if not isinstance(r, dict) else r, ensure_ascii=False) + "\n")


def test_manual_e2e_gate_accepts_submission_confirmed(cfg, monkeypatch):
    sha = "sha256:" + "d" * 64
    _final(monkeypatch, sha)
    assert not AU.manual_e2e_completed(cfg)
    _write_receipt(cfg, _conf_receipt(sha))
    ev = AU.manual_e2e_evidence(cfg)
    assert ev["completed"] and ev["evidence"][0]["sha256"] == sha and ev["evidence"][0]["evidence"].startswith("第 2")


@pytest.mark.parametrize("kw, needle", [
    (dict(official_status="pending"), "no official acceptance evidence"),               # submitted only, unconfirmed
    (dict(confirmation={k: (k != "review_content_present") for k in CONFIRMATION_KEYS}), "SUBMISSION_CONFIRMED"),
    (dict(confirmation={k: (k != "unique_matching_history_row") for k in CONFIRMATION_KEYS}), "SUBMISSION_CONFIRMED"),
])
def test_manual_e2e_gate_rejects_incomplete_confirmation(cfg, monkeypatch, kw, needle):
    sha = "sha256:" + "d" * 64
    _final(monkeypatch, sha)
    _write_receipt(cfg, _conf_receipt(sha, **kw))
    ev = AU.manual_e2e_evidence(cfg)
    assert not ev["completed"] and needle in ev["rejected"][0]["reason"]


def test_manual_e2e_gate_rejects_wrong_team_sha_and_automation(cfg, monkeypatch):
    sha = "sha256:" + "d" * 64
    _final(monkeypatch, sha)
    _write_receipt(cfg, _conf_receipt("sha256:" + "e" * 64))                          # SHA mismatch
    r = _conf_receipt(sha)
    r.team_id = "TEAM_99999"
    _write_receipt(cfg, r)                                                            # wrong team
    a = _conf_receipt(sha)
    a.submission_method, a.confirmed_by = "browser_automation", "auto_upload"
    _write_receipt(cfg, a)                                                            # automation never counts
    ev = AU.manual_e2e_evidence(cfg)
    assert not ev["completed"] and len(ev["rejected"]) == 3


# ---------------------------------------------------------------- runner with a confirmation-capable fake portal
class Portal20(FakePortal):
    """FakePortal + read_confirmation_evidence: `pre` before 送出繳交, `post` after it."""
    def __init__(self, *, pre=None, post=None, **kw):
        super().__init__(**kw)
        self.pre, self.post = pre, post

    def read_confirmation_evidence(self, trade_date):
        self.calls.append("read_confirmation")
        return self.post if ("submit" in self.calls and self.post is not None) else self.pre


def comp(tmp_path, **kw):
    return cand(tmp_path, date=T, source="competition_final", mode="competition", **kw)


def go20(c, drv, cfg, *, now="2026-10-28T07:40:00", used=0, confirmed=(), prior=()):
    rec = []
    o = AU.run(c, drv, now_fn=lambda: at(now), ops_cfg=cfg, run_mode="COMPETITION", official_test=False,
               attempts_used=used, manual_e2e_done=True, record=lambda stage, **kw: rec.append((stage, kw)),
               prior_shas=prior, confirmed_shas=confirmed)
    return o, rec


def _doc_of(c):
    return json.loads(c.file.read_text(encoding="utf-8"))


def test_auto_upload_submit_success_confirmed(cfg, tmp_path):
    c = comp(tmp_path)
    drv = Portal20(date=T, pre=_evidence(None, rows=[]), post=_evidence(_doc_of(c)))
    o, rec = go20(c, drv, cfg)
    assert o.status == "SUBMISSION_CONFIRMED" and drv.calls.count("upload") == 1 and drv.calls.count("submit") == 1
    assert [s for s, _ in rec] == ["file_uploaded", "server_validated", "submitted", "submitted"]
    assert rec[-1][1]["official_status"] == "submitted" and all(rec[-1][1]["confirmation"].values())
    assert AU.submission_status(o.status) == "SUBMISSION_CONFIRMED" and not o.manual_action_required


def test_upload_failure_fails_closed_without_submit(cfg, tmp_path):
    drv = Portal20(date=T, pre=_evidence(None, rows=[]), upload_raises=RuntimeError("input detached"))
    o, _ = go20(comp(tmp_path), drv, cfg)
    assert o.status == "FAIL_CLOSED" and "submit" not in drv.calls and AU.submission_status(o.status) == "BLOCKED"


def test_submit_failure_is_rejected(cfg, tmp_path):
    drv = Portal20(date=T, pre=_evidence(None, rows=[]), submit_result=("FAIL", "目前不在繳交時間內，本次未送出。"))
    o, rec = go20(comp(tmp_path), drv, cfg)
    assert o.status == "REJECTED" and rec[-1][0] == "rejected"


def test_unknown_submit_result_is_verified_read_only_then_confirmed(cfg, tmp_path):
    c = comp(tmp_path)
    drv = Portal20(date=T, pre=_evidence(None, rows=[]), post=_evidence(_doc_of(c)), submit_result=("UNKNOWN", ""))
    o, _ = go20(c, drv, cfg)
    assert o.status == "SUBMISSION_CONFIRMED" and drv.calls.count("submit") == 1


def test_unknown_submit_result_without_history_is_never_success(cfg, tmp_path):
    drv = Portal20(date=T, pre=_evidence(None, rows=[]), post=_evidence(None, rows=[]), submit_result=("UNKNOWN", ""))
    o, rec = go20(comp(tmp_path), drv, cfg)
    assert o.status == "SUBMITTED_UNVERIFIED" and "MANUAL_CHECK_REQUIRED" in o.reason
    assert drv.calls.count("submit") == 1 and o.manual_action_required          # no blind second click


def test_submitted_but_review_missing_is_not_confirmed(cfg, tmp_path):
    c = comp(tmp_path)
    drv = Portal20(date=T, pre=_evidence(None, rows=[]), post=_evidence(_doc_of(c), review=False))
    o, _ = go20(c, drv, cfg)
    assert o.status == "SUBMITTED_UNVERIFIED" and "review_content_present" in o.reason


def test_ambiguous_history_after_submit_is_manual(cfg, tmp_path):
    c = comp(tmp_path)
    drv = Portal20(date=T, pre=_evidence(None, rows=[]),
                   post=_evidence(_doc_of(c), rows=[_row(), _row(when="2026-10-27 19:59")]))
    o, _ = go20(c, drv, cfg)
    assert o.status == "SUBMITTED_UNVERIFIED" and "ambiguous" in o.reason


def test_already_submitted_on_portal_never_uploads(cfg, tmp_path):
    c = comp(tmp_path)
    drv = Portal20(date=T, pre=_evidence(_doc_of(c)))
    o, rec = go20(c, drv, cfg)
    assert o.status == "ALREADY_SUBMITTED" and "upload" not in drv.calls and "submit" not in drv.calls
    assert rec[0][0] == "submitted" and rec[0][1]["official_status"] == "submitted"


def test_duplicate_history_before_upload_fails_closed(cfg, tmp_path):
    c = comp(tmp_path)
    drv = Portal20(date=T, pre=_evidence(_doc_of(c), rows=[_row(), _row(when="x")]))
    o, _ = go20(c, drv, cfg)
    assert o.status == "FAIL_CLOSED" and "HISTORY_AMBIGUOUS" in o.reason and "upload" not in drv.calls


def test_earlier_different_submission_on_portal_fails_closed(cfg, tmp_path):
    """A row for T that is not this FINAL (e.g. an unrecorded manual submission) or whose review cannot be read:
    never upload / submit over it -- a human checks (Owner: unknown -> read-only verify first, no blind action)."""
    c = comp(tmp_path)
    old = _doc_of(c) | {"orders": [{"ticker": "2330", "shares": 1000}]}
    for pre in (_evidence(old), _evidence(_doc_of(c), review=False)):
        drv = Portal20(date=T, pre=pre, post=_evidence(_doc_of(c)))
        o, _ = go20(c, drv, cfg)
        assert o.status == "FAIL_CLOSED" and "HISTORY_ROW_EXISTS_UNCONFIRMED" in o.reason
        assert "upload" not in drv.calls and "submit" not in drv.calls


class FlowPortal(Portal20):
    """Portal20 with the real driver's submit-flow guard (adapter statuses) and click tracking."""
    def __init__(self, *, pending=(), **kw):
        super().__init__(**kw)
        self.pending = list(pending)

    def submit_flow_pending(self):
        return self.pending


def test_unconfirmed_submit_flow_stops_after_server_validated(cfg, tmp_path):
    drv = FlowPortal(date=T, pre=_evidence(None, rows=[]), pending=["submit_confirmation_modal", "submit_success"])
    o, rec = go20(comp(tmp_path), drv, cfg)
    assert o.status == "FAIL_CLOSED" and "SUBMIT_FLOW_UNCONFIRMED" in o.reason and "submit" not in drv.calls
    assert [s for s, _ in rec] == ["file_uploaded", "server_validated"] and o.manual_action_required
    assert AU.submission_status(o.status) == "BLOCKED"


def test_submit_exception_after_click_is_verified_read_only(cfg, tmp_path):
    c = comp(tmp_path)
    drv = FlowPortal(date=T, pre=_evidence(None, rows=[]), post=_evidence(_doc_of(c)),
                     submit_raises=RuntimeError("confirm dialog vanished"), raises_after_click=True)
    o, rec = go20(c, drv, cfg)
    assert o.status == "SUBMISSION_CONFIRMED" and drv.calls.count("submit") == 1
    assert "SUBMIT_RESULT_UNKNOWN" in rec[2][1]["message"] and rec[2][0] == "submitted"
    drv2 = FlowPortal(date=T, pre=_evidence(None, rows=[]), post=_evidence(None, rows=[]),
                      submit_raises=RuntimeError("timeout"), raises_after_click=True)
    o2, rec2 = go20(comp(tmp_path), drv2, cfg)
    assert o2.status == "SUBMITTED_UNVERIFIED" and drv2.calls.count("submit") == 1      # never clicked twice
    assert rec2[-1][0] == "submitted" and rec2[-1][1]["official_status"] == "pending"


def test_submit_refused_before_click_is_plain_fail_closed(cfg, tmp_path):
    drv = FlowPortal(date=T, pre=_evidence(None, rows=[]), submit_raises=PD.UIUnexpected("SUBMIT_BUTTON_NOT_AVAILABLE"))
    o, rec = go20(comp(tmp_path), drv, cfg)
    assert o.status == "FAIL_CLOSED" and "SUBMIT_BUTTON_NOT_AVAILABLE" in o.reason
    assert "submitted" not in [s for s, _ in rec]


def _adapter_with(**status):
    a = copy.deepcopy(PD.load_adapter())
    for k, v in status.items():
        if k in a["selectors"]:
            a["selectors"][k]["status"] = v
        else:
            a["wording"][k] = {"status": v, "markers": ["<verbatim>"] if v == "CONFIRMED_REAL_E2E" else []}
    return a


def test_submit_flow_pending_on_real_adapter_lists_only_window_only_items():
    assert PD.submit_flow_pending(PD.load_adapter()) == ["submit_confirmation_modal", "submit_confirm_button",
                                                         "validation_pass", "submit_success"]
    ok = dict(validation_pass="CONFIRMED_REAL_E2E", submit_success="CONFIRMED_REAL_E2E")
    assert PD.submit_flow_pending(_adapter_with(submit_confirmation_modal="CONFIRMED_REAL_E2E",
                                                submit_confirm_button="CONFIRMED_REAL_E2E", **ok)) == []
    assert PD.submit_flow_pending(_adapter_with(submit_confirmation_modal=PD.NOT_PRESENT,
                                                submit_confirm_button=PD.NOT_PRESENT, **ok)) == []
    mixed = PD.submit_flow_pending(_adapter_with(submit_confirmation_modal=PD.NOT_PRESENT, **ok))
    assert mixed == ["submit_confirm_button"]
    assert PD.submit_flow_pending(_adapter_with(submit_confirmation_modal="OWNER_OBSERVED_LABEL",
                                                submit_confirm_button="CONFIRMED_REAL_E2E", **ok))
    no_markers = _adapter_with(submit_confirmation_modal=PD.NOT_PRESENT, submit_confirm_button=PD.NOT_PRESENT, **ok)
    no_markers["wording"]["submit_success"]["markers"] = []
    assert PD.submit_flow_pending(no_markers) == ["submit_success"]


def test_real_driver_submit_refuses_unconfirmed_flow_before_any_click():
    drv = PD.PlaywrightPortalDriver.__new__(PD.PlaywrightPortalDriver)
    drv.adapter = PD.load_adapter()
    drv.read_page_state = lambda: pytest.fail("must refuse before touching the page")
    with pytest.raises(PD.UIUnexpected, match="SUBMIT_FLOW_UNCONFIRMED"):
        drv.submit()
    assert drv.submit_clicked is False


def test_idempotency_key_local_receipt_blocks_before_browser(cfg, tmp_path):
    c = comp(tmp_path)
    o, rec = go20(c, None, cfg, confirmed=(c.sha256,))                    # driver None: never touched
    assert o.status == "ALREADY_SUBMITTED" and rec == [] and AU.submission_status(o.status) == "SUBMISSION_CONFIRMED"
    o2, _ = go20(comp(tmp_path, state="SUBMISSION_CONFIRMED"), None, cfg)
    assert o2.status == "ALREADY_SUBMITTED"


def test_retry_after_unknown_only_verifies(cfg, tmp_path):
    c = comp(tmp_path, state="SUBMITTED")
    drv = Portal20(date=T, pre=_evidence(None, rows=[]))
    o, _ = go20(c, drv, cfg, used=1)
    assert o.status == "SUBMITTED_UNVERIFIED" and "upload" not in drv.calls and "submit" not in drv.calls
    drv2 = Portal20(date=T, pre=_evidence(_doc_of(c)))                       # history now shows it -> stop re-sending
    o2, _ = go20(c, drv2, cfg, used=1)
    assert o2.status == "ALREADY_SUBMITTED" and "submit" not in drv2.calls


def test_retry_is_bounded_and_same_sha_only(cfg, tmp_path):
    c = comp(tmp_path)
    o, _ = go20(c, Portal20(date=T, pre=_evidence(None, rows=[])), cfg, used=3)
    assert o.status == "FAIL_CLOSED" and "MAX_AUTOMATED_ATTEMPTS" in o.reason
    o2, _ = go20(c, Portal20(date=T, pre=_evidence(None, rows=[])), cfg, prior=("sha256:" + "9" * 64,))
    assert "DIFFERENT_SHA_RETRY_BLOCKED" in o2.reason


@pytest.mark.parametrize("now, status", [
    ("2026-10-28T08:29:59", "SUBMISSION_CONFIRMED"),     # before 08:30
    ("2026-10-28T08:30:00", "SUBMISSION_CONFIRMED"),     # exactly 08:30: existing FINAL may still be submitted
    ("2026-10-28T08:40:00", "SUBMISSION_CONFIRMED"),     # after 08:30, before 08:55
    ("2026-10-28T08:54:59", "SUBMISSION_CONFIRMED"),
    ("2026-10-28T08:55:00", "WINDOW_CLOSED"),            # exactly 08:55: no upload / submit
    ("2026-10-28T09:10:00", "WINDOW_CLOSED"),            # after 08:55
])
def test_submission_hard_stop_times(cfg, tmp_path, now, status):
    c = comp(tmp_path)
    drv = Portal20(date=T, pre=_evidence(None, rows=[]), post=_evidence(_doc_of(c)))
    o, _ = go20(c, drv, cfg, now=now)
    assert o.status == status
    if status == "WINDOW_CLOSED":
        assert "upload" not in drv.calls and "submit" not in drv.calls


def test_wrong_team_and_trade_date_on_page_fail_closed(cfg, tmp_path):
    o, _ = go20(comp(tmp_path), Portal20(date=T, team="TEAM_99999", pre=_evidence(None, rows=[])), cfg)
    assert o.status == "FAIL_CLOSED" and "PAGE_TEAM_ID" in o.reason
    o2, _ = go20(comp(tmp_path), Portal20(date="2026-10-27", pre=_evidence(None, rows=[])), cfg)
    assert o2.status == "FAIL_CLOSED" and "PAGE_TRADE_DATE" in o2.reason


def test_unconfirmed_validation_wording_never_submits(cfg, tmp_path):
    """The official 檢核 PASS wording is still PENDING_WINDOW_ONLY: a real driver times out -> manual."""
    drv = Portal20(date=T, pre=_evidence(None, rows=[]), validation_timeout=TimeoutError("no confirmed marker"))
    o, _ = go20(comp(tmp_path), drv, cfg)
    assert o.status == "FAIL_CLOSED" and "VALIDATION_TIMEOUT" in o.reason and "submit" not in drv.calls


def test_execute_submission_lock_contention_fails_closed(cfg, tmp_path, monkeypatch):
    c = comp(tmp_path)
    monkeypatch.setattr(AU, "candidate_from_competition", lambda t, o: c)
    monkeypatch.setattr(AU, "manual_e2e_completed", lambda o: True)
    cfg2 = dict(cfg, auto_upload=dict(cfg["auto_upload"], lock_timeout_s=0.2))
    started = []
    with AU.submission_lock(T, cfg2, 1):
        r = AU.execute(T, official_test=False, ops_cfg=cfg2, now_fn=lambda: at("2026-10-28T07:40:00"),
                       run_mode="COMPETITION", driver_factory=lambda o, t: started.append(1))
    assert r["outcome"]["status"] == "FAIL_CLOSED" and "LOCK_UNAVAILABLE" in r["outcome"]["reason"] and not started
    assert r["submission_status"] == "BLOCKED" and r["manual"]["signal"] == "MANUAL_UPLOAD_REQUIRED"


def test_execute_end_to_end_confirmed_and_idempotent(cfg, tmp_path, monkeypatch):
    from agent.ops import signals
    from agent.submission.manual import ManualSubmissionProvider
    c = comp(tmp_path)
    _final(monkeypatch, c.sha256)
    monkeypatch.setattr(ManualSubmissionProvider, "_final", lambda self, d: {"sha256": c.sha256, "team_id": TEAM,
                        "trade_date": T, "mode": "competition", "file": c.file.name})
    monkeypatch.setattr(AU, "candidate_from_competition", lambda t, o: c)
    monkeypatch.setattr(AU, "manual_e2e_completed", lambda o: True)
    drv = Portal20(date=T, pre=_evidence(None, rows=[]), post=_evidence(_doc_of(c)))
    r = AU.execute(T, official_test=False, ops_cfg=cfg, now_fn=lambda: at("2026-10-28T07:40:00"),
                   run_mode="COMPETITION", driver_factory=lambda o, t: drv)
    assert r["outcome"]["status"] == "SUBMISSION_CONFIRMED", r["outcome"]["reason"]
    assert r["submission_status"] == "SUBMISSION_CONFIRMED"
    assert r["idempotency_key"] == [T, TEAM, c.sha256]
    assert any(s["signal"] == "SUBMISSION_CONFIRMED" for s in signals.read(T, cfg))
    assert AU.confirmed_shas(T, TEAM, cfg) == (c.sha256,)
    second = []
    r2 = AU.execute(T, official_test=False, ops_cfg=cfg, now_fn=lambda: at("2026-10-28T07:45:00"),
                    run_mode="COMPETITION", driver_factory=lambda o, t: second.append(1))
    assert r2["outcome"]["status"] == "ALREADY_SUBMITTED" and not second          # no browser, no second upload


def test_status_reports_submission_confirmed_not_accepted(fixture_store, ops_cfg):
    from agent.submission import handoff as H
    from agent.submission import status as ST
    from agent.submission.receipt import record_receipt
    from tests.ops.test_competition_day import CLK1, T1, run
    s = run(fixture_store, ops_cfg, T1, CLK1, initial=True)
    r = Receipt(T1, "TEAM_TEST", s["sha256"], "2026-10-26T07:40:00+08:00", "manual_web", "Owner",
                official_status="submitted", stage="submitted", history_entry=f"第 1\t{T1}\t已繳交\t07:40\t回看",
                confirmation={k: True for k in CONFIRMATION_KEYS})
    assert record_receipt(r, ops_cfg)["state"] == "SUBMISSION_CONFIRMED"           # base state machine
    st = ST.compute(T1, now=at("2026-10-26T07:50:00"), ops_cfg=ops_cfg)
    assert st["state"] == "SUBMISSION_CONFIRMED" and st["state"] != "ACCEPTED" and st["confirmation"]
    assert ST.compute(T1, now=at("2026-10-26T09:00:00"), ops_cfg=ops_cfg)["state"] == "SUBMISSION_CONFIRMED"
    assert H.datapack_handoff(T1, ops_cfg=ops_cfg, run_mode="PRECOMPETITION", now=at("2026-10-26T20:00:00"))["accepted"]


# ---------------------------------------------------------------- PREDICTION_STATUS vs SUBMISSION_STATUS
@pytest.mark.parametrize("rec, sub", [
    ({"status": "PASS", "run_mode": "COMPETITION", "auto_upload_status": "FAIL_CLOSED"}, "BLOCKED"),
    ({"status": "PASS", "run_mode": "COMPETITION", "auto_upload_status": "SUBMISSION_CONFIRMED"}, "SUBMISSION_CONFIRMED"),
    ({"status": "PASS", "run_mode": "COMPETITION", "auto_upload_status": "DISABLED"}, "MANUAL_UPLOAD_REQUIRED"),
    ({"status": "PASS", "run_mode": "COMPETITION", "submission_state": "SUBMISSION_CONFIRMED"}, "SUBMISSION_CONFIRMED"),
    ({"status": "BLOCKED", "run_mode": "COMPETITION"}, "NOT_RUN"),
    ({"status": "PASS", "run_mode": "PRECOMPETITION"}, "NOT_APPLICABLE"),
])
def test_prediction_and_submission_status_are_separate(rec, sub):
    out = S.split_status(dict(rec))
    assert out["prediction_status"] == rec["status"] and out["submission_status"] == sub


# ---------------------------------------------------------------- production lock (19:30 vs 07:30)
def test_1930_run_blocks_on_lock_contention_without_running(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "LOG_DIR", tmp_path / "scheduled")
    monkeypatch.setattr(S, "LATEST", tmp_path / "scheduled" / "latest_status.json")
    monkeypatch.setattr(S, "HISTORY", tmp_path / "scheduled" / "history.jsonl")
    monkeypatch.setattr(S, "PRODUCTION_LOCK_WAIT_S", 0.2)
    ran = []
    monkeypatch.setattr(S, "_run", lambda *a, **k: ran.append(1))
    with production_lock(tmp_path / "locks", wait_s=1):                    # the 07:30 run holds it (pid alive)
        rec = S.run(now=at("2026-10-27T19:30:00"))
    assert rec["status"] == "BLOCKED" and rec["blocked_reason"] == "LOCK_UNAVAILABLE" and not ran
    assert rec["prediction_status"] == "BLOCKED"
    S.run(now=at("2026-10-27T19:31:00"))                                     # lock free again -> the run proceeds
    assert ran == [1]


def test_morning_blocks_on_lock_contention_without_deciding(monkeypatch, tmp_path):
    monkeypatch.setattr(MF, "LOG_DIR", tmp_path / "morning")
    monkeypatch.setattr(MF, "LOCK_WAIT_S", 0.2)
    called = []
    with production_lock(tmp_path / "locks", wait_s=1):                    # the 19:30 catch-up holds it
        rec = MF.run(now=at("2026-10-28T07:30:00"), cd_runner=lambda *a: called.append(1))
    assert rec["status"] == "BLOCKED" and rec["blocked_reason"] == "LOCK_UNAVAILABLE" and not called


def test_stale_lock_of_dead_process_is_recovered(tmp_path):
    lk = tmp_path / "locks" / "competition_production.lock"
    lk.parent.mkdir(parents=True)
    lk.write_text(json.dumps({"pid": 999999, "host": __import__("socket").gethostname(),
                              "created_at": "2026-10-27T19:30:00+08:00"}), encoding="utf-8")
    import os
    os.utime(lk, (0, 0))                                                     # old + owner pid gone -> recoverable
    with production_lock(tmp_path / "locks", wait_s=1, stale_after_s=1):
        pass
    assert list((tmp_path / "locks").glob("competition_production.lock.stale-*"))   # evidence kept, not deleted


# ---------------------------------------------------------------- 07:30 morning FINAL
HOL = {"2026-10-23"}


@pytest.mark.parametrize("now, action", [
    ("2026-10-28T07:30:00", "RUN"),
    ("2026-10-28T08:29:59", "RUN"),                       # before 08:30
    ("2026-10-28T08:30:00", "SUBMIT_EXISTING_ONLY"),      # exactly 08:30: no new decision
    ("2026-10-28T08:54:59", "SUBMIT_EXISTING_ONLY"),
    ("2026-10-28T08:55:00", "SKIP"),                      # exactly 08:55
    ("2026-10-31T07:30:00", "SKIP"),                      # Saturday
    ("2026-10-23T07:30:00", "SKIP"),                      # market closure
])
def test_morning_plan(now, action):
    assert MF.plan(at(now), HOL)["action"] == action


GOOD = {"trade_date": T, "mode": "competition", "status": "READY_TO_SUBMIT", "final_action": "KEPT_DIFFERENT",
        "data_health": "PASS", "validation": "PASS", "run_id": "20261028_073512_gitabc",
        "compliance_summary": {k: "PASS" for k in MF.REQUIRED_COMPLIANCE}}
PRIOR = {"trade_date": T, "mode": "competition", "sha256": "sha256:" + "1" * 64, "run_id": "20261027_194000_gitabc",
         "team_id": TEAM, "file": f"D-Plan_{TEAM}_{T}.json", "path": "submissions/x"}


def test_supersede_allowed_only_when_everything_passes():
    ok, why = MF.supersede_decision(GOOD, PRIOR, trade_date=T, now=at("2026-10-28T07:50:00"))
    assert ok, why


@pytest.mark.parametrize("change, needle", [
    (dict(final_action="KEPT_IDENTICAL"), "only a different decision"),
    (dict(data_health="WARN"), "freshness"),
    (dict(validation="FAIL"), "validation"),
    (dict(status="BLOCKED"), "run status"),
    (dict(compliance_summary={**GOOD["compliance_summary"], "Cash < 25%": "FAIL (26%)"}), "compliance"),
    (dict(trade_date="2026-10-27"), "trade date"),
    (dict(mode="dry-run"), "not a competition"),
])
def test_supersede_blocked(change, needle):
    ok, why = MF.supersede_decision(dict(GOOD, **change), PRIOR, trade_date=T, now=at("2026-10-28T07:50:00"))
    assert not ok and needle in why


def test_supersede_blocked_after_0830_and_without_prior():
    assert not MF.supersede_decision(GOOD, PRIOR, trade_date=T, now=at("2026-10-28T08:30:00"))[0]
    assert not MF.supersede_decision(GOOD, None, trade_date=T, now=at("2026-10-28T07:50:00"))[0]


class _State:
    """active FINAL + submission state for the morning-run tests (single active FINAL enforced by replace)."""
    def __init__(self, prior=PRIOR, state="READY_FOR_UPLOAD"):
        self.finals, self.state = ([dict(prior)] if prior else []), state

    def active(self, t, o=None):
        return self.finals[-1] if self.finals else None


def _morning(monkeypatch, tmp_path, st, *, summary=GOOD, submit=None, replace_ok=True, now="2026-10-28T07:30:00",
             portal=(True, "no portal submission for T")):
    import agent.ops.package_submission as PS
    from agent.submission import status as ST
    monkeypatch.setattr(MF, "LOG_DIR", tmp_path / "morning")
    monkeypatch.setattr(MF, "snapshot_summary", lambda *a, **k: None)
    monkeypatch.setattr(PS, "active_final", st.active)
    monkeypatch.setattr(ST, "compute", lambda t, **k: {"state": st.state})
    calls = {"cd": 0, "replace": [], "submit": 0}

    def cd(t, team, pre, started):
        calls["cd"] += 1
        return dict(summary, sha256=PRIOR["sha256"]), None

    def rep(t, team, run_id, *, reason, operator):
        calls["replace"].append((run_id, reason, operator))
        if not replace_ok:
            return {"ok": False, "reasons": ["refused"]}
        new = dict(PRIOR, sha256="sha256:" + "2" * 64, run_id=run_id)
        st.finals.append(new)
        return {"ok": True, "sha256": new["sha256"], "comparison": {"class": "DIFFERENT"}}

    def sub(t, mode, rec):
        calls["submit"] += 1
        if submit:
            submit(rec)
        else:
            rec.update(auto_upload_status="SUBMISSION_CONFIRMED")
            st.state = "SUBMISSION_CONFIRMED"
        return rec
    prep = lambda *a, **k: {"datapack_status": "PASS (FRESH)", "blocked_reason": None, "cd_mode": "competition",  # noqa: E731
                            "extra_args": []}
    rec = MF.run(now=at(now), cd_runner=cd, submit=sub, replace=rep, prepare=prep, portal_check=lambda t, o: portal)
    return rec, calls


def test_morning_supersede_success_keeps_one_active_final(monkeypatch, tmp_path):
    st = _State()
    rec, calls = _morning(monkeypatch, tmp_path, st)
    assert rec["status"] == "PASS" and rec["superseded"] and calls["replace"][0][2] == MF.OPERATOR
    assert rec["prior_final_sha256"] == PRIOR["sha256"] and rec["new_final_sha256"] == "sha256:" + "2" * 64
    assert rec["active_final_sha256"] == rec["new_final_sha256"]                    # exactly one active FINAL
    log = (tmp_path / "morning" / "supersede.jsonl").read_text(encoding="utf-8").splitlines()
    row = json.loads(log[0])
    assert row["prior_final_sha256"] == PRIOR["sha256"] and row["reason"] and row["evidence"]
    assert calls["submit"] == 1 and rec["submission_status"] == "SUBMISSION_CONFIRMED"
    assert json.loads((tmp_path / "morning" / "latest_status.json").read_text(encoding="utf-8"))["superseded"]


def test_morning_supersede_blocked_keeps_evening_final(monkeypatch, tmp_path):
    st = _State()
    bad = dict(GOOD, compliance_summary={**GOOD["compliance_summary"], "Holdings 20-30": "FAIL (31)"})
    rec, calls = _morning(monkeypatch, tmp_path, st, summary=bad)
    assert not rec["superseded"] and not calls["replace"] and "compliance" in rec["supersede_reason"]
    assert rec["active_final_sha256"] == PRIOR["sha256"] and calls["submit"] == 1


@pytest.mark.parametrize("portal", [(False, "the portal already has 1 submission row(s) for T (NOT_CONFIRMED)"),
                                    (False, "portal state unknown (['LOGIN_STATE_LOGIN_REQUIRED'])")])
def test_morning_never_supersedes_a_final_that_may_be_on_the_portal(monkeypatch, tmp_path, portal):
    st = _State()
    rec, calls = _morning(monkeypatch, tmp_path, st, portal=portal)
    assert not rec["superseded"] and not calls["replace"] and rec["active_final_sha256"] == PRIOR["sha256"]
    assert rec["supersede_reason"].startswith("evening FINAL kept: ") and portal[1] in rec["supersede_reason"]


def test_portal_clear_is_fail_closed(monkeypatch):
    monkeypatch.setattr(C, "verify", lambda t, **k: {"status": "NOT_CONFIRMED", "reasons": ["LOGIN_STATE_UNKNOWN"]})
    assert MF.portal_clear(T, {})[0] is False
    monkeypatch.setattr(C, "verify", lambda t, **k: {"status": "NOT_CONFIRMED", "matching_rows": 1, "reasons": []})
    assert MF.portal_clear(T, {})[0] is False
    monkeypatch.setattr(C, "verify", lambda t, **k: (_ for _ in ()).throw(RuntimeError("browser")))
    assert MF.portal_clear(T, {})[0] is False
    monkeypatch.setattr(C, "verify", lambda t, **k: {"status": "NOT_CONFIRMED", "matching_rows": 0, "reasons": []})
    assert MF.portal_clear(T, {}) == (True, "no portal submission for T")


def test_morning_identical_decision_keeps_evening_final(monkeypatch, tmp_path):
    rec, calls = _morning(monkeypatch, tmp_path, _State(), summary=dict(GOOD, final_action="KEPT_IDENTICAL"))
    assert not rec["superseded"] and not calls["replace"] and rec["active_final_sha256"] == PRIOR["sha256"]


def test_morning_after_confirmed_submission_makes_no_decision(monkeypatch, tmp_path):
    rec, calls = _morning(monkeypatch, tmp_path, _State(state="SUBMISSION_CONFIRMED"))
    assert calls["cd"] == 0 and calls["submit"] == 0 and rec["status"] == "SKIPPED"
    assert "ALREADY_SUBMITTED" in rec["blocked_reason"] and rec["submission_status"] == "SUBMISSION_CONFIRMED"


def test_morning_with_unverified_submission_never_decides_and_only_verifies(monkeypatch, tmp_path):
    rec, calls = _morning(monkeypatch, tmp_path, _State(state="SUBMITTED"))
    assert calls["cd"] == 0 and not calls["replace"] and rec["status"] == "SKIPPED"
    assert "SUBMISSION_UNVERIFIED" in rec["blocked_reason"] and calls["submit"] == 1     # read-only verify path


def test_morning_after_0830_submits_existing_final_only(monkeypatch, tmp_path):
    rec, calls = _morning(monkeypatch, tmp_path, _State(), now="2026-10-28T08:35:00")
    assert calls["cd"] == 0 and not calls["replace"] and calls["submit"] == 1
    assert rec["blocked_reason"] == "DECISION_WINDOW_CLOSED"


def test_morning_submission_failure_never_fails_the_prediction(monkeypatch, tmp_path):
    def fail(rec):
        rec.update(auto_upload_status="FAIL_CLOSED", manual_action_required=True)
    rec, _ = _morning(monkeypatch, tmp_path, _State(), submit=fail)
    assert rec["prediction_status"] == "PASS" and rec["submission_status"] == "BLOCKED"
    assert rec["manual_action_required"] is True


def test_morning_without_prior_final_marks_first(monkeypatch, tmp_path):
    st = _State(prior=None)
    rec, calls = _morning(monkeypatch, tmp_path, st, summary=dict(GOOD, final_action="MARKED"))
    assert rec["status"] == "PASS" and not calls["replace"] and not rec["superseded"]


# ---------------------------------------------------------------- scheduler scripts (07:30 new, 17:00 / 19:30 untouched)
def _ps(name):
    return (ROOT / "automation" / name).read_text(encoding="utf-8-sig")


def test_0730_task_registration():
    reg = _ps("register_morning_final_task.ps1")
    assert "$Name = 'AI_CUP_Competition_MorningFinal_0730'" in reg
    assert "-Daily -At ([datetime]'2026-10-28T07:30:00')" in reg
    assert "-StartWhenAvailable" in reg and "$Settings.WakeToRun = $false" in reg
    assert "-MultipleInstances IgnoreNew" in reg and "(New-TimeSpan -Minutes 85)" in reg     # stops by 08:55
    for other in ("AI_CUP_Precompetition_Evaluation_1700", "AI_CUP_Precompetition_DryRun_1930"):
        assert f"-TaskName '{other}'" not in reg and f"$Name = '{other}'" not in reg
    run = _ps("run_morning_final.ps1")
    assert "-m agent.ops.morning_final" in run and "exit" not in run.replace("Never calls `exit`.", "")


def test_1700_and_1930_wrappers_unchanged():
    ev = _ps("run_precompetition_evaluation.ps1")
    assert "& $Py -m agent.ops.daily_evaluation" in ev and "morning" not in ev and "auto_upload" not in ev
    sc = _ps("run_precompetition_scheduled.ps1")
    assert "$argsList = @('-m', 'agent.ops.scheduled_run')" in sc and "morning" not in sc
    assert S.TASK_NAME == "AI_CUP_Precompetition_DryRun_1930"


def test_1930_plan_and_evaluation_untouched():
    p = S.plan(at("2026-10-27T19:30:00"), HOL)
    assert p["action"] == "RUN" and p["trade_date"] == "2026-10-28" and p["run_kind"] == "NORMAL"
    src = (ROOT / "agent" / "ops" / "daily_evaluation.py").read_text(encoding="utf-8")
    assert "production_lock" not in src and "auto_upload" not in src             # evaluation writes no FINAL state


def test_quant_fingerprint_unchanged():
    from agent.ops.common import load_ops_config, sha256_file
    fz = load_ops_config()["freeze"]
    h = sha256_file(ROOT / fz["strategy_config"])
    assert (h if h.startswith("sha256:") else "sha256:" + h) == fz["strategy_sha256"] == \
        "sha256:f34fa02e924011b20c52a4bd42e961169f97e1950e76e04b7e78dc43ac23d2e0"


def test_observe_refuses_while_a_production_run_holds_the_profile(tmp_path, monkeypatch):
    ops = {"paths": {"ops_logs_dir": str(tmp_path / "logs" / "ops")}}
    assert PD.production_busy(ops) == []
    lk = production_lock(tmp_path / "logs" / "locks", wait_s=1)
    lk.acquire()
    try:
        monkeypatch.setattr(PD, "PlaywrightPortalDriver", lambda *a, **k: pytest.fail("no browser while busy"))
        r = PD.observe(minutes=0.01, ops_cfg=ops)
        assert r["status"] == "BUSY" and r["locks"] == ["competition_production.lock"]
    finally:
        lk.release()
    assert PD.production_busy(ops) == []


def test_observe_and_review_are_read_only():
    """observe() never clicks / types / uploads; open_review() clicks only the confirmed 回看 link and 關閉."""
    import inspect
    ob = inspect.getsource(PD.observe) + PD._MUTATION_JS + PD._DRAIN_JS
    for bad in (".click(", ".fill(", ".type(", "set_input_files", ".press(", "upload_file", "submit(", "accept(",
                "cookie", "localStorage", "sessionStorage", ".value", "storage_state"):
        assert bad not in ob, bad
    assert "dialog.dismiss()" in ob                      # a native confirm() is cancelled: nothing is ever submitted
    rv = inspect.getsource(PD.PlaywrightPortalDriver.open_review)
    assert rv.count(".click()") == 2 and "set_input_files" not in rv and "submit" not in rv
    a = PD.load_adapter()
    for name in ("history_review_link", "review_dialog", "review_content", "review_close_button", "dplan_section"):
        assert a["selectors"][name]["status"] == "CONFIRMED_REAL_E2E" and "Issue #20" in a["selectors"][name]["source"]


# ---------------------------------------------------------------- 19:30 live observation -> adapter proposal
def _snaps():
    base = {"buttons": [{"text": "送出繳交", "disabled": True}], "dialogs": [], "alerts": [], "mutations": [],
            "history": [], "dplan_status": "未繳交", "attempts": [0, 25], "window_status": "UNKNOWN",
            "submit_button": {"visible": True, "enabled": False}}
    return [
        dict(base, at="t0", validation_panel="待上傳", evidence=["e/observe_000.png"]),
        dict(base, at="t1", validation_panel="檢核通過 · 可送出", submit_button={"visible": True, "enabled": True},
             evidence=["e/observe_001.png"]),
        dict(base, at="t2", validation_panel="檢核通過 · 可送出", dialogs=["確認送出？ 送出後以此版本為準 取消 確認送出"],
             buttons=[{"text": "送出繳交"}, {"text": "取消"}, {"text": "確認送出"}], evidence=["e/observe_002.png"]),
        dict(base, at="t3", validation_panel="檢核通過 · 可送出", alerts=["繳交成功"], dplan_status="已繳交",
             mutations=[{"kind": "added", "tag": "div", "role": None, "text": "繳交成功"}],
             history=[{"text": "第 2\t2026-10-28\t已繳交\t2026-10-27 20:05\t回看"}], evidence=["e/observe_003.png"]),
        {"at": "t4", "native_dialog": {"type": "confirm", "message": "確定要送出嗎？"}},
    ]


def test_observation_report_proposes_only_new_verbatim_wording(tmp_path):
    from agent.submission import observation_report as R
    res = R.candidates(_snaps(), PD.load_adapter())
    texts = {k: [c["text"] for c in v] for k, v in res["items"].items()}
    assert texts["validation_pass"] == ["檢核通過 · 可送出"]                         # 待上傳 is known wording
    assert texts["submit_confirmation_modal"] == ["確認送出？ 送出後以此版本為準 取消 確認送出", "確定要送出嗎？"]
    assert texts["submit_confirm_button"] == ["取消", "確認送出"]                     # a human picks the confirm one
    assert texts["submit_success"] == ["繳交成功"]
    assert res["items"]["validation_pass"][0]["evidence"] == ["e/observe_001.png"]
    events = [t["event"] for t in res["timeline"]]
    assert "submit_button" in events and "dplan_status" in events and "native_dialog" in events
    d = tmp_path / "20261027_200000_observe"
    d.mkdir()
    (d / "observe.jsonl").write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in _snaps()), encoding="utf-8")
    R.report(d)
    md = (d / "adapter_proposal.md").read_text(encoding="utf-8")
    assert "PROPOSAL ONLY" in md and "## submit_success" in md and "繳交成功" in md


def test_observation_report_never_writes_the_adapter():
    import inspect

    from agent.submission import observation_report as R
    src = inspect.getsource(R)
    assert "portal_adapter.yaml\", \"w\"" not in src and "yaml.safe_dump" not in src and "write_text" in src
    assert all(x not in src for x in ("playwright", "cookie", ".click(", "set_input_files"))


def test_window_only_items_need_live_observation_evidence():
    """Every window-only item stays PENDING until confirmed; once confirmed it must cite a live observation folder
    (the runner's submit step depends on all four: portal_driver.submit_flow_pending)."""
    a = PD.load_adapter()
    entries = {"validation_pass": a["wording"]["validation_pass"], "submit_success": a["wording"]["submit_success"],
               "submit_confirmation_modal": a["selectors"]["submit_confirmation_modal"],
               "submit_confirm_button": a["selectors"]["submit_confirm_button"]}
    for name, e in entries.items():
        if e["status"] in PD.PENDING:
            assert name in PD.submit_flow_pending(a)
            continue
        assert e["status"] in ("CONFIRMED_REAL_E2E", PD.NOT_PRESENT), name
        assert "_observe" in e.get("source", "") and "Issue #20" in e.get("source", ""), name
        if name in ("validation_pass", "submit_success"):
            assert e.get("markers"), name
