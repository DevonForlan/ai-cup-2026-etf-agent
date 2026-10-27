"""DataPack handoff (Issue #4): ACCEPTED (T) -> official settlement -> DataPack -> validate -> archive -> T+1 start.

    .venv\\Scripts\\python.exe -m agent.submission.handoff --date T

COMPETITION: the next trading day may start ONLY from the official DataPack (as_of = T) — never the paper ledger,
internal settlement or a reconstruction (the gate in agent/ops/datapack.py enforces it). PRECOMPETITION: paper flow.
Read-only: it never downloads (the Owner downloads 資料包 from the 文件繳交 page into data/official_datapack/).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.ops.common import TPE, load_ops_config, sha256_file  # noqa: E402


def next_trading_day(t: str) -> str:
    from agent.ops.datapack import calendar_holidays
    from agent.ops.scheduled_run import is_trading_day
    hol = calendar_holidays()
    d = date.fromisoformat(t) + timedelta(days=1)
    while not is_trading_day(d, hol):
        d += timedelta(days=1)
    return d.isoformat()


def datapack_handoff(trade_date: str, *, ops_cfg: dict | None = None, now: datetime | None = None,
                     run_mode: str | None = None, provider=None, emit: bool = True) -> dict:
    from agent.ops import signals
    from agent.ops.scheduled_run import run_mode as rm
    from agent.ops.team import resolve
    from agent.submission.status import compute
    ops_cfg = ops_cfg or load_ops_config()
    now = now or datetime.now(TPE)
    mode = (run_mode or rm(ops_cfg)).upper()
    nxt = next_trading_day(trade_date)
    sub = compute(trade_date, now=now, ops_cfg=ops_cfg)
    out = {"trade_date": trade_date, "submission_state": sub["state"], "accepted": sub["state"] in ("ACCEPTED", "SUBMISSION_CONFIRMED"),
           "next_trade_date": nxt, "datapack_expected_as_of": trade_date, "mode": mode}
    if mode != "COMPETITION":
        out.update(datapack_status="NOT_APPLICABLE_PRECOMPETITION", start_source_next="PRECOMPETITION_PAPER_LEDGER")
        return out
    team = resolve("COMPETITION", ops_cfg)
    if team["status"] != "OK":
        out.update(datapack_status="BLOCKED", reason="TEAM_ID_NOT_CONFIGURED")
        return out
    from agent.ops.datapack import datapack_gate
    g = datapack_gate(nxt, team["team_id"], provider=provider, ops_cfg=ops_cfg,
                      **(ops_cfg.get("datapack_calendar_override") or {}))
    out.update(datapack_gate=g["status"], reason=g.get("reason"), datapack_file=g.get("file"),
               datapack_as_of=g.get("settlement_date"), datapack_schema=g.get("schema_version"),
               datapack_freshness=g.get("freshness"), problems=g.get("problems"))
    if g["status"] == "PASS" and g.get("file"):
        off = g.get("official") or {}
        sha = sha256_file(Path(g["file"]))
        checks = {"team_id": "PASS",                                   # validate_official_datapack checks team_id
                  "as_of_date": "PASS" if g.get("settlement_date") == trade_date else f"FAIL ({g.get('settlement_date')})",
                  "schema": "PASS" if g.get("schema_version") else "FAIL",
                  "nav": "PASS" if off.get("nav") not in (None, "") else "FAIL",
                  "cash": "PASS" if off.get("cash") not in (None, "") else "FAIL",
                  "holdings": "PASS" if isinstance(off.get("holdings"), dict) else "FAIL",
                  "freshness": "PASS" if g.get("freshness") == "FRESH" else f"FAIL ({g.get('freshness')})",
                  "sha256": "PASS" if sha else "FAIL"}
        ok = all(v == "PASS" for v in checks.values())
        out.update(datapack_status="DATAPACK_READY" if ok else "DATAPACK_INVALID", datapack_sha256=sha,
                   datapack_checks=checks, start_source_next="OFFICIAL_DATAPACK" if ok else None,
                   archive_command=f"python -m agent.ops.datapack --file {g['file']} --team-id {team['team_id']} "
                                   f"--trade-date {nxt} --operator <name>")
    elif g.get("reason") in ("DATAPACK_MISSING", "DATAPACK_STALE"):
        out.update(datapack_status="DATAPACK_REQUIRED", start_source_next=None)
        if emit and out["accepted"]:
            signals.emit("DATAPACK_REQUIRED", nxt, f"{g.get('reason')}: download 資料包 (as_of {trade_date}) into "
                                                  f"data/official_datapack/", ops_cfg=ops_cfg)
    else:
        out.update(datapack_status=g.get("reason") or "DATAPACK_INVALID", start_source_next=None)
    return out


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="the trade date that was submitted (T)")
    a = ap.parse_args(argv)
    print(json.dumps(datapack_handoff(a.date), ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
