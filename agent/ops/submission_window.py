"""Submission / decision window for trade date T (pure clock logic, no I/O except config).

Official window (config/competition.yaml): T-1 19:30 -> T 08:55. Internal policy (config/ops.yaml deadline):

  T-1 19:30 .. 23:59   normal / same-day catch-up prediction
  T   00:00 .. 08:29   CROSS-DAY catch-up allowed (trade_date = today only, never yesterday's)
  T   08:30            decision_cutoff  -> DECISION_WINDOW_CLOSED: no new investment decision is produced
  T   08:55            official close   -> SUBMISSION_WINDOW_CLOSED: no new submission candidate

Deadline warnings (evaluated whenever the scheduled run / catch-up / an operator check executes; no extra
high-frequency scheduler):
  >= 08:00 and no READY_FOR_UPLOAD  -> SUBMISSION_WARNING_0800
  >= 08:15 and no READY_FOR_UPLOAD  -> SUBMISSION_HIGH_WARNING_0815
  >= 08:45 and not ACCEPTED         -> SUBMISSION_CRITICAL_WARNING_0845
"""
from __future__ import annotations

from datetime import datetime, timedelta

from agent.ops.common import TPE

DEFAULTS = {"decision_cutoff": "08:30", "warn_0800": "08:00", "high_warn_0815": "08:15", "critical_warn_0845": "08:45"}
READY_OR_BETTER = {"READY_FOR_UPLOAD", "SUBMISSION_UI_UNAVAILABLE", "UPLOADED", "ACCEPTED"}


def _hm(s: str) -> tuple[int, int]:
    h, m = str(s).split(":")
    return int(h), int(m)


def params(ops_cfg: dict | None = None) -> dict:
    return {**DEFAULTS, **{k: v for k, v in ((ops_cfg or {}).get("deadline") or {}).items() if k in DEFAULTS}}


def official_times() -> tuple[tuple[int, int], tuple[int, int]]:
    from agent.config import load_official_rules
    r = load_official_rules()
    return _hm(r.submission_open), _hm(r.submission_close)


def at(day: str, hm: tuple[int, int]) -> datetime:
    y, m, d = map(int, day.split("-"))
    return datetime(y, m, d, *hm, tzinfo=TPE)


def times_for(trade_date: str, ops_cfg: dict | None = None, open_hm=None, close_hm=None) -> dict:
    p = params(ops_cfg)
    if open_hm is None or close_hm is None:
        open_hm, close_hm = official_times()
    prev = (datetime.fromisoformat(trade_date) - timedelta(days=1)).date().isoformat()
    return {"opens": at(prev, open_hm), "warn_0800": at(trade_date, _hm(p["warn_0800"])),
            "high_warn_0815": at(trade_date, _hm(p["high_warn_0815"])),
            "decision_cutoff": at(trade_date, _hm(p["decision_cutoff"])),
            "critical_warn_0845": at(trade_date, _hm(p["critical_warn_0845"])), "closes": at(trade_date, close_hm)}


def phase(trade_date: str, now: datetime, ops_cfg: dict | None = None, open_hm=None, close_hm=None) -> str:
    t = times_for(trade_date, ops_cfg, open_hm, close_hm)
    if now < t["opens"]:
        return "WINDOW_NOT_OPEN"
    if now >= t["closes"]:
        return "SUBMISSION_WINDOW_CLOSED"
    if now >= t["decision_cutoff"]:
        return "DECISION_WINDOW_CLOSED"
    return "DECISION_OPEN"


def warnings(trade_date: str, now: datetime, submission_state: str | None, ops_cfg: dict | None = None,
             open_hm=None, close_hm=None) -> list[str]:
    t = times_for(trade_date, ops_cfg, open_hm, close_hm)
    if now < t["opens"] or now >= t["closes"]:
        return []
    st = submission_state or "NOT_GENERATED"
    out = []
    if now >= t["warn_0800"] and st not in READY_OR_BETTER:
        out.append("SUBMISSION_WARNING_0800")
    if now >= t["high_warn_0815"] and st not in READY_OR_BETTER:
        out.append("SUBMISSION_HIGH_WARNING_0815")
    if now >= t["critical_warn_0845"] and st != "ACCEPTED":
        out.append("SUBMISSION_CRITICAL_WARNING_0845")
    return out
