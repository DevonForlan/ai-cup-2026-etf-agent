"""Deadline guard. Cutoff = trade date + competition.yaml submission_window.closes (+08:00).

Phases (minutes to cutoff, thresholds from config/ops.yaml):
  NORMAL        > restrict_refresh_minutes
  RESTRICTED    <= restrict_refresh_minutes : no non-critical data refresh
  NO_LLM        <= no_llm_minutes           : template narrative, no LLM retries
  PACKAGE_ONLY  <= package_only_minutes     : quant-only run + validation + package, nothing else
  PAST_CUTOFF   <= 0                        : still produce a package, clearly marked LATE
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from agent.config import load_official_rules
from agent.ops.common import TPE, Clock


@dataclass
class DeadlineStatus:
    cutoff: datetime
    now: datetime
    minutes_left: float
    phase: str

    @property
    def allow_noncritical_refresh(self) -> bool:
        return self.phase == "NORMAL"

    @property
    def allow_llm(self) -> bool:
        return self.phase in ("NORMAL", "RESTRICTED")

    @property
    def allow_refresh(self) -> bool:
        return self.phase in ("NORMAL", "RESTRICTED", "NO_LLM")

    def to_dict(self) -> dict:
        return {"cutoff": self.cutoff.isoformat(), "now": self.now.isoformat(),
                "minutes_left": round(self.minutes_left, 1), "phase": self.phase}


def cutoff_for(trade_date: str) -> datetime:
    r = load_official_rules()
    hh, mm = map(int, r.submission_close.split(":"))
    y, m, d = map(int, trade_date.split("-"))
    return datetime(y, m, d, hh, mm, tzinfo=TPE)


def opening_for(trade_date: str) -> datetime:
    from datetime import timedelta
    r = load_official_rules()
    hh, mm = map(int, r.submission_open.split(":"))
    y, m, d = map(int, trade_date.split("-"))
    return datetime(y, m, d, hh, mm, tzinfo=TPE) - timedelta(days=1)


def status(trade_date: str, clock: Clock, ops_cfg: dict) -> DeadlineStatus:
    c = cutoff_for(trade_date)
    now = clock.now()
    left = (c - now).total_seconds() / 60
    dl = ops_cfg["deadline"]
    if left <= 0:
        ph = "PAST_CUTOFF"
    elif left <= dl["package_only_minutes"]:
        ph = "PACKAGE_ONLY"
    elif left <= dl["no_llm_minutes"]:
        ph = "NO_LLM"
    elif left <= dl["restrict_refresh_minutes"]:
        ph = "RESTRICTED"
    else:
        ph = "NORMAL"
    return DeadlineStatus(c, now, left, ph)
