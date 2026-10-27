"""Issue #20 / PR #22: with the REAL config (auto_upload.enabled = true, method browser) every unsafe condition still
fails closed -- enabling the switch removes only the DISABLED gate, nothing else (fake portal; nothing real)."""
import copy
import json

import pytest

from agent.ops.common import load_ops_config, sha256_file
from agent.submission import auto_upload as AU
from agent.submission import portal_driver as PD
from tests.ops.test_issue4_portal import TEAM, at, cand
from tests.ops.test_issue20_auto_submission import FlowPortal, T, _doc_of, _evidence, _row

NOW = "2026-10-28T07:40:00"


@pytest.fixture
def real():
    ops = copy.deepcopy(load_ops_config())
    assert ops["auto_upload"]["enabled"] is True and ops["auto_upload"]["method"] == "browser"
    assert ops["team"]["competition_team_id"] == TEAM
    ops["auto_upload"].update(acceptance_timeout_s=0, acceptance_poll_s=0, validation_timeout_s=0)
    return ops


def comp(tmp_path, **kw):
    return cand(tmp_path, date=T, source="competition_final", **{"mode": "competition", **kw})


def gate(c, ops, *, now=NOW, e2e=True, mode="COMPETITION", **kw):
    return AU.gate(c, now=at(now), ops_cfg=ops, run_mode=mode, official_test=False, attempts_used=kw.pop("used", 0),
                   manual_e2e_done=e2e, **kw)


def test_enabled_config_passes_the_gate_only_for_a_clean_candidate(real, tmp_path):
    assert gate(comp(tmp_path), real) == []


def _bad_checks(tmp_path, key, value):
    c = comp(tmp_path)
    if value is None:
        c.validation_checks.pop(key)
    else:
        c.validation_checks[key], c.local_validation_ok = value, False
    return c


def _other_date_in_file(tmp_path):
    c = comp(tmp_path)
    c.file.write_text(json.dumps(dict(_doc_of(c), trade_date="2026-10-29")), encoding="utf-8")
    c.sha256 = sha256_file(c.file)
    return c


@pytest.mark.parametrize("make, kw, needle", [
    (lambda p: comp(p), dict(e2e=False), "MANUAL_E2E_NOT_COMPLETED"),
    (lambda p: comp(p), dict(now="2026-10-28T08:55:00"), "SUBMISSION_WINDOW_CLOSED"),
    (lambda p: comp(p), dict(now="2026-10-27T19:00:00"), "WINDOW_NOT_OPEN"),
    (lambda p: _bad_checks(p, "schema", None), {}, "LOCAL_VALIDATION_UNKNOWN"),
    (lambda p: _bad_checks(p, "active_share_ge_15", "FAIL"), {}, "LOCAL_VALIDATION_FAIL"),
    (lambda p: _bad_checks(p, "holdings_20_30", "FAIL"), {}, "LOCAL_VALIDATION_FAIL"),
    (lambda p: comp(p, team="TEAM_99999"), {}, "TEAM_ID_MISMATCH"),
    (_other_date_in_file, {}, "TRADE_DATE_MISMATCH"),
    (lambda p: comp(p), dict(used=3), "MAX_AUTOMATED_ATTEMPTS"),
    (lambda p: comp(p), dict(mode="PRECOMPETITION"), "PRECOMPETITION_AUTO_SUBMIT_FORBIDDEN"),
    (lambda p: comp(p, mode="dry-run"), {}, "NOT_A_COMPETITION_FINAL"),
])
def test_enabled_config_still_fails_closed(real, tmp_path, make, kw, needle):
    assert any(f.startswith(needle) for f in gate(make(tmp_path), real, **kw)), needle


def test_enabled_config_sha_mismatch_fails_closed(real, tmp_path):
    c = comp(tmp_path)
    c.sha256 = "0" * 64
    assert any(f.startswith("SHA_MISMATCH") for f in gate(c, real))


def _run(c, drv, ops, now=NOW):
    rec = []
    o = AU.run(c, drv, now_fn=lambda: at(now), ops_cfg=ops, run_mode="COMPETITION", official_test=False,
               attempts_used=0, manual_e2e_done=True, record=lambda stage, **kw: rec.append((stage, kw)))
    return o, rec


@pytest.mark.parametrize("kw, status, needle", [
    (dict(login="LOGIN_REQUIRED"), "LOGIN_REQUIRED", "LOGIN_STATE"),
    (dict(login=["LOGGED_IN", "LOGIN_REQUIRED"]), "LOGIN_REQUIRED", "LOGIN_EXPIRED_MID_RUN"),
    (dict(team="TEAM_00001"), "FAIL_CLOSED", "PAGE_TEAM_ID"),
    (dict(date="2026-10-29"), "FAIL_CLOSED", "PAGE_TRADE_DATE"),
    (dict(validation=("UNKNOWN", "???")), "FAIL_CLOSED", "VALIDATION_RESULT_UNKNOWN"),
    (dict(upload_raises=PD.UIUnexpected("UNKNOWN_SELECTOR dplan_file_input")), "FAIL_CLOSED", "UNKNOWN_SELECTOR"),
    (dict(dialogs=["系統公告"]), "FAIL_CLOSED", "UNEXPECTED_MODAL"),
    (dict(pre=_evidence(None, rows=[_row(), _row(when="x")])), "FAIL_CLOSED", "HISTORY_AMBIGUOUS"),
])
def test_enabled_runner_fails_closed_on_portal_problems(real, tmp_path, kw, status, needle):
    kw.setdefault("pre", _evidence(None, rows=[]))
    drv = FlowPortal(date=kw.pop("date", T), pending=PD.submit_flow_pending(PD.load_adapter()), **kw)
    o, _ = _run(comp(tmp_path), drv, real)
    assert o.status == status and needle in o.reason and "submit" not in drv.calls
    assert AU.submission_status(o.status) == "BLOCKED" and o.manual_action_required


def test_enabled_runner_submits_end_to_end_with_the_real_adapter(real, tmp_path):
    """Owner Decision 2026-10-27: with the real adapter nothing blocks the submit step; the run uploads, validates,
    submits (bounded exploration in the real driver) and verifies -> SUBMISSION_CONFIRMED."""
    assert PD.submit_flow_pending(PD.load_adapter()) == []
    c = comp(tmp_path)
    drv = FlowPortal(date=T, pre=_evidence(None, rows=[]), post=_evidence(_doc_of(c)),
                     pending=PD.submit_flow_pending(PD.load_adapter()))
    o, rec = _run(c, drv, real)
    assert o.status == "SUBMISSION_CONFIRMED" and drv.calls.count("submit") == 1
    assert [s for s, _ in rec][:3] == ["file_uploaded", "server_validated", "submitted"]


def test_enabled_runner_unknown_submission_is_never_success(real, tmp_path):
    drv = FlowPortal(date=T, pre=_evidence(None, rows=[]), post=_evidence(None, rows=[]), submit_result=("UNKNOWN", ""))
    o, _ = _run(comp(tmp_path), drv, real)
    assert o.status == "SUBMITTED_UNVERIFIED" and drv.calls.count("submit") == 1 and o.manual_action_required
