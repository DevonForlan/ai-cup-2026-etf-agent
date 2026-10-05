"""Placeholder for an official submission API. Intentionally unimplemented: the organiser has not documented
any interface (NC-1). Do NOT guess endpoints, reverse-engineer the web platform or automate a browser."""
from __future__ import annotations

from agent.submission.base import OfficialSubmissionUnavailable, SubmissionProvider


class FutureOfficialAPISubmissionProvider(SubmissionProvider):
    name = "official_api"

    def prepare(self, trade_date: str, team_id: str) -> dict:
        raise OfficialSubmissionUnavailable("no official submission API documented (NC-1)")

    def submit(self, prepared: dict) -> dict:
        raise OfficialSubmissionUnavailable("no official submission API documented (NC-1)")

    def verify_receipt(self, receipt: dict) -> dict:
        raise OfficialSubmissionUnavailable("no official submission API documented (NC-1)")
