"""Organizer clarification adapter (Round 06).

Official answers are NEVER hard-coded. They are read from config/organizer_clarifications.yaml, which is
created only from an organiser answer the user provides (and documented in docs/ORGANIZER_CLARIFICATIONS.md).
No file / no entry -> every NC rule stays `unknown` and the simulator keeps using
config/unconfirmed_rules.yaml simulation_assumptions, labelled ASSUMPTION.

Entry format:
  NC-1:
    status: confirmed            # unknown | confirmed | partially_confirmed | superseded
    answer: "..."                # summary of the official text
    effective_date: 2026-10-20
    source: organizer_email      # organizer_email | official_faq | official_announcement | platform
    source_ref: "mail 2026-10-19 from ..."
    affected: [settlement, submission]
    config_changes: {}           # optional: keys of unconfirmed_rules.yaml to switch (applied only via tests)
"""
from __future__ import annotations

from pathlib import Path

import yaml

from agent.config import ROOT

RULE_IDS = ("NC-1", "NC-2", "NC-3", "NC-4", "NC-5", "NC-6", "NC-7", "NC-8", "NC-9", "NC-10", "NC-15", "C12")
DESCRIPTIONS = {
    "NC-1": "official settlement source and submission mechanism",
    "NC-2": "Active Share definition (mode)",
    "NC-3": "C-check disposition: reject vs warning",
    "NC-4": "no-trade / no-submission handling",
    "NC-5": "fee rounding",
    "NC-6": "boundaries: cash 25% / 20 and 30 holdings inclusive",
    "NC-7": "stock-dividend odd shares",
    "NC-8": "MDD includes initial NAV",
    "NC-9": "bug fixes allowed during the competition",
    "NC-10": "multiple submissions per day: which one counts",
    "NC-15": "first trading day 10/26 or 10/27",
    "C12": "C12 cash estimate includes fees",
}
STATUSES = ("unknown", "confirmed", "partially_confirmed", "superseded")
SOURCES = ("organizer_email", "official_faq", "official_announcement", "platform")
DEFAULT_PATH = ROOT / "config" / "organizer_clarifications.yaml"


class ClarificationError(ValueError):
    pass


def load(path: Path | None = None) -> dict[str, dict]:
    p = Path(path) if path else DEFAULT_PATH
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else None
    raw = raw or {}
    out = {}
    for rid in RULE_IDS:
        e = dict(raw.get(rid) or {})
        e.setdefault("status", "unknown")
        out[rid] = e
    problems = validate(out) + [f"unknown rule id {k}" for k in raw if k not in RULE_IDS]
    if problems:
        raise ClarificationError("; ".join(problems))
    return out


def validate(entries: dict[str, dict]) -> list[str]:
    probs = []
    for rid, e in entries.items():
        st = e.get("status")
        if st not in STATUSES:
            probs.append(f"{rid}: bad status {st!r}")
        if st in ("confirmed", "partially_confirmed"):
            for k in ("answer", "source", "effective_date", "affected"):
                if not e.get(k):
                    probs.append(f"{rid}: confirmed entry needs '{k}'")
            if e.get("source") and e["source"] not in SOURCES:
                probs.append(f"{rid}: source must be one of {SOURCES}")
    return probs


def status(rule_id: str, path: Path | None = None) -> str:
    return load(path)[rule_id]["status"]


def is_confirmed(rule_id: str, path: Path | None = None) -> bool:
    return status(rule_id, path) == "confirmed"


def label(rule_id: str, path: Path | None = None) -> str:
    """CONFIRMED (official answer on file) or ASSUMPTION (simulation_assumptions in use)."""
    return "CONFIRMED" if is_confirmed(rule_id, path) else "ASSUMPTION"


def summary(path: Path | None = None) -> list[dict]:
    e = load(path)
    return [{"rule": r, "description": DESCRIPTIONS[r], "status": e[r]["status"],
             "mode": "CONFIRMED" if e[r]["status"] == "confirmed" else "ASSUMPTION",
             "source": e[r].get("source"), "effective_date": str(e[r].get("effective_date") or "")} for r in RULE_IDS]
