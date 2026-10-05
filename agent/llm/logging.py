"""Append-only LLM call log: logs/llm/YYYYMMDD/calls.jsonl. Never contains API keys."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.config import ROOT
from agent.llm.env import redact

TPE = timezone(timedelta(hours=8))


class LLMCallLogger:
    def __init__(self, root: Path | None = None, run_date: str | None = None, enabled: bool = True):
        self.root = root or ROOT / "logs" / "llm"
        self.run_date = run_date
        self.enabled = enabled
        self.records: list[dict] = []

    def path(self) -> Path:
        d = (self.run_date or datetime.now(TPE).strftime("%Y-%m-%d")).replace("-", "")
        return self.root / d / "calls.jsonl"

    def log(self, rec: dict) -> None:
        rec = dict(rec)
        rec.setdefault("timestamp", datetime.now(TPE).replace(microsecond=0).isoformat())
        self.records.append(rec)
        if not self.enabled:
            return
        p = self.path()
        p.parent.mkdir(parents=True, exist_ok=True)
        line = redact(json.dumps(rec, ensure_ascii=False, default=str))
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())

    def summary(self) -> dict:
        r = self.records
        lat = sorted(x.get("latency_sec", 0) for x in r if x.get("status") in ("ok", "replay"))
        p95 = lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else 0.0
        return {"calls": len(r), "ok": sum(x["status"] in ("ok", "replay") for x in r),
                "failed": sum(x["status"] not in ("ok", "replay", "skipped_budget") for x in r),
                "skipped_budget": sum(x["status"] == "skipped_budget" for x in r),
                "retries": sum(x.get("retry_count", 0) for x in r),
                "input_tokens": sum(x.get("input_tokens") or 0 for x in r),
                "output_tokens": sum(x.get("output_tokens") or 0 for x in r),
                "cost_usd": sum(x.get("cost_usd") or 0 for x in r),
                "latency_mean": (sum(lat) / len(lat)) if lat else 0.0, "latency_p95": p95}
