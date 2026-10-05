"""ManualSubmissionProvider: prepares the FINAL file for a human upload. It never uploads."""
from __future__ import annotations

import json

from agent.ops.common import load_ops_config, ops_path, sha256_file, ymd
from agent.submission.base import (CONFIRMED, NOT_READY, READY, REJECTED, SUBMITTED_UNVERIFIED, UNKNOWN,
                                   OfficialSubmissionUnavailable, SubmissionProvider, get_state, set_state)


class ManualSubmissionProvider(SubmissionProvider):
    name = "manual"

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or load_ops_config()

    def _final(self, trade_date: str) -> dict | None:
        day = ops_path(self.cfg, "submissions_dir") / ymd(trade_date)
        hist = day / "final_history.jsonl"
        if not hist.exists():
            return None
        lines = [json.loads(x) for x in hist.read_text(encoding="utf-8").splitlines() if x.strip()]
        active = [x for x in lines if x.get("event", "MARKED") in ("MARKED", "REPLACED")]
        return active[-1] if active else None

    def prepare(self, trade_date: str, team_id: str) -> dict:
        rec = self._final(trade_date)
        day = ops_path(self.cfg, "submissions_dir") / ymd(trade_date)
        problems = []
        if rec is None:
            problems.append("no FINAL_CANDIDATE")
        else:
            f = day / "FINAL" / rec["file"]
            if not f.exists():
                problems.append("FINAL file missing")
            elif sha256_file(f) != rec["sha256"]:
                problems.append("FINAL file hash changed")
            if rec["team_id"] != team_id:
                problems.append(f"team {rec['team_id']} != {team_id}")
            if rec["trade_date"] != trade_date:
                problems.append("trade date mismatch")
            if rec.get("mode") != "competition":
                problems.append(f"FINAL is a {rec.get('mode')} file (not for upload)")
        state = get_state(trade_date, self.cfg)["state"]
        if not problems and state == NOT_READY:
            set_state(trade_date, READY, reason="FINAL verified by ManualSubmissionProvider.prepare", cfg=self.cfg,
                      dplan_sha256=rec["sha256"], team_id=team_id)
        return {"provider": self.name, "ok": not problems, "problems": problems, "final": rec,
                "upload_path": str(day / "FINAL" / rec["file"]) if rec else None,
                "instructions": "Upload this ONE file manually on the official platform, then record the "
                                "receipt: python -m agent.submission.receipt --date ... --sha256 ...",
                "state": get_state(trade_date, self.cfg)["state"]}

    def submit(self, prepared: dict) -> dict:
        raise OfficialSubmissionUnavailable(
            "Automatic submission is disabled: the official submission interface is not announced (NC-1). "
            "Upload manually and record the receipt.")

    def verify_receipt(self, receipt: dict) -> dict:
        d, team = receipt["trade_date"], receipt["team_id"]
        rec = self._final(d)
        reasons = []
        if rec is None:
            reasons.append("no FINAL_CANDIDATE for this date")
        else:
            if receipt["dplan_sha256"] != rec["sha256"]:
                reasons.append("receipt sha256 != FINAL sha256 (a different file was uploaded?)")
            if team != rec["team_id"]:
                reasons.append(f"receipt team {team} != FINAL team {rec['team_id']}")
            if d != rec["trade_date"]:
                reasons.append("trade date mismatch")
        st = get_state(d, self.cfg)["state"]
        if reasons:
            new = UNKNOWN
        elif receipt.get("official_status") == "rejected":
            new = REJECTED
        elif receipt.get("official_status") == "accepted" and receipt.get("official_receipt_id"):
            new = CONFIRMED
        else:
            new = SUBMITTED_UNVERIFIED               # uploaded, but no official confirmation yet
        if st == NOT_READY and not reasons:
            set_state(d, READY, reason="FINAL verified at receipt time", cfg=self.cfg)
        out = set_state(d, new, reason="; ".join(reasons) or f"receipt {receipt.get('official_status')}",
                        cfg=self.cfg, receipt_id=receipt.get("official_receipt_id"),
                        receipt_sha256=receipt["dplan_sha256"])
        out["reason"] = "; ".join(reasons) or f"receipt {receipt.get('official_status')}"
        return out
