"""Operational signals (Issue #4): append-only local signal log for the operator — no polling, no new scheduler,
no external service. Emitted by the 19:30 scheduler, the auto-upload runner and the submission status checks.

    logs/notifications/signals.jsonl      every signal (append-only)
    logs/notifications/latest.json        newest signal per (trade_date, signal)
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from agent.ops.common import TPE, load_ops_config

SIGNALS = ("LOGIN_REQUIRED", "READY_FOR_UPLOAD", "AUTO_UPLOAD_RUNNING", "FILE_UPLOADED", "SERVER_VALIDATED",
           "SUBMITTED", "SUBMISSION_ACCEPTED", "SUBMISSION_CONFIRMED", "REJECTED", "MANUAL_UPLOAD_REQUIRED", "SUBMISSION_WARNING_0800",
           "SUBMISSION_HIGH_WARNING_0815", "SUBMISSION_CRITICAL_WARNING_0845", "DATAPACK_REQUIRED", "WINDOW_CLOSED")


def signals_dir(ops_cfg: dict | None = None) -> Path:
    from agent.config import ROOT
    base = Path((ops_cfg or load_ops_config())["paths"].get("ops_logs_dir", "logs/ops"))
    base = base if base.is_absolute() else ROOT / base
    return base.parent / "notifications"


def emit(signal: str, trade_date: str | None, detail: str = "", *, ops_cfg: dict | None = None) -> dict:
    if signal not in SIGNALS:
        raise ValueError(f"unknown signal {signal}")
    d = signals_dir(ops_cfg)
    d.mkdir(parents=True, exist_ok=True)
    rec = {"at": datetime.now(TPE).replace(microsecond=0).isoformat(), "signal": signal, "trade_date": trade_date,
           "detail": str(detail)[:500]}
    with open(d / "signals.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    latest_p = d / "latest.json"
    try:
        latest = json.loads(latest_p.read_text(encoding="utf-8")) if latest_p.exists() else {}
    except ValueError:
        latest = {}
    latest[f"{trade_date}|{signal}"] = rec
    latest_p.write_text(json.dumps(latest, ensure_ascii=False, indent=1), encoding="utf-8")
    return rec


def read(trade_date: str | None = None, ops_cfg: dict | None = None) -> list[dict]:
    p = signals_dir(ops_cfg) / "signals.jsonl"
    if not p.exists():
        return []
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [r for r in rows if trade_date is None or r.get("trade_date") == trade_date]
