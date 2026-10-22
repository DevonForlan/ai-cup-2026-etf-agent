"""Submission portal helper — DISCOVERY / BROWSER-OPEN ONLY.

    .venv\\Scripts\\python.exe -m agent.submission.portal --status [--date T]
    .venv\\Scripts\\python.exe -m agent.submission.portal --open   [--date T]

It never logs in, never selects a file, never uploads, never presses submit, never reads cookies / tokens /
credentials and never guesses a URL. `--open` only opens the operator-configured config/ops.yaml
submission.portal_url in the default browser, and only when the trade date is READY_FOR_UPLOAD (a competition
FINAL). Everything after that is manual (docs: reports/COMPETITION_OPERATION_SOP.md).

Providers:
  ManualSubmissionProvider    ENABLED   (agent/submission/manual.py: prepare + receipt verification)
  OfficialPortalProvider      DISABLED_PENDING_OFFICIAL_PORTAL_VALIDATION (agent/submission/future_api.py)
UI status (config/ops.yaml submission.ui_status): NOT_YET_VERIFIED | AVAILABLE | UNAVAILABLE | LOGIN_REQUIRED
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.ops.common import TPE, load_ops_config  # noqa: E402

UI_STATUSES = ("NOT_YET_VERIFIED", "AVAILABLE", "UNAVAILABLE", "LOGIN_REQUIRED")
OPENABLE = ("READY_FOR_UPLOAD", "SUBMISSION_UI_UNAVAILABLE")


def providers() -> dict:
    from agent.submission.future_api import PORTAL_STATUS
    return {"ManualSubmissionProvider": "ENABLED", "OfficialPortalProvider": PORTAL_STATUS}


def portal_status(trade_date: str | None = None, ops_cfg: dict | None = None, now: datetime | None = None) -> dict:
    from agent.submission.status import compute, submission_cfg
    ops_cfg = ops_cfg or load_ops_config()
    sc = submission_cfg(ops_cfg)
    d = trade_date or (now or datetime.now(TPE)).date().isoformat()
    st = compute(d, now=now, ops_cfg=ops_cfg)
    ui = sc["ui_status"] if sc["ui_status"] in UI_STATUSES else "NOT_YET_VERIFIED"
    return {"trade_date": d, "SUBMISSION_UI_STATUS": ui, "portal_url": sc["portal_url"] or None,
            "portal_url_status": "CONFIGURED" if sc["portal_url"] else "SUBMISSION_PORTAL_URL_NOT_CONFIGURED",
            "submission_state": st["state"], "uploadable": st["uploadable"], "file": st["file"], "sha256": st["sha256"],
            "providers": providers(), "auto_upload": "DISABLED (manual upload only)"}


def open_submission_portal(trade_date: str | None = None, ops_cfg: dict | None = None, now: datetime | None = None,
                           opener=None) -> dict:
    """Open the configured portal page in the browser. Returns what happened; never does anything else."""
    s = portal_status(trade_date, ops_cfg, now)
    if not s["portal_url"]:
        return {**s, "opened": False, "result": "SUBMISSION_PORTAL_URL_NOT_CONFIGURED"}
    if s["submission_state"] not in OPENABLE:
        return {**s, "opened": False, "result": f"NOT_READY_FOR_UPLOAD ({s['submission_state']})"}
    if not s["uploadable"]:
        return {**s, "opened": False, "result": "FINAL_IS_NOT_A_COMPETITION_FILE (dry-run / paper; do not upload)"}
    if not str(s["portal_url"]).lower().startswith("https://"):
        return {**s, "opened": False, "result": "PORTAL_URL_REJECTED (https only)"}
    if opener is None:
        import webbrowser
        opener = webbrowser.open
    opener(s["portal_url"])
    return {**s, "opened": True, "result": "BROWSER_OPENED (login / file selection / upload are manual)"}


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--status", action="store_true")
    g.add_argument("--open", action="store_true")
    a = ap.parse_args(argv)
    r = open_submission_portal(a.date) if a.open else portal_status(a.date)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
