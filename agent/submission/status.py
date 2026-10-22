"""Deterministic, evidence-based SUBMISSION STATUS for a trade date (read-only derivation; never uploads).

It layers the operator-facing lifecycle on top of the persisted state machine in agent/submission/base.py
(NOT_READY / READY_TO_SUBMIT / SUBMITTED_UNVERIFIED / SUBMISSION_CONFIRMED / REJECTED / UNKNOWN), which stays the
only writer of upload / acceptance facts (agent/submission/receipt.py). A state is reached ONLY with evidence:

  NOT_GENERATED              no D-Plan candidate for T
  GENERATED                  a candidate D-Plan file exists                        (file in candidates/<run_id>/)
  VALIDATED                  a candidate passed schema / ticker / numeric / compliance (validation_report ok)
  READY_FOR_UPLOAD           an active FINAL exists and its sha256 still verifies  (FINAL/ + final_history)
  UPLOADED                   a receipt says it was uploaded, no official acceptance (base SUBMITTED_UNVERIFIED)
  ACCEPTED                   official receipt id + status accepted for the FINAL sha (base SUBMISSION_CONFIRMED)
  REJECTED                   official receipt says rejected                        (base REJECTED)
  SUBMISSION_UI_UNAVAILABLE  READY_FOR_UPLOAD but config says the official upload page is unavailable
  SUBMISSION_WINDOW_CLOSED   08:55 passed without ACCEPTED / UPLOADED / REJECTED evidence

READY_FOR_UPLOAD is NEVER treated as ACCEPTED. A FINAL produced in dry-run / PRECOMPETITION is reported with
uploadable = False (paper file, must not be uploaded).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from agent.ops.common import TPE, load_ops_config, ops_path, sha256_file, write_json, ymd

NOT_GENERATED, GENERATED, VALIDATED, READY_FOR_UPLOAD = "NOT_GENERATED", "GENERATED", "VALIDATED", "READY_FOR_UPLOAD"
UPLOADED, ACCEPTED, REJECTED = "UPLOADED", "ACCEPTED", "REJECTED"
UI_UNAVAILABLE, WINDOW_CLOSED = "SUBMISSION_UI_UNAVAILABLE", "SUBMISSION_WINDOW_CLOSED"
STATES = (NOT_GENERATED, GENERATED, VALIDATED, READY_FOR_UPLOAD, UPLOADED, ACCEPTED, REJECTED, UI_UNAVAILABLE,
          WINDOW_CLOSED)
BASE_MAP = {"SUBMITTED_UNVERIFIED": UPLOADED, "SUBMISSION_CONFIRMED": ACCEPTED, "REJECTED": REJECTED}


def submission_cfg(ops_cfg: dict | None = None) -> dict:
    s = dict((ops_cfg or load_ops_config()).get("submission") or {})
    s.setdefault("portal_url", None)
    s.setdefault("ui_status", "NOT_YET_VERIFIED")
    s.setdefault("official_portal_provider", "DISABLED_PENDING_OFFICIAL_PORTAL_VALIDATION")
    return s


def _candidates(day: Path) -> list[dict]:
    out = []
    for c in sorted((day / "candidates").glob("*")) if (day / "candidates").is_dir() else []:
        f = next(iter(sorted(c.glob("D-Plan_*.json"))), None)
        if f is None:
            continue
        meta, val = {}, {}
        try:
            meta = json.loads((c / "run_metadata.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        try:
            val = json.loads((c / "validation_report.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        out.append({"run_id": c.name, "file": str(f), "generated_at": meta.get("generated_at"),
                    "mode": meta.get("mode"), "validated": bool(val.get("ok")),
                    "validated_at": meta.get("generated_at") if val.get("ok") else None})
    return out


def compute(trade_date: str, now: datetime | None = None, ops_cfg: dict | None = None, write: bool = False) -> dict:
    from agent.ops import submission_window as SW
    from agent.ops.package_submission import active_final
    from agent.submission.base import get_state
    from agent.submission.receipt import effective_submission, receipts_path
    ops_cfg = ops_cfg or load_ops_config()
    now = now or datetime.now(TPE)
    day = ops_path(ops_cfg, "submissions_dir") / ymd(trade_date)
    sc = submission_cfg(ops_cfg)
    cands = _candidates(day)
    fin = active_final(trade_date, ops_cfg)
    rec = {"trade_date": trade_date, "checked_at": now.replace(microsecond=0).isoformat(), "state": NOT_GENERATED,
           "evidence": [], "team_id": None, "file": None, "sha256": None, "generated_at": None, "validated_at": None,
           "uploaded_at": None, "accepted_at": None, "submission_id": None, "receipt_evidence": None,
           "failure_reason": None, "uploadable": False, "mode": None, "ui_status": sc["ui_status"],
           "portal_url_configured": bool(sc["portal_url"]), "official_portal_provider": sc["official_portal_provider"],
           "official_receipt_format": sc.get("receipt_format", "PENDING_PORTAL_VALIDATION"),
           "last_upload_status": None, "uploads_today": 0, "receipt_text": None, "last_upload_is_effective": None}
    if cands:
        rec.update(state=GENERATED, generated_at=cands[-1]["generated_at"])
        rec["evidence"].append(f"{len(cands)} candidate D-Plan(s) in {day / 'candidates'}")
        ok = [c for c in cands if c["validated"]]
        if ok:
            rec.update(state=VALIDATED, validated_at=ok[-1]["validated_at"])
            rec["evidence"].append(f"validation_report ok for {ok[-1]['run_id']}")
    if fin is not None:
        f = day / "FINAL" / fin["file"]
        if f.exists() and sha256_file(f) == fin["sha256"]:
            rec.update(state=READY_FOR_UPLOAD, team_id=fin["team_id"], file=str(f), sha256=fin["sha256"],
                       mode=fin.get("mode"), uploadable=fin.get("mode") == "competition",
                       generated_at=rec["generated_at"] or fin.get("marked_at"),
                       validated_at=rec["validated_at"] or fin.get("marked_at"))
            rec["evidence"].append(f"FINAL {fin['file']} sha256 verified (mode {fin.get('mode')})")
        else:
            rec["failure_reason"] = "FINAL file missing or hash changed"
    base = get_state(trade_date, ops_cfg)
    mapped = BASE_MAP.get(base.get("state"))
    receipts = []
    rp = receipts_path(trade_date, ops_cfg)
    if rp.exists():
        receipts = [json.loads(x) for x in rp.read_text(encoding="utf-8").splitlines() if x.strip()]
    if mapped and rec["sha256"]:                    # upload / acceptance facts only from the receipt state machine
        eff = effective_submission(receipts, trade_date) if receipts else {"effective": None, "last_upload": None}
        last = eff.get("last_upload") or (receipts[-1] if receipts else None)
        rec.update(state=mapped, uploaded_at=(last or {}).get("submitted_at"),
                   receipt_evidence=(last or {}).get("screenshot_reference"))
        rec.update(last_upload_status=(last or {}).get("official_status"), uploads_today=eff.get("uploads"),
                   receipt_text=(last or {}).get("receipt_text"),
                   last_upload_is_effective=eff.get("last_upload_is_effective"))
        if eff.get("effective"):
            rec.update(accepted_at=eff["effective"].get("accepted_at") or eff["effective"].get("submitted_at"),
                       submission_id=eff["effective"].get("official_receipt_id"))
        if mapped == REJECTED:
            rec["failure_reason"] = (last or {}).get("failure_reason") or "official receipt: rejected"
        rec["evidence"].append(f"submission_state {base.get('state')} ({len(receipts)} receipt(s))")
    elif base.get("state") == "UNKNOWN":
        rec["failure_reason"] = "receipt evidence inconsistent with FINAL (base state UNKNOWN) — human must investigate"
    if rec["state"] == READY_FOR_UPLOAD and sc["ui_status"] == "UNAVAILABLE":
        rec["state"] = UI_UNAVAILABLE
        rec["evidence"].append("config submission.ui_status = UNAVAILABLE (official page has no upload function)")
    ph = SW.phase(trade_date, now, ops_cfg)
    rec["window_phase"] = ph
    if ph == "SUBMISSION_WINDOW_CLOSED" and rec["state"] not in (ACCEPTED, UPLOADED, REJECTED):
        rec["state_before_close"] = rec["state"]
        rec["state"] = WINDOW_CLOSED
    rec["deadline_warnings"] = SW.warnings(trade_date, now, rec["state"], ops_cfg)
    if write:
        write_json(day / "submission_status.json", rec)
    return rec


def main(argv=None) -> int:
    import argparse
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="read-only submission status for a trade date")
    ap.add_argument("--date", default=None, help="trade date (default: today)")
    a = ap.parse_args(argv)
    d = a.date or datetime.now(TPE).date().isoformat()
    r = compute(d)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
