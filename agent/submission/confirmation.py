"""SUBMISSION_CONFIRMED — read-only portal proof that a D-Plan was received (Issue #20, Owner Decision 2026-10-27).

The official portal never shows an "ACCEPTED" word. What it does show (real DOM, config/portal_adapter.yaml):
每日上傳 「已繳交」, ONE history row per trade date (交易日 / 日期 / 每日上傳 JSON / 繳交時間 / 回看) and, behind 「回看」,
the submitted JSON. A submission is CONFIRMED only when every check below holds (never inferred, never guessed):

  submitted_marker_present       the trade date's history row carries 已繳交 (wording history_submitted)
  unique_matching_history_row    exactly one history row for the trade date (several -> AMBIGUOUS)
  trade_date_match               row date, review header and review JSON trade_date == T
  team_match                     page Team ID == JSON team_id == the configured competition Team ID
  review_content_present         回看 returns parseable D-Plan JSON
  review_content_matches_final   that JSON == the active FINAL (parsed; the portal re-orders keys, so the file
                                 sha256 cannot be compared byte-wise -- the content is compared instead)
  no_rejection_marker            no rejected wording in the row / review / page
  no_validation_failure_marker   no 檢核 failure wording (validation_fail) on the page

    .venv\\Scripts\\python.exe -m agent.submission.confirmation verify --date T [--record-manual --confirmed-by NAME]
        read-only: open the portal in the Owner-logged-in automation profile, read the evidence, print the result.
        --record-manual appends a manual_web receipt with the confirmation (only when CONFIRMED).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.ops.common import TPE, load_ops_config  # noqa: E402
from agent.submission.receipt import CONFIRMATION_KEYS  # noqa: E402

CONFIRMED, NOT_CONFIRMED, AMBIGUOUS = "SUBMISSION_CONFIRMED", "NOT_CONFIRMED", "AMBIGUOUS"


def _markers(adapter: dict, key: str) -> list[str]:
    from agent.submission.portal_driver import wording_markers
    return wording_markers(adapter, key)


def rows_for(history_rows: list[dict], trade_date: str) -> list[dict]:
    """History rows whose 日期 cell is the trade date (fallback: the date in the row text)."""
    out = []
    for r in history_rows or []:
        cells = r.get("cells") or []
        if (len(cells) > 1 and cells[1].strip() == trade_date) or (not cells and trade_date in (r.get("text") or "")):
            out.append(r)
    return out


def parse_review(review: dict | None) -> dict | None:
    try:
        doc = json.loads((review or {}).get("json_text") or "")
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def evaluate(evidence: dict | None, *, trade_date: str, team_id: str, final_doc: dict | None,
             adapter: dict | None = None) -> dict:
    """Pure: evidence (driver.read_confirmation_evidence) -> {status, checks, reasons, history_entry}."""
    from agent.submission.portal_driver import load_adapter
    adapter = adapter or load_adapter()
    ev = evidence or {}
    rows = rows_for(ev.get("history_rows") or [], trade_date)
    row = rows[0] if len(rows) == 1 else None
    review = ev.get("review") or {}
    doc = parse_review(review)
    page = ev.get("page_text") or ""
    row_text = (row or {}).get("text") or ""
    submitted = _markers(adapter, "history_submitted")
    rejected = _markers(adapter, "history_rejected") + _markers(adapter, "rejected")
    vfail = _markers(adapter, "validation_fail")
    status_cell = ((row or {}).get("cells") or ["", "", ""])[2:3] or [""]
    c = {
        "submitted_marker_present": bool(row) and any(m == status_cell[0].strip() or m in status_cell[0]
                                                      for m in submitted),
        "unique_matching_history_row": len(rows) == 1,
        "trade_date_match": bool(row) and trade_date in (review.get("header") or "") and
        (doc or {}).get("trade_date") == trade_date,
        "team_match": ev.get("team_id") == team_id and (doc or {}).get("team_id") == team_id,
        "review_content_present": doc is not None,
        "review_content_matches_final": doc is not None and final_doc is not None and doc == final_doc,
        "no_rejection_marker": not any(m in row_text or m in (review.get("header") or "") or m in page
                                       for m in rejected),
        "no_validation_failure_marker": not any(m in page for m in vfail),
    }
    assert tuple(c) == CONFIRMATION_KEYS
    bad = [k for k, v in c.items() if v is not True]
    if len(rows) > 1:
        status = AMBIGUOUS
    elif not bad:
        status = CONFIRMED
    else:
        status = NOT_CONFIRMED
    return {"status": status, "checks": c, "reasons": bad if len(rows) <= 1 else [f"{len(rows)} history rows for "
                                                                                  f"{trade_date}"] + bad,
            "history_entry": row_text or None, "matching_rows": len(rows)}


def final_doc_for(trade_date: str, ops_cfg: dict) -> tuple[dict | None, dict | None]:
    from agent.ops.common import ops_path, ymd
    from agent.ops.package_submission import active_final
    fin = active_final(trade_date, ops_cfg)
    if not fin:
        return None, None
    f = ops_path(ops_cfg, "submissions_dir") / ymd(trade_date) / "FINAL" / fin["file"]
    try:
        return fin, json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fin, None


def verify(trade_date: str, *, ops_cfg: dict | None = None, driver=None, record_manual: bool = False,
           confirmed_by: str | None = None) -> dict:
    """Read-only portal verification of T (optionally records the MANUAL receipt with the confirmation)."""
    from agent.ops.team import resolve
    from agent.submission.auto_upload import UIUnexpected, _default_driver   # browser code stays in the allowed modules
    ops_cfg = ops_cfg or load_ops_config()
    team = resolve("COMPETITION", ops_cfg)
    fin, doc = final_doc_for(trade_date, ops_cfg)
    out = {"trade_date": trade_date, "checked_at": datetime.now(TPE).replace(microsecond=0).isoformat(),
           "team_id": team.get("team_id"), "final_sha256": (fin or {}).get("sha256")}
    if team["status"] != "OK" or not fin or doc is None or fin.get("mode") != "competition":
        out.update(status=NOT_CONFIRMED, reasons=["no competition FINAL / Team ID for this trade date"])
        return out
    own = driver is None
    drv = driver
    try:
        if own:
            drv = _default_driver(ops_cfg, False)
        drv.open_portal()
        login = drv.check_login()
        if login != "LOGGED_IN":
            out.update(status=NOT_CONFIRMED, reasons=[f"LOGIN_STATE_{login}"])
            return out
        ev = drv.read_confirmation_evidence(trade_date)
        res = evaluate(ev, trade_date=trade_date, team_id=team["team_id"], final_doc=doc,
                       adapter=getattr(drv, "adapter", None))
        out.update(res, evidence=drv.capture_evidence("confirmation") or [])
    except UIUnexpected as e:
        out.update(status=NOT_CONFIRMED, reasons=[str(e)])
        return out
    finally:
        if own and drv is not None:
            drv.close()
    if record_manual and out["status"] == CONFIRMED:
        out["receipt_state"] = record_confirmation(trade_date, team["team_id"], fin, out, method="manual_web",
                                                   confirmed_by=confirmed_by or "Owner (manual upload)",
                                                   ops_cfg=ops_cfg)["state"]
    return out


def record_confirmation(trade_date: str, team_id: str, fin: dict, res: dict, *, method: str, confirmed_by: str,
                        ops_cfg: dict) -> dict:
    """Append the confirmation receipt (official_status 'submitted', stage 'submitted'): never 'accepted'."""
    from agent.submission.receipt import Receipt, record_receipt
    row = res.get("history_entry") or ""
    cells = row.split("\t")
    submitted_at = None
    if len(cells) >= 4:
        try:
            submitted_at = datetime.fromisoformat(cells[3].strip().replace(" ", "T") + ":00+08:00").isoformat()
        except ValueError:
            submitted_at = None
    r = Receipt(trade_date, team_id, fin["sha256"], submitted_at or res["checked_at"], method, confirmed_by,
                official_status="submitted", stage="submitted", history_entry=row, filename=fin.get("file"),
                evidence_files=[str(x) for x in res.get("evidence") or []],
                receipt_text="SUBMISSION_CONFIRMED (read-only portal check: history row + 回看 content == FINAL)",
                notes="Issue #20: the portal shows no ACCEPTED wording; this is a SUBMISSION_CONFIRMED record",
                confirmation=dict(res["checks"]))
    return record_receipt(r, ops_cfg)


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    v = sp.add_parser("verify")
    v.add_argument("--date", required=True)
    v.add_argument("--record-manual", action="store_true", help="append a manual_web receipt when CONFIRMED")
    v.add_argument("--confirmed-by", default=None)
    a = ap.parse_args(argv)
    r = verify(a.date, record_manual=a.record_manual, confirmed_by=a.confirmed_by)
    r.pop("page_text", None)
    print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
    return 0 if r["status"] == CONFIRMED else 2


if __name__ == "__main__":
    raise SystemExit(main())
