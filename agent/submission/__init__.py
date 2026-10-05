"""Submission adapters. Manual only until the organiser publishes an interface (NC-1); nothing uploads."""
from agent.submission.base import (CONFIRMED, NOT_READY, READY, REJECTED, STATES, SUBMITTED_UNVERIFIED, UNKNOWN,
                                   OfficialSubmissionUnavailable, SubmissionProvider, get_state, set_state)

__all__ = ["CONFIRMED", "NOT_READY", "READY", "REJECTED", "STATES", "SUBMITTED_UNVERIFIED", "UNKNOWN",
           "OfficialSubmissionUnavailable", "SubmissionProvider", "get_state", "set_state"]
