"""Submission receipt model + post-submission confirmation (Round 06).

Receipts are entered by a human after uploading the FINAL file (the platform's receipt / screenshot).

  python -m agent.submission.receipt --date 2026-10-27 --team-id TEAM_042 --sha256 sha256:... ^
      --method manual_web --receipt-id ABC123 --official-status accepted ^
      --screenshot submissions\\20261027\\receipt_0812.png --confirmed-by "operator A"
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.ops.common import TPE, load_ops_config, ops_path, write_json, ymd  # noqa: E402

RECEIPT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "title": "SubmissionReceipt", "type": "object",
    "required": ["trade_date", "team_id", "dplan_sha256", "submitted_at", "submission_method", "confirmed_by"],
    "properties": {
        "trade_date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "team_id": {"type": "string", "minLength": 1},
        "dplan_sha256": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
        "submitted_at": {"type": "string"},
        "submission_method": {"enum": ["manual_web", "manual_email", "official_api", "other"]},
        "official_receipt_id": {"type": ["string", "null"]},
        "official_status": {"enum": ["accepted", "rejected", "pending", "unknown"]},
        "screenshot_reference": {"type": ["string", "null"]},
        "confirmed_by": {"type": "string", "minLength": 1},
        "notes": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}


@dataclass
class Receipt:
    trade_date: str
    team_id: str
    dplan_sha256: str
    submitted_at: str
    submission_method: str
    confirmed_by: str
    official_receipt_id: str | None = None
    official_status: str = "unknown"
    screenshot_reference: str | None = None
    notes: str | None = None

    def validate(self) -> list[str]:
        import jsonschema
        v = jsonschema.Draft202012Validator(RECEIPT_SCHEMA)
        return [e.message for e in v.iter_errors(asdict(self))]


def receipts_path(trade_date: str, cfg: dict | None = None) -> Path:
    return ops_path(cfg or load_ops_config(), "submissions_dir") / ymd(trade_date) / "receipts.jsonl"


def record_receipt(r: Receipt, cfg: dict | None = None) -> dict:
    """Append the receipt (append-only) and update the submission state via the manual provider."""
    from agent.submission.manual import ManualSubmissionProvider
    probs = r.validate()
    if probs:
        raise ValueError("invalid receipt: " + "; ".join(probs))
    cfg = cfg or load_ops_config()
    p = receipts_path(r.trade_date, cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(asdict(r), recorded_at=datetime.now(TPE).isoformat()), ensure_ascii=False) + "\n")
    return ManualSubmissionProvider(cfg).verify_receipt(asdict(r))


def write_schema(path: Path) -> Path:
    return write_json(path, RECEIPT_SCHEMA)


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--team-id", required=True)
    ap.add_argument("--sha256", required=True, help="sha256 shown by the platform / of the uploaded file")
    ap.add_argument("--method", default="manual_web", choices=["manual_web", "manual_email", "official_api", "other"])
    ap.add_argument("--submitted-at", default=None)
    ap.add_argument("--receipt-id", default=None)
    ap.add_argument("--official-status", default="unknown", choices=["accepted", "rejected", "pending", "unknown"])
    ap.add_argument("--screenshot", default=None)
    ap.add_argument("--confirmed-by", required=True)
    ap.add_argument("--notes", default=None)
    a = ap.parse_args(argv)
    r = Receipt(a.date, a.team_id, a.sha256, a.submitted_at or datetime.now(TPE).isoformat(), a.method,
                a.confirmed_by, a.receipt_id, a.official_status, a.screenshot, a.notes)
    st = record_receipt(r)
    print(f"SUBMISSION STATE {a.date}: {st['state']}  ({st.get('reason', '')})")
    return 0 if st["state"] in ("SUBMISSION_CONFIRMED", "SUBMITTED_UNVERIFIED") else 2


if __name__ == "__main__":
    raise SystemExit(main())
