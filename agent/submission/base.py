"""Submission provider interface + submission state machine (Round 06).

The official submission mechanism is NOT announced (NC-1). No provider may upload, log in, automate a
browser or call an unknown endpoint. A generated file is NOT a submission: only a matching receipt can move
a trade date to SUBMISSION_CONFIRMED.

States
  NOT_READY             no valid FINAL_CANDIDATE
  READY_TO_SUBMIT       FINAL_CANDIDATE exists and verifies (hash / team / date / validation)
  SUBMITTED_UNVERIFIED  operator says it was uploaded, no matching official receipt yet
  SUBMISSION_CONFIRMED  receipt matches trade_date + team_id + D-Plan sha256 and the platform accepted it
  REJECTED              platform rejected it (receipt official_status = rejected)
  UNKNOWN               evidence inconsistent (e.g. receipt hash != FINAL hash) -> human must investigate
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from agent.ops.common import TPE, load_ops_config, ops_path, write_json, ymd

NOT_READY, READY, SUBMITTED_UNVERIFIED, CONFIRMED, REJECTED, UNKNOWN = (
    "NOT_READY", "READY_TO_SUBMIT", "SUBMITTED_UNVERIFIED", "SUBMISSION_CONFIRMED", "REJECTED", "UNKNOWN")
STATES = (NOT_READY, READY, SUBMITTED_UNVERIFIED, CONFIRMED, REJECTED, UNKNOWN)
ALLOWED = {
    NOT_READY: {READY, NOT_READY},
    READY: {READY, SUBMITTED_UNVERIFIED, CONFIRMED, REJECTED, UNKNOWN, NOT_READY},
    SUBMITTED_UNVERIFIED: {CONFIRMED, REJECTED, UNKNOWN, SUBMITTED_UNVERIFIED},
    CONFIRMED: {CONFIRMED, UNKNOWN},          # a confirmed date never silently goes back to READY
    REJECTED: {READY, SUBMITTED_UNVERIFIED, REJECTED, UNKNOWN},
    UNKNOWN: set(STATES),
}


class OfficialSubmissionUnavailable(NotImplementedError):
    """Raised by every submit(): the organiser has not published a submission interface (NC-1)."""


class InvalidTransition(RuntimeError):
    pass


def state_path(trade_date: str, cfg: dict | None = None) -> Path:
    return ops_path(cfg or load_ops_config(), "submissions_dir") / ymd(trade_date) / "submission_state.json"


def get_state(trade_date: str, cfg: dict | None = None) -> dict:
    p = state_path(trade_date, cfg)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"trade_date": trade_date, "state": NOT_READY, "history": []}


def set_state(trade_date: str, new: str, *, reason: str, cfg: dict | None = None, **fields) -> dict:
    if new not in STATES:
        raise ValueError(new)
    st = get_state(trade_date, cfg)
    old = st["state"]
    if new not in ALLOWED[old]:
        raise InvalidTransition(f"{old} -> {new} not allowed ({reason})")
    st["history"].append({"at": datetime.now(TPE).isoformat(), "from": old, "to": new, "reason": reason, **fields})
    st.update(fields, state=new, updated_at=datetime.now(TPE).isoformat())
    write_json(state_path(trade_date, cfg), st)
    return st


class SubmissionProvider(ABC):
    name = "base"

    @abstractmethod
    def prepare(self, trade_date: str, team_id: str) -> dict:
        """Locate + verify the FINAL file; return what the operator (or a future API) needs."""

    @abstractmethod
    def submit(self, prepared: dict) -> dict:
        """Upload. Must raise OfficialSubmissionUnavailable until the organiser documents an interface."""

    @abstractmethod
    def verify_receipt(self, receipt: dict) -> dict:
        """Match a receipt against the FINAL file -> new submission state."""
