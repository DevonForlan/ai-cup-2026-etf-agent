"""Guarded automated D-Plan upload (Issue #4) — FAIL CLOSED by design. Disabled by default.

Feasibility (2026-10-22): the competition back office (https://fundaiagent.esun-ai-challenge.tw, SSO login) offers NO
documented participant API — its frontend talks to a private /api with the browser session + a CSRF cookie. Using
that directly would mean session/CSRF extraction and guessed endpoints: forbidden. The only acceptable mechanism is
normal browser automation of the human UI in a browser profile the Owner logged into interactively
(BROWSER_AUTOMATION_FEASIBLE, unverified until the UI is observed). Until then `config/ops.yaml auto_upload.enabled`
is false and the Playwright driver has no selectors, so every real run fails closed.

Flow (each step recorded as evidence; ACCEPTED only with official history evidence):
  safety gate -> login state -> page shows T + Team ID -> idempotency (history already has an accepted entry?)
  -> attempts -> upload FILE -> FILE_UPLOADED -> 檢核結果 PASS? -> SERVER_VALIDATED -> time < 08:55?
  -> 送出繳交 -> SUBMITTED -> history row with the configured acceptance marker -> ACCEPTED (else stays SUBMITTED)
Anything unexpected (UI, login, date, team, sha, unknown validation, ambiguous history) -> FAIL_CLOSED, no submit.
It never generates a decision: it only uploads an EXISTING validated FINAL (allowed after 08:30, never after 08:55).

    .venv\\Scripts\\python.exe -m agent.submission.auto_upload --date T [--official-test] --check   # gate only
    .venv\\Scripts\\python.exe -m agent.submission.auto_upload --date T [--official-test] --run     # if enabled
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
from agent.ops.common import TPE, load_ops_config, sha256_file  # noqa: E402

OFFICIAL_DAILY_LIMIT = 25
RESUMABLE = ("READY_FOR_UPLOAD", "FILE_UPLOADED", "SERVER_VALIDATED")


class UIUnexpected(RuntimeError):
    """The portal did not look / behave as observed -> fail closed."""


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


@dataclass
class Outcome:
    status: str                    # ACCEPTED | SUBMITTED | REJECTED | FAIL_CLOSED | ALREADY_ACCEPTED | NOT_RUN
    reason: str
    steps: list = field(default_factory=list)


def cfg_auto(ops_cfg: dict) -> dict:
    a = dict(ops_cfg.get("auto_upload") or {})
    a.setdefault("enabled", False)
    a.setdefault("method", "none")
    a.setdefault("max_automated_attempts", 3)
    a.setdefault("selectors", {})
    a.setdefault("accepted_markers", [])
    return a


# ----------------------------------------------------------------------------- safety gate (pure)
def gate(c: Candidate, *, now: datetime, ops_cfg: dict, run_mode: str, official_test: bool, attempts_used: int,
         manual_e2e_done: bool, check_config: bool = True) -> list[str]:
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
    elif c.state == "SUBMITTED":
        f.append("SUBMITTED_AWAITING_EVIDENCE (do not submit again before the history is checked)")
    elif c.state not in RESUMABLE:
        f.append(f"STATE_NOT_SUBMITTABLE ({c.state})")
    if not c.local_validation_ok:
        f.append("LOCAL_VALIDATION_FAIL")
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
    if attempts_used >= int(a["max_automated_attempts"]):
        f.append(f"MAX_AUTOMATED_ATTEMPTS ({attempts_used}/{a['max_automated_attempts']})")
    return f


# ----------------------------------------------------------------------------- runner
def run(c: Candidate, driver, *, now_fn, ops_cfg: dict, run_mode: str, official_test: bool, attempts_used: int,
        manual_e2e_done: bool, record, check_config: bool = True) -> Outcome:
    """`record(stage, **fields)` persists evidence (official-test records or competition receipts)."""
    o = Outcome("NOT_RUN", "")
    fails = gate(c, now=now_fn(), ops_cfg=ops_cfg, run_mode=run_mode, official_test=official_test,
                 attempts_used=attempts_used, manual_e2e_done=manual_e2e_done, check_config=check_config)
    if fails:
        status = "ALREADY_ACCEPTED" if any(x.startswith("ALREADY_ACCEPTED") for x in fails) else "FAIL_CLOSED"
        return Outcome(status, "; ".join(fails))
    markers = [m for m in cfg_auto(ops_cfg)["accepted_markers"] if m]
    try:
        st = driver.session_state()
        o.steps.append(f"session {st}")
        if st != "LOGGED_IN":
            raise UIUnexpected(f"LOGIN_STATE_{st} (the Owner must log in interactively in the automation profile)")
        driver.open_submission_page()
        shown_date, shown_team = driver.shown_trade_date(), driver.shown_team_id()
        if shown_date != c.trade_date:
            raise UIUnexpected(f"PAGE_TRADE_DATE {shown_date!r} != {c.trade_date}")
        if shown_team not in (None, c.team_id):
            raise UIUnexpected(f"PAGE_TEAM {shown_team!r} != {c.team_id}")
        hist = driver.history()
        if any(_accepted_row(r, c, markers) for r in hist):
            record("accepted", official_status="accepted", history_entry=_row_text(next(
                r for r in hist if _accepted_row(r, c, markers))), message="already accepted (found in history)")
            return Outcome("ALREADY_ACCEPTED", "history already shows an accepted submission for this file", o.steps)
        remaining = driver.attempts_remaining()
        if remaining is None:
            raise UIUnexpected("ATTEMPTS_REMAINING_UNREADABLE")
        if remaining <= 0:
            raise UIUnexpected("OFFICIAL_ATTEMPT_LIMIT_REACHED")
        driver.upload(c.file)
        record("file_uploaded", official_status="pending", message="file uploaded")
        o.steps.append("FILE_UPLOADED")
        res, text = driver.validation_result()
        if res == "FAIL":
            record("rejected", official_status="rejected", validation_result="FAIL", message=text,
                   failure_reason=text)
            return Outcome("REJECTED", f"檢核結果 FAIL: {text}", o.steps + ["REJECTED"])
        if res != "PASS":
            raise UIUnexpected(f"VALIDATION_RESULT_UNKNOWN ({text!r})")
        record("server_validated", official_status="pending", validation_result="PASS", message=text)
        o.steps.append("SERVER_VALIDATED")
        from agent.ops import submission_window as SW
        if SW.phase(c.trade_date, now_fn(), ops_cfg) == "SUBMISSION_WINDOW_CLOSED":
            raise UIUnexpected("SUBMISSION_WINDOW_CLOSED before submit")
        msg = driver.submit()
        record("submitted", official_status="pending", validation_result="PASS", message=msg)
        o.steps.append("SUBMITTED")
        rows = [r for r in driver.history() if _accepted_row(r, c, markers)]
        if len(rows) == 1:
            record("accepted", official_status="accepted", validation_result="PASS", history_entry=_row_text(rows[0]),
                   submission_id=rows[0].get("submission_id"), message=msg)
            return Outcome("ACCEPTED", "official history shows the submission as accepted", o.steps + ["ACCEPTED"])
        if len(rows) > 1:
            return Outcome("SUBMITTED", "DUPLICATE_AMBIGUITY: several matching history rows — human must check",
                           o.steps)
        return Outcome("SUBMITTED", "no official acceptance evidence in the history yet (not ACCEPTED)", o.steps)
    except UIUnexpected as e:
        return Outcome("FAIL_CLOSED", str(e), o.steps)
    except Exception as e:  # noqa: BLE001 - any driver error is a fail-closed outcome, never a blind retry
        return Outcome("FAIL_CLOSED", f"{type(e).__name__}: {str(e)[:200]}", o.steps)


def _row_text(r: dict) -> str:
    return str(r.get("text") or json.dumps(r, ensure_ascii=False))[:500]


def _accepted_row(r: dict, c: Candidate, markers: list[str]) -> bool:
    """A history row counts as acceptance only if it names THIS file / sha and carries a configured official
    acceptance marker (taken verbatim from the observed UI; no marker configured -> never accepted)."""
    if not markers:
        return False
    same = (r.get("sha256") == c.sha256) or (r.get("filename") == c.file.name and r.get("trade_date") in (None, c.trade_date))
    return bool(same) and any(m in str(r.get("status_text") or r.get("text") or "") for m in markers)


# ----------------------------------------------------------------------------- candidates + evidence
def candidate_from_official_test(trade_date: str, ops_cfg: dict) -> Candidate | None:
    from agent.submission.official_test import dirs
    p = dirs(trade_date, ops_cfg)["reports"] / "TEST_SUBMISSION_PACKAGE.json"
    if not p.exists():
        return None
    pkg = json.loads(p.read_text(encoding="utf-8"))
    f = pkg.get("final") or {}
    if not f.get("file"):
        return None
    state = _official_test_state(trade_date, ops_cfg, f.get("sha256"))
    return Candidate(trade_date, f.get("team_id_in_file") or "", Path(f["file"]), f.get("sha256") or "", state,
                     bool(pkg.get("local_validation_ok")) and pkg.get("status") == "READY_FOR_MANUAL_TEST_UPLOAD",
                     "official_test_package", f.get("mode"))


def _official_records(trade_date: str, ops_cfg: dict) -> list[dict]:
    from agent.submission.official_test import dirs
    p = dirs(trade_date, ops_cfg)["receipts"] / "records.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def _official_test_state(trade_date: str, ops_cfg: dict, sha: str | None) -> str:
    recs = [r for r in _official_records(trade_date, ops_cfg) if r.get("sha256") == sha]
    if any(r.get("mapped_internal_state") == "ACCEPTED" for r in recs):
        return "ACCEPTED"
    return recs[-1]["mapped_internal_state"] if recs else "READY_FOR_UPLOAD"


def manual_e2e_completed(ops_cfg: dict) -> bool:
    """True once ANY manual sealed-test record reached official acceptance evidence (Issue #4 §11)."""
    from agent.submission.official_test import _dir
    root = _dir("official_test_receipts_dir", "data/official_test_receipts", ops_cfg)
    for p in root.glob("*/records.jsonl") if root.exists() else []:
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("mapped_internal_state") == "ACCEPTED" and r.get("operator") != "auto_upload":
                    return True
    return False


def automated_attempts(trade_date: str, ops_cfg: dict, official_test: bool) -> int:
    if official_test:
        return sum(1 for r in _official_records(trade_date, ops_cfg)
                   if r.get("operator") == "auto_upload" and r.get("stage") == "file_uploaded")
    from agent.submission.receipt import receipts_path
    p = receipts_path(trade_date, ops_cfg)
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []
    return sum(1 for r in rows if r.get("submission_method") == "browser_automation" and r.get("stage") == "file_uploaded")


def recorder(c: Candidate, ops_cfg: dict, official_test: bool):
    def rec(stage: str, *, official_status: str, message: str = "", validation_result: str | None = None,
            history_entry: str | None = None, submission_id: str | None = None, failure_reason: str | None = None):
        now = datetime.now(TPE).replace(microsecond=0).isoformat()
        if official_test:
            from agent.submission.official_test import record_upload
            record_upload(c.trade_date, c.sha256, official_status if official_status != "pending" else "pending",
                          message or stage, "auto_upload", submission_id=submission_id, filename=c.file.name,
                          stage=stage, validation_result=validation_result, history_entry=history_entry,
                          server_validated_at=now if stage == "server_validated" else None,
                          submitted_at=now if stage == "submitted" else None,
                          accepted_at=now if stage == "accepted" else None, ops_cfg=ops_cfg)
        else:
            from agent.submission.receipt import Receipt, record_receipt
            record_receipt(Receipt(c.trade_date, c.team_id, c.sha256, now, "browser_automation", "auto_upload",
                                   official_receipt_id=submission_id, official_status=official_status,
                                   receipt_text=message, filename=c.file.name, stage=stage,
                                   server_validation_result=validation_result, history_entry=history_entry,
                                   failure_reason=failure_reason,
                                   server_validated_at=now if stage == "server_validated" else None), ops_cfg)
    return rec


# ----------------------------------------------------------------------------- Playwright driver (unverified)
class PlaywrightDriver:
    """Normal browser automation of the human UI in a persistent profile the Owner logged into interactively.
    UNVERIFIED: selectors must be filled from the observed UI (config/ops.yaml auto_upload.selectors); with any
    selector missing it refuses to start. Never reads cookies / tokens, never calls /api directly."""
    REQUIRED = ("logged_in_marker", "trade_date_text", "attempts_remaining_text", "file_input", "validation_text",
                "submit_button", "history_rows")

    def __init__(self, ops_cfg: dict):
        a = cfg_auto(ops_cfg)
        missing = [k for k in self.REQUIRED if not a["selectors"].get(k)]
        if missing:
            raise UIUnexpected(f"SELECTORS_NOT_CONFIGURED {missing}")
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError as e:
            raise UIUnexpected("PLAYWRIGHT_NOT_INSTALLED") from e
        self.sel, self.url = a["selectors"], (ops_cfg.get("submission") or {}).get("portal_url")
        self.profile = ROOT / a.get("browser_profile_dir", "data/browser_profiles/fundaiagent")
        raise UIUnexpected("PLAYWRIGHT_DRIVER_NOT_VALIDATED (implement against the observed UI after the manual E2E)")


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
    c = candidate_from_official_test(a.date, ops) if a.official_test else _competition_candidate(a.date, ops)
    if c is None:
        print(json.dumps({"status": "FAIL_CLOSED", "reason": "NO_CANDIDATE"}))
        return 2
    kw = dict(ops_cfg=ops, run_mode=run_mode(ops), official_test=a.official_test,
              attempts_used=automated_attempts(a.date, ops, a.official_test), manual_e2e_done=manual_e2e_completed(ops))
    if a.check:
        f = gate(c, now=datetime.now(TPE), **kw)
        print(json.dumps({"gate": "PASS" if not f else "FAIL_CLOSED", "failures": f}, ensure_ascii=False, indent=1))
        return 0 if not f else 2
    try:
        drv = PlaywrightDriver(ops)
    except UIUnexpected as e:
        print(json.dumps({"status": "FAIL_CLOSED", "reason": str(e)}, ensure_ascii=False))
        return 2
    o = run(c, drv, now_fn=lambda: datetime.now(TPE), record=recorder(c, ops, a.official_test), **kw)
    print(json.dumps(o.__dict__, ensure_ascii=False, indent=1, default=str))
    return 0 if o.status in ("ACCEPTED", "ALREADY_ACCEPTED") else 2


def _competition_candidate(trade_date: str, ops_cfg: dict) -> Candidate | None:
    from agent.submission.status import compute
    st = compute(trade_date, ops_cfg=ops_cfg)
    if not st.get("file"):
        return None
    return Candidate(trade_date, st.get("team_id") or "", Path(st["file"]), st.get("sha256") or "", st["state"],
                     st["state"] in ("READY_FOR_UPLOAD", "FILE_UPLOADED", "SERVER_VALIDATED", "SUBMITTED", "ACCEPTED"),
                     "competition_final", st.get("mode"))


if __name__ == "__main__":
    raise SystemExit(main())
