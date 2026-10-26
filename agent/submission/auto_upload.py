"""Guarded automated D-Plan upload (Issue #4) — FAIL CLOSED by design; `config/ops.yaml auto_upload.enabled` stays
false until a REAL_E2E in a valid window reaches official acceptance and the Owner approves enabling it.

Mechanism: normal browser automation of the human UI (agent/submission/portal_driver.py) in a profile the Owner
logged into interactively. The portal has NO documented participant API; its private /api is never called.

Lifecycle: READY_FOR_UPLOAD -> FILE_UPLOADED -> SERVER_VALIDATED -> SUBMITTED -> ACCEPTED / REJECTED.
ACCEPTED only with official history evidence (adapter wording `history_accepted`, verbatim); otherwise
SUBMITTED_UNVERIFIED + MANUAL_CHECK_REQUIRED. Never generates a decision; only uploads the EXISTING validated FINAL.

    .venv\\Scripts\\python.exe -m agent.submission.auto_upload --date T [--official-test] --check    # gate only
    .venv\\Scripts\\python.exe -m agent.submission.auto_upload --date T [--official-test] --run      # if enabled
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT  # noqa: E402
from agent.ops.common import TPE, load_ops_config, sha256_file, write_json, ymd  # noqa: E402
from agent.submission.portal_driver import UIUnexpected  # noqa: E402,F401  (re-exported)

OFFICIAL_DAILY_LIMIT = 25
UPLOADABLE = ("READY_FOR_UPLOAD", "FILE_UPLOADED", "SERVER_VALIDATED")
SUCCESS = ("ACCEPTED", "ALREADY_ACCEPTED")
# §10 local validation (official_test.full_local_validation): every item must be present AND PASS; missing = UNKNOWN
REQUIRED_CHECKS = ("json_parse", "schema", "ticker", "numeric", "team_id", "trade_date", "filename", "file_size",
                   "whole_lot", "holdings_20_30", "tsmc_le_25", "other_le_10", "cash_lt_25", "active_share_ge_15",
                   "quant_fingerprint", "dplan_order_consistency", "no_manual_override")


@dataclass
class Candidate:
    trade_date: str
    team_id: str
    file: Path
    sha256: str
    state: str
    local_validation_ok: bool
    source: str                    # "competition_final" | "official_test_package"
    final_mode: str | None = None
    validation_checks: dict = field(default_factory=dict)
    generated_at: str | None = None
    validated_at: str | None = None


@dataclass
class Outcome:
    status: str     # ACCEPTED | ALREADY_ACCEPTED | SUBMITTED_UNVERIFIED | REJECTED | LOGIN_REQUIRED | WINDOW_CLOSED | FAIL_CLOSED
    reason: str
    steps: list = field(default_factory=list)
    portal: dict = field(default_factory=dict)
    evidence: list = field(default_factory=list)

    @property
    def manual_action_required(self) -> bool:
        return self.status not in SUCCESS


def cfg_auto(ops_cfg: dict) -> dict:
    a = dict(ops_cfg.get("auto_upload") or {})
    a.setdefault("enabled", False)
    a.setdefault("method", "none")
    a.setdefault("max_automated_attempts", 3)
    a.setdefault("validation_timeout_s", 60)
    a.setdefault("acceptance_timeout_s", 120)
    a.setdefault("acceptance_poll_s", 10)
    return a


# ----------------------------------------------------------------------------- safety gate (pure)
def gate(c: Candidate, *, now: datetime, ops_cfg: dict, run_mode: str, official_test: bool, attempts_used: int,
         manual_e2e_done: bool, check_config: bool = True, prior_shas: tuple = ()) -> list[str]:
    from agent.config import load_official_rules
    from agent.ops import submission_window as SW
    from agent.ops.team import resolve
    a = cfg_auto(ops_cfg)
    f = []
    if check_config and not (a["enabled"] and a["method"] == "browser"):
        f.append("AUTO_UPLOAD_DISABLED (config/ops.yaml auto_upload.enabled / method)")
    if not (run_mode == "COMPETITION" or official_test):
        f.append("PRECOMPETITION_AUTO_SUBMIT_FORBIDDEN (only COMPETITION or explicit --official-test)")
    if official_test and c.source != "official_test_package":
        f.append("OFFICIAL_TEST_REQUIRES_SEALED_TEST_PACKAGE")
    if not official_test and (c.source != "competition_final" or c.final_mode != "competition"):
        f.append(f"NOT_A_COMPETITION_FINAL (source {c.source}, mode {c.final_mode})")
    if not manual_e2e_done:
        f.append("MANUAL_E2E_NOT_COMPLETED (a manual sealed-test run must reach official acceptance first)")
    team = resolve("COMPETITION", ops_cfg)
    if team["status"] != "OK" or c.team_id != team["team_id"]:
        f.append(f"TEAM_ID_MISMATCH ({c.team_id} vs configured {team['team_id']})")
    if c.state == "ACCEPTED":
        f.append("ALREADY_ACCEPTED (idempotent: never re-submit an accepted trade date)")
    elif c.state not in UPLOADABLE + ("SUBMITTED",):
        f.append(f"STATE_NOT_SUBMITTABLE ({c.state})")
    if not c.local_validation_ok:
        bad = [k for k, v in (c.validation_checks or {}).items() if v != "PASS"]
        f.append("LOCAL_VALIDATION_FAIL" + (f" {bad}" if bad else ""))
    missing = [k for k in REQUIRED_CHECKS if k not in (c.validation_checks or {})]
    if missing:
        f.append(f"LOCAL_VALIDATION_UNKNOWN {missing}")
    if any(s and s != c.sha256 for s in prior_shas):
        f.append("DIFFERENT_SHA_RETRY_BLOCKED (retries only for the same FINAL sha256)")
    fz = ops_cfg["freeze"]
    h = sha256_file(ROOT / fz["strategy_config"])
    if (h if h.startswith("sha256:") else "sha256:" + h) != fz["strategy_sha256"]:
        f.append("QUANT_FREEZE_FAIL")
    if not c.file.exists():
        f.append("FILE_MISSING")
    else:
        if sha256_file(c.file) != c.sha256:
            f.append("SHA_MISMATCH")
        limit = int((ops_cfg.get("submission") or {}).get("max_upload_bytes") or 2 * 1024 * 1024)
        if c.file.stat().st_size > limit:
            f.append(f"FILE_TOO_LARGE (> {limit} bytes)")
        want = load_official_rules().raw["dplan"]["filename_pattern"].format(team_id=c.team_id, trade_date=c.trade_date)
        if c.file.name != want:
            f.append(f"FILENAME_MISMATCH ({c.file.name} != {want})")
        try:
            doc = json.loads(c.file.read_text(encoding="utf-8"))
            if doc.get("trade_date") != c.trade_date:
                f.append(f"TRADE_DATE_MISMATCH ({doc.get('trade_date')})")
            if doc.get("team_id") != c.team_id:
                f.append(f"FILE_TEAM_MISMATCH ({doc.get('team_id')})")
        except ValueError:
            f.append("FILE_NOT_JSON")
    ph = SW.phase(c.trade_date, now, ops_cfg)
    if ph == "WINDOW_NOT_OPEN":
        f.append("WINDOW_NOT_OPEN")
    elif ph == "SUBMISSION_WINDOW_CLOSED":
        f.append("SUBMISSION_WINDOW_CLOSED (08:55: submit forbidden)")
    if attempts_used >= int(a["max_automated_attempts"]) and c.state != "SUBMITTED":
        f.append(f"MAX_AUTOMATED_ATTEMPTS ({attempts_used}/{a['max_automated_attempts']})")
    return f


# ----------------------------------------------------------------------------- runner
def run(c: Candidate, driver, *, now_fn, ops_cfg: dict, run_mode: str, official_test: bool, attempts_used: int,
        manual_e2e_done: bool, record, check_config: bool = True, prior_shas: tuple = (),
        portal: dict | None = None) -> Outcome:
    """`driver` implements portal_driver.PortalDriver. `record(stage, **fields)` persists official-stage evidence.
    `portal` (optional) is filled with what the page showed (shared with the recorder for the audit rows)."""
    from agent.ops import submission_window as SW
    a = cfg_auto(ops_cfg)
    fails = gate(c, now=now_fn(), ops_cfg=ops_cfg, run_mode=run_mode, official_test=official_test,
                 attempts_used=attempts_used, manual_e2e_done=manual_e2e_done, check_config=check_config,
                 prior_shas=prior_shas)
    if fails:
        if any(x.startswith("ALREADY_ACCEPTED") for x in fails):
            return Outcome("ALREADY_ACCEPTED", "; ".join(fails))
        if any(x.startswith("SUBMISSION_WINDOW_CLOSED") for x in fails):
            return Outcome("WINDOW_CLOSED", "; ".join(fails))
        return Outcome("FAIL_CLOSED", "; ".join(fails))
    o = Outcome("FAIL_CLOSED", "", portal=portal if portal is not None else {})

    def ev(tag):
        try:
            refs = driver.capture_evidence(tag) or []
        except Exception:  # noqa: BLE001
            refs = []
        o.evidence.extend(refs)
        return refs

    def open_window() -> bool:
        return SW.phase(c.trade_date, now_fn(), ops_cfg) == "DECISION_OPEN" or \
            SW.phase(c.trade_date, now_fn(), ops_cfg) == "DECISION_WINDOW_CLOSED"     # 08:30-08:55: existing FINAL only

    try:
        driver.open_portal()
        login = driver.check_login()
        o.portal["login_state"] = login
        o.steps.append(f"login {login}")
        if login != "LOGGED_IN":
            o.status, o.reason = "LOGIN_REQUIRED", f"LOGIN_STATE_{login} (the Owner must log in in the automation profile)"
            return o
        page = driver.read_page_state()
        o.portal.update(window_status=page.get("window_status"), url=page.get("url"))
        if page.get("unexpected_dialogs"):
            raise UIUnexpected(f"UNEXPECTED_MODAL {page['unexpected_dialogs'][:1]}")
        if page.get("window_status") == "CLOSED":
            o.status, o.reason = "WINDOW_CLOSED", "portal shows the submission window as closed"
            return o
        team, tdate = driver.read_team_id(), driver.read_trade_date()
        o.portal.update(team_id=team, trade_date=tdate)
        if team != c.team_id:
            raise UIUnexpected(f"PAGE_TEAM_ID {team!r} != {c.team_id}")
        if tdate != c.trade_date:
            raise UIUnexpected(f"PAGE_TRADE_DATE {tdate!r} != {c.trade_date}")
        used, remaining = driver.read_attempts()
        o.portal.update(attempts_used=used, attempts_remaining=remaining)
        if used is None or remaining is None:
            raise UIUnexpected("ATTEMPTS_UNREADABLE")
        hist = driver.read_history()
        mine = [r for r in hist if r.get("accepted") and (c.file.name in r.get("text", "") or c.sha256 in r.get("text", ""))]
        if mine:
            record("accepted", official_status="accepted", history_entry=mine[0]["text"], message="found in history",
                   evidence=ev("already_accepted"))
            o.status, o.reason = "ALREADY_ACCEPTED", "official history already shows this FINAL as accepted"
            return o
        if c.state == "SUBMITTED":                                   # idempotent: verify only, never resubmit
            return _verify(c, driver, o, record, a, ev)
        if remaining <= 0:
            raise UIUnexpected("OFFICIAL_ATTEMPT_LIMIT_REACHED")
        validated_on_page = False
        if c.state in ("FILE_UPLOADED", "SERVER_VALIDATED"):          # resume: the page may still hold the result
            res, text = driver.read_validation_result()
            validated_on_page = res == "PASS"
            if validated_on_page and c.state == "FILE_UPLOADED":
                record("server_validated", official_status="pending", validation_result="PASS", message=text,
                       evidence=ev("server_validated_resume"))
            o.steps.append(f"RESUME {c.state} page={res}")
        if not validated_on_page:
            if not open_window():
                o.status, o.reason = "WINDOW_CLOSED", "submission window closed before upload"
                return o
            driver.upload_file(c.file)
            record("file_uploaded", official_status="pending", message="file uploaded", evidence=ev("file_uploaded"))
            o.steps.append("FILE_UPLOADED")
            try:
                driver.wait_for_server_validation(float(a["validation_timeout_s"]))
            except UIUnexpected:
                raise
            except Exception as e:  # noqa: BLE001 - no result in time: uploaded but unknown -> a human checks
                ev("validation_timeout")
                o.status = "FAIL_CLOSED"
                o.reason = f"MANUAL_CHECK_REQUIRED: VALIDATION_TIMEOUT ({type(e).__name__}: {str(e)[:120]})"
                return o
            res, text = driver.read_validation_result()
            if res == "FAIL":
                record("rejected", official_status="rejected", validation_result="FAIL", message=text,
                       failure_reason=text, evidence=ev("validation_fail"))
                o.status, o.reason = "REJECTED", f"檢核結果 FAIL: {text}"
                o.steps.append("REJECTED")
                return o
            if res != "PASS":
                ev("validation_unknown")
                raise UIUnexpected(f"VALIDATION_RESULT_UNKNOWN ({text[:120]!r})")
            record("server_validated", official_status="pending", validation_result="PASS", message=text,
                   evidence=ev("server_validated"))
            o.steps.append("SERVER_VALIDATED")
        # pre-submit re-check: session, page identity, same FINAL bytes, validation still PASS, no modal, < 08:55
        if driver.check_login() != "LOGGED_IN":
            o.portal["login_state"] = "LOGIN_REQUIRED"
            o.status, o.reason = "LOGIN_REQUIRED", "LOGIN_EXPIRED_MID_RUN (session lost before submit; nothing submitted)"
            return o
        if driver.read_team_id() != c.team_id or driver.read_trade_date() != c.trade_date:
            raise UIUnexpected("PAGE_IDENTITY_CHANGED_BEFORE_SUBMIT")
        if sha256_file(c.file) != c.sha256:
            raise UIUnexpected("FINAL_SHA_CHANGED_BEFORE_SUBMIT")
        if driver.read_validation_result()[0] != "PASS":
            raise UIUnexpected("VALIDATION_NOT_PASS_BEFORE_SUBMIT")
        page = driver.read_page_state()
        if page.get("unexpected_dialogs"):
            raise UIUnexpected(f"UNEXPECTED_MODAL {page['unexpected_dialogs'][:1]}")
        if SW.phase(c.trade_date, now_fn(), ops_cfg) == "SUBMISSION_WINDOW_CLOSED":
            o.status, o.reason = "WINDOW_CLOSED", "08:55 reached before submit (stopped)"
            return o
        driver.submit()
        sres, stext = driver.read_submit_result()
        if sres == "FAIL":
            record("rejected", official_status="rejected", validation_result="PASS", message=stext, failure_reason=stext,
                   evidence=ev("submit_fail"))
            o.status, o.reason = "REJECTED", f"submit refused: {stext}"
            return o
        record("submitted", official_status="pending", validation_result="PASS",
               message=stext or "submit clicked (official response not recognised)", evidence=ev("submitted"))
        o.steps.append("SUBMITTED")
        return _verify(c, driver, o, record, a, ev)
    except UIUnexpected as e:
        o.status, o.reason = "FAIL_CLOSED", str(e)
        return o
    except Exception as e:  # noqa: BLE001 - any driver error is fail-closed, never a blind retry
        o.status, o.reason = "FAIL_CLOSED", f"{type(e).__name__}: {str(e)[:200]}"
        return o


def _verify(c, driver, o, record, a, ev) -> Outcome:
    rows = driver.verify_acceptance(c.file.name, c.sha256, c.trade_date, float(a["acceptance_timeout_s"]),
                                    float(a["acceptance_poll_s"]))
    if len(rows) == 1:
        record("accepted", official_status="accepted", validation_result="PASS", history_entry=rows[0]["text"],
               submission_id=rows[0].get("submission_id"), message="official history: accepted", evidence=ev("accepted"))
        o.status, o.reason = "ACCEPTED", "official history shows the submission as accepted"
        o.steps.append("ACCEPTED")
    elif len(rows) > 1:
        o.status, o.reason = "SUBMITTED_UNVERIFIED", "MANUAL_CHECK_REQUIRED: several matching history rows (ambiguous)"
    else:
        o.status, o.reason = "SUBMITTED_UNVERIFIED", "MANUAL_CHECK_REQUIRED: no official acceptance evidence before timeout"
    return o


# ----------------------------------------------------------------------------- candidates
def candidate_from_official_test(trade_date: str, ops_cfg: dict) -> Candidate | None:
    from agent.submission.official_test import dirs
    p = dirs(trade_date, ops_cfg)["reports"] / "TEST_SUBMISSION_PACKAGE.json"
    if not p.exists():
        return None
    pkg = json.loads(p.read_text(encoding="utf-8"))
    f = pkg.get("final") or {}
    if not f.get("file"):
        return None
    lv = pkg.get("local_validation") or {}
    return Candidate(trade_date, f.get("team_id_in_file") or "", Path(f["file"]), f.get("sha256") or "",
                     _official_test_state(trade_date, ops_cfg, f.get("sha256")),
                     bool(pkg.get("local_validation_ok")) and pkg.get("status") == "READY_FOR_MANUAL_TEST_UPLOAD",
                     "official_test_package", f.get("mode"), lv, _mtime(Path(f["file"])), pkg.get("prepared_at"))


def candidate_from_competition(trade_date: str, ops_cfg: dict) -> Candidate | None:
    """Competition FINAL + the full §10 local validation recomputed from the run summary."""
    from agent.ops.common import ops_path
    from agent.ops.package_submission import active_final
    from agent.submission.official_test import full_local_validation
    from agent.submission.status import compute
    st = compute(trade_date, ops_cfg=ops_cfg)
    if not st.get("file"):
        return None
    summ_p = ops_path(ops_cfg, "ops_logs_dir") / ymd(trade_date) / "competition_day_summary.json"
    summary = json.loads(summ_p.read_text(encoding="utf-8")) if summ_p.exists() else None
    v = full_local_validation(trade_date, st.get("team_id") or "", Path(st["file"]), summary, ops_cfg,
                              active_final(trade_date, ops_cfg))
    return Candidate(trade_date, st.get("team_id") or "", Path(st["file"]), st.get("sha256") or "", st["state"],
                     v["ok"], "competition_final", st.get("mode"), v["checks"], _mtime(Path(st["file"])),
                     datetime.now(TPE).replace(microsecond=0).isoformat())


def _mtime(p: Path) -> str | None:
    try:
        return datetime.fromtimestamp(p.stat().st_mtime, TPE).replace(microsecond=0).isoformat()
    except OSError:
        return None


def _official_records(trade_date: str, ops_cfg: dict) -> list[dict]:
    from agent.submission.official_test import dirs
    p = dirs(trade_date, ops_cfg)["receipts"] / "records.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def _official_test_state(trade_date: str, ops_cfg: dict, sha: str | None) -> str:
    recs = [r for r in _official_records(trade_date, ops_cfg) if r.get("sha256") == sha]
    if any(r.get("mapped_internal_state") == "ACCEPTED" for r in recs):
        return "ACCEPTED"
    return recs[-1]["mapped_internal_state"] if recs else "READY_FOR_UPLOAD"


AUTOMATION_OPERATORS = ("auto_upload",)
MANUAL_PORTAL_METHODS = ("manual_web",)          # the same formal portal UI flow the automation would use


def _norm_sha(x: str | None) -> str:
    x = (x or "").strip().lower()
    return x if x.startswith("sha256:") or not x else "sha256:" + x


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def manual_e2e_evidence(ops_cfg: dict) -> dict:
    """The auto-upload prerequisite: at least one MANUAL submission through the formal portal flow that reached
    OFFICIAL acceptance for a real FINAL. Sources:
      * competition receipts (`submissions_dir/<ymd>/receipts.jsonl`, method `manual_web`) -- the Day-1 manual E2E;
      * sealed-test records (`official_test_receipts_dir/<ymd>/records.jsonl`), if one ever reaches acceptance.
    A record qualifies only with official evidence (receipt / submission id or the verbatim history row;
    `receipt.has_acceptance_evidence`), the configured competition Team ID, and the SHA of the FINAL / sealed-test
    package of that trade date. Automation records never count (an automated run cannot satisfy its own
    prerequisite). A trade date with accepted manual evidence for different SHAs is ambiguous and does not count."""
    from agent.ops.package_submission import active_final
    from agent.ops.team import resolve
    from agent.submission.official_test import _dir, dirs
    from agent.submission.receipt import has_acceptance_evidence
    team = resolve("COMPETITION", ops_cfg)
    team_id = team["team_id"] if team["status"] == "OK" else None
    ok, rejected = [], []

    def reject(src, r, why):
        rejected.append({"source": src, "trade_date": r.get("trade_date"), "reason": why})

    # competition receipts (normal manual submission path)
    sub_root = ops_path_safe(ops_cfg, "submissions_dir")
    by_date: dict[str, list] = {}
    for f in sorted(sub_root.glob("*/receipts.jsonl")) if sub_root and sub_root.exists() else []:
        for r in _jsonl(f):
            src = "competition_receipt"
            if r.get("submission_method") not in MANUAL_PORTAL_METHODS or r.get("confirmed_by") in AUTOMATION_OPERATORS:
                reject(src, r, f"not a manual portal submission ({r.get('submission_method')}, {r.get('confirmed_by')})")
                continue
            if not has_acceptance_evidence(r):
                reject(src, r, "no official acceptance evidence (accepted + receipt id / history entry)")
                continue
            if not team_id or r.get("team_id") != team_id:
                reject(src, r, f"team {r.get('team_id')} != configured {team_id}")
                continue
            fin = active_final(r.get("trade_date") or "", ops_cfg)
            if not fin or fin.get("mode") != "competition" or fin.get("team_id") != team_id:
                reject(src, r, "no competition FINAL for this trade date / team")
                continue
            if _norm_sha(r.get("dplan_sha256")) != _norm_sha(fin.get("sha256")):
                reject(src, r, "receipt sha256 does not match the FINAL")
                continue
            by_date.setdefault(r["trade_date"], []).append({"source": src, "trade_date": r["trade_date"],
                                                            "sha256": _norm_sha(r["dplan_sha256"]),
                                                            "evidence": r.get("official_receipt_id") or r.get("history_entry")})
    # sealed-test records (only if one ever reaches acceptance)
    root = _dir("official_test_receipts_dir", "data/official_test_receipts", ops_cfg)
    for f in sorted(root.glob("*/records.jsonl")) if root.exists() else []:
        for r in _jsonl(f):
            src = "official_test_record"
            if r.get("operator") in AUTOMATION_OPERATORS:
                reject(src, r, "automation record")
                continue
            ev = {"official_status": "accepted" if r.get("official_result") == "accepted" else r.get("official_result"),
                  "stage": r.get("stage"), "official_receipt_id": r.get("submission_id"),
                  "history_entry": r.get("history_entry")}
            if r.get("mapped_internal_state") != "ACCEPTED" or not has_acceptance_evidence(ev):
                reject(src, r, "no official acceptance evidence")
                continue
            pkg_p = dirs(r.get("trade_date") or "", ops_cfg)["reports"] / "TEST_SUBMISSION_PACKAGE.json"
            pkg = json.loads(pkg_p.read_text(encoding="utf-8")) if pkg_p.exists() else {}
            fin = pkg.get("final") or {}
            if not team_id or fin.get("team_id_in_file") != team_id:
                reject(src, r, "package team does not match the configured competition team")
                continue
            if not fin.get("sha256") or _norm_sha(r.get("sha256")) != _norm_sha(fin.get("sha256")):
                reject(src, r, "record sha256 does not match the sealed-test package")
                continue
            by_date.setdefault(r["trade_date"], []).append({"source": src, "trade_date": r["trade_date"],
                                                            "sha256": _norm_sha(r["sha256"]),
                                                            "evidence": r.get("submission_id") or r.get("history_entry")})
    for t, rows in sorted(by_date.items()):
        if len({x["sha256"] for x in rows}) > 1:
            for x in rows:
                rejected.append({"source": x["source"], "trade_date": t, "reason": "ambiguous: several accepted SHAs"})
            continue
        ok.append(rows[0])
    return {"completed": bool(ok), "evidence": ok, "rejected": rejected}


def ops_path_safe(ops_cfg: dict, key: str) -> Path | None:
    from agent.ops.common import ops_path
    try:
        return ops_path(ops_cfg, key)
    except (KeyError, TypeError):
        return None


def manual_e2e_completed(ops_cfg: dict) -> bool:
    """See manual_e2e_evidence (Owner approval is still required before auto_upload.enabled = true)."""
    return manual_e2e_evidence(ops_cfg)["completed"]


def _automation_rows(trade_date: str, ops_cfg: dict, official_test: bool) -> list[dict]:
    if official_test:
        return [r for r in _official_records(trade_date, ops_cfg) if r.get("operator") == "auto_upload"]
    from agent.submission.receipt import receipts_path
    p = receipts_path(trade_date, ops_cfg)
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []
    return [r for r in rows if r.get("submission_method") == "browser_automation"]


def automated_attempts(trade_date: str, ops_cfg: dict, official_test: bool) -> int:
    return sum(1 for r in _automation_rows(trade_date, ops_cfg, official_test) if r.get("stage") == "file_uploaded")


def prior_automation_shas(trade_date: str, ops_cfg: dict, official_test: bool) -> tuple:
    return tuple({r.get("sha256") or r.get("dplan_sha256") for r in _automation_rows(trade_date, ops_cfg, official_test)})


# ----------------------------------------------------------------------------- evidence / audit
def evidence_dir(trade_date: str, ops_cfg: dict | None = None) -> Path:
    from agent.ops.common import ops_path
    cfg = ops_cfg or load_ops_config()
    base = ops_path(cfg, "submission_evidence_dir") if "submission_evidence_dir" in cfg.get("paths", {}) \
        else ROOT / "data" / "submission_evidence"
    return base / ymd(trade_date)


STAGE_SIGNAL = {"file_uploaded": "FILE_UPLOADED", "server_validated": "SERVER_VALIDATED", "submitted": "SUBMITTED",
                "rejected": "REJECTED"}


def recorder(c: Candidate, ops_cfg: dict, official_test: bool, audit_dir: Path | None = None,
             portal: dict | None = None):
    """Persist each official stage: official-test records / competition receipts + the local daily audit trail +
    the stage signal. `portal` (the runner's live portal dict) is copied into every audit row."""
    from agent.ops import signals
    audit_dir = audit_dir or evidence_dir(c.trade_date, ops_cfg)
    attempt = automated_attempts(c.trade_date, ops_cfg, official_test) + 1

    def rec(stage: str, *, official_status: str, message: str = "", validation_result: str | None = None,
            history_entry: str | None = None, submission_id: str | None = None, failure_reason: str | None = None,
            evidence: list | None = None):
        now = datetime.now(TPE).replace(microsecond=0).isoformat()
        if official_test:
            from agent.submission.official_test import record_upload
            record_upload(c.trade_date, c.sha256, official_status, message or stage, "auto_upload",
                          submission_id=submission_id, filename=c.file.name, stage=stage,
                          validation_result=validation_result, history_entry=history_entry,
                          server_validated_at=now if stage == "server_validated" else None,
                          submitted_at=now if stage == "submitted" else None,
                          accepted_at=now if stage == "accepted" else None, ops_cfg=ops_cfg)
        else:
            from agent.submission.receipt import Receipt, record_receipt
            record_receipt(Receipt(c.trade_date, c.team_id, c.sha256, now, "browser_automation", "auto_upload",
                                   official_receipt_id=submission_id, official_status=official_status,
                                   receipt_text=message, filename=c.file.name, stage=stage,
                                   server_validation_result=validation_result, history_entry=history_entry,
                                   failure_reason=failure_reason, evidence_files=list(evidence or []),
                                   server_validated_at=now if stage == "server_validated" else None), ops_cfg)
        audit_dir.mkdir(parents=True, exist_ok=True)
        refs = [str(x) for x in (evidence or [])]
        row = {"at": now, f"{stage}_at": now, "generated_at": c.generated_at, "validated_at": c.validated_at,
               "trade_date": c.trade_date, "team_id": c.team_id, "filename": c.file.name, "sha256": c.sha256,
               "attempt_number": attempt, "stage": stage, "official_status": official_status,
               "validation_result": validation_result, "submit_result": message if stage == "submitted" else None,
               "history_entry": history_entry, "submission_id": submission_id, "receipt_text": message,
               "failure_reason": failure_reason, "portal_state": dict(portal or {}),
               "screenshot_references": [x for x in refs if not x.endswith(".txt")],
               "page_text_references": [x for x in refs if x.endswith(".txt")],
               "environment": "OFFICIAL_TEST" if official_test else "COMPETITION"}
        with open(audit_dir / "audit.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        if stage in STAGE_SIGNAL:
            signals.emit(STAGE_SIGNAL[stage], c.trade_date, f"{c.file.name} {message or stage}"[:300], ops_cfg=ops_cfg)
    return rec


def manual_fallback(c: Candidate | None, outcome: Outcome, *, ops_cfg: dict, now: datetime, attempts_used: int,
                    trade_date: str | None = None) -> dict:
    """MANUAL_UPLOAD_REQUIRED instructions with every fact the operator needs (written locally + signal)."""
    from agent.ops import signals
    from agent.ops import submission_window as SW
    t = (c.trade_date if c else trade_date) or ""
    tm = SW.times_for(t, ops_cfg) if t else None
    left = (tm["closes"] - now).total_seconds() / 60 if tm else None
    a = cfg_auto(ops_cfg)
    info = {"signal": "MANUAL_UPLOAD_REQUIRED", "trade_date": t, "team_id": c.team_id if c else None,
            "dplan_path": str(c.file) if c else None, "filename": c.file.name if c else None,
            "sha256": c.sha256 if c else None, "file_bytes": c.file.stat().st_size if (c and c.file.exists()) else None,
            "local_validation": "PASS" if (c and c.local_validation_ok) else ("FAIL" if c else "NO_CANDIDATE"),
            "submission_state": c.state if c else "NOT_GENERATED", "auto_upload_status": outcome.status,
            "failure_reason": outcome.reason, "attempts_used_automation": attempts_used,
            "max_automated_attempts": a["max_automated_attempts"],
            "portal_attempts_used": outcome.portal.get("attempts_used"),
            "portal_attempts_remaining": outcome.portal.get("attempts_remaining"),
            "portal_state": outcome.portal.get("window_status"), "login_state": outcome.portal.get("login_state"),
            "window_closes_at": tm["closes"].isoformat() if tm else None,
            "window_minutes_left": None if left is None else round(left, 1),
            "portal_url": (ops_cfg.get("submission") or {}).get("portal_url"),
            "manual_steps": [
                "Open the portal 文件繳交 page and log in (the agent never logs in for you).",
                f"Confirm the page trade date = {t} and Team ID = {c.team_id if c else '?'}.",
                f"Upload ONLY {c.file if c else '<FINAL>'} (verify sha256 with: certutil -hashfile <file> SHA256).",
                "Read 檢核結果; only if it is PASS press 送出繳交; never edit the D-Plan content.",
                "Copy the history row verbatim and screenshot it.",
                f"Record (competition): python -m agent.submission.receipt --date {t} --team-id "
                f"{c.team_id if c else '<TEAM>'} --sha256 {c.sha256 if c else '<sha256>'} --method manual_web "
                "--official-status accepted --stage accepted --history-entry \"<verbatim row>\" "
                "--evidence <screenshot.png> --confirmed-by \"<name>\" (use --official-status pending --stage "
                "submitted when no history row is visible yet).",
                f"Record (sealed test): python -m agent.submission.official_test record-upload --date {t} --sha256 "
                f"{c.sha256 if c else '<sha256>'} --result accepted --stage accepted --history-entry \"<row>\" "
                "--message \"<verbatim>\" --operator \"<name>\"."]}
    d = evidence_dir(t, ops_cfg) if t else evidence_dir("1970-01-01", ops_cfg).parent
    d.mkdir(parents=True, exist_ok=True)
    write_json(d / "MANUAL_UPLOAD_REQUIRED.json", info)
    signals.emit("MANUAL_UPLOAD_REQUIRED", t, outcome.reason, ops_cfg=ops_cfg)
    return info


# ----------------------------------------------------------------------------- orchestration
def execute(trade_date: str, *, official_test: bool, ops_cfg: dict | None = None, now_fn=None, driver_factory=None,
            run_mode: str | None = None, check_config: bool = True) -> dict:
    """Gate -> driver -> evidence -> signals -> manual fallback. Used by the CLI and the 19:30 scheduler."""
    from agent.ops import signals
    from agent.ops.scheduled_run import run_mode as rm
    ops_cfg = ops_cfg or load_ops_config()
    now_fn = now_fn or (lambda: datetime.now(TPE))
    mode = run_mode or rm(ops_cfg)
    c = candidate_from_official_test(trade_date, ops_cfg) if official_test else candidate_from_competition(trade_date, ops_cfg)
    used = automated_attempts(trade_date, ops_cfg, official_test)
    if c is None:
        o = Outcome("FAIL_CLOSED", "NO_CANDIDATE (no validated FINAL for this trade date)")
        return {"outcome": o.__dict__, "manual": manual_fallback(None, o, ops_cfg=ops_cfg, now=now_fn(), attempts_used=used,
                                                                trade_date=trade_date)}
    kw = dict(now_fn=now_fn, ops_cfg=ops_cfg, run_mode=mode, official_test=official_test, attempts_used=used,
              manual_e2e_done=manual_e2e_completed(ops_cfg), check_config=check_config,
              prior_shas=prior_automation_shas(trade_date, ops_cfg, official_test))
    pre = gate(c, now=now_fn(), **{k: v for k, v in kw.items() if k not in ("now_fn",)})
    if pre:
        o = run(c, None, record=lambda *a, **k: None, **kw)          # gate outcome only: no browser is started
    else:
        drv = None
        try:
            signals.emit("AUTO_UPLOAD_RUNNING", trade_date, f"{c.file.name} state {c.state}", ops_cfg=ops_cfg)
            drv = (driver_factory or _default_driver)(ops_cfg, official_test)
            live: dict = {}
            o = run(c, drv, record=recorder(c, ops_cfg, official_test, portal=live), portal=live, **kw)
        except UIUnexpected as e:
            o = Outcome("FAIL_CLOSED", str(e))
        finally:
            if drv is not None:
                try:
                    drv.close()
                except Exception:  # noqa: BLE001
                    pass
    out = {"outcome": o.__dict__, "candidate": {"file": str(c.file), "sha256": c.sha256, "state": c.state}}
    if o.status in SUCCESS:
        signals.emit("SUBMISSION_ACCEPTED", trade_date, o.reason, ops_cfg=ops_cfg)
    else:
        if o.status in ("LOGIN_REQUIRED", "WINDOW_CLOSED"):
            signals.emit(o.status, trade_date, o.reason, ops_cfg=ops_cfg)
        out["manual"] = manual_fallback(c, o, ops_cfg=ops_cfg, now=now_fn(), attempts_used=used)
    d = evidence_dir(trade_date, ops_cfg)
    d.mkdir(parents=True, exist_ok=True)
    write_json(d / "auto_upload_last.json", out)
    return out


def _default_driver(ops_cfg: dict, official_test: bool):
    from agent.submission.portal_driver import PlaywrightPortalDriver
    return PlaywrightPortalDriver(ops_cfg, official_test=official_test,
                                  headless=bool((ops_cfg.get("auto_upload") or {}).get("headless", False)))


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--official-test", action="store_true")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--run", action="store_true")
    a = ap.parse_args(argv)
    from agent.ops.scheduled_run import run_mode
    ops = load_ops_config()
    if a.check:
        c = candidate_from_official_test(a.date, ops) if a.official_test else candidate_from_competition(a.date, ops)
        if c is None:
            print(json.dumps({"gate": "FAIL_CLOSED", "failures": ["NO_CANDIDATE"]}))
            return 2
        f = gate(c, now=datetime.now(TPE), ops_cfg=ops, run_mode=run_mode(ops), official_test=a.official_test,
                 attempts_used=automated_attempts(a.date, ops, a.official_test), manual_e2e_done=manual_e2e_completed(ops),
                 prior_shas=prior_automation_shas(a.date, ops, a.official_test))
        print(json.dumps({"gate": "PASS" if not f else "FAIL_CLOSED", "failures": f}, ensure_ascii=False, indent=1))
        return 0 if not f else 2
    r = execute(a.date, official_test=a.official_test, ops_cfg=ops)
    print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
    return 0 if r["outcome"]["status"] in SUCCESS else 2


if __name__ == "__main__":
    raise SystemExit(main())
