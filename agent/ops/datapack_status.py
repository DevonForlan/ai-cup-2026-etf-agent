"""Read-only DataPack status for the next submission (docs/OFFICIAL_DATAPACK_INTEGRATION.md).

    .venv\\Scripts\\python.exe -m agent.ops.datapack_status [--mode COMPETITION] [--trade-date 2026-10-28] [--json]

Never downloads, never logs in, never changes files.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agent.ops.common import TPE, load_ops_config  # noqa: E402


def next_trade_date(now: datetime, hol: set[str]) -> str:
    """The trade date whose submission is being prepared: tomorrow's trading day once 19:30 has passed (or on a
    non-trading evening), otherwise today if it is a trading day (window still open until 08:55)."""
    from agent.ops.scheduled_run import is_trading_day, next_trading_day
    t = now.date()
    if now.hour * 60 + now.minute >= 19 * 60 + 30 or not is_trading_day(t, hol):
        return next_trading_day(t, hol).isoformat()
    return t.isoformat()


def status(mode: str | None = None, trade_date: str | None = None, team_id: str | None = None, now: datetime | None = None,
           ops_cfg: dict | None = None, provider=None, hol: set[str] | None = None,
           first_trade_date: str | None = None) -> dict:
    from agent.config import load_official_rules
    from agent.ops.daily_evaluation import Paths
    from agent.ops.datapack import calendar_holidays, previous_trading_day, validate_official_datapack
    from agent.ops.datapack_downloader import PORTAL_STATUS, ManualFileProvider
    from agent.ops.scheduled_run import run_mode
    ops_cfg = ops_cfg or load_ops_config()
    hol = calendar_holidays() if hol is None else hol
    mode = (mode or run_mode(ops_cfg)).upper()
    if team_id is None:                       # P-1: runtime team id from config/ops.yaml (agent/ops/team.py)
        from agent.ops.team import resolve as resolve_team
        tm = resolve_team(mode, ops_cfg)
        if tm["status"] != "OK":
            return {"mode": mode, "team_id": None, "trade_date": trade_date or next_trade_date(now or datetime.now(TPE), hol),
                    "expected_previous_trading_day": None, "datapack_required": mode == "COMPETITION",
                    "latest_datapack_found": False, "datapack_file": None, "datapack_date": None, "schema_version": None,
                    "freshness": None, "validation": None, "problems": [], "provider": "ManualFileProvider",
                    "official_portal_provider": PORTAL_STATUS, "status": "BLOCKED", "reason": "TEAM_ID_NOT_CONFIGURED",
                    "settlement_source": None,
                    "recommended_action": "set config/ops.yaml team.competition_team_id from the organiser's official notice"}
        team_id = tm["team_id"]
    trade_date = trade_date or next_trade_date(now or datetime.now(TPE), hol)
    first = first_trade_date or str(load_official_rules().raw["official_rules"].get("first_trade_date") or "")
    exp = previous_trading_day(trade_date, hol)
    provider = provider or ManualFileProvider(ops_cfg=ops_cfg)
    found = provider.locate(team_id, trade_date)
    v = validate_official_datapack(found, team_id, trade_date, exp, None, first) if found else None
    out = {"mode": mode, "team_id": team_id, "trade_date": trade_date, "expected_previous_trading_day": exp,
           "datapack_required": mode == "COMPETITION", "latest_datapack_found": bool(found),
           "datapack_file": str(found) if found else None, "datapack_date": v["settlement_date"] if v else None,
           "schema_version": v["schema_version"] if v else None, "freshness": v["freshness"] if v else None,
           "validation": v["status"] if v else None, "problems": v["problems"] if v else [],
           "provider": provider.name, "official_portal_provider": PORTAL_STATUS}
    if mode == "COMPETITION":
        day1 = trade_date == first
        if v and v["status"] == "PASS":
            out.update(status="READY", reason=None, settlement_source="INITIAL_CAPITAL" if day1 else "OFFICIAL_DATAPACK",
                       recommended_action="NONE")
        elif not found and day1:
            out.update(status="READY", reason=None, settlement_source="INITIAL_CAPITAL", recommended_action="NONE")
        else:
            out.update(status="BLOCKED", reason="DATAPACK_MISSING" if not found else v["reason"],
                       settlement_source=None,
                       recommended_action="DOWNLOAD_DATAPACK_FROM_BACKOFFICE_INTO data\\official_datapack (then rerun)")
    else:
        paper = Paths().settlement(exp).exists()
        out.update(status="READY", reason=None,
                   settlement_source="PRECOMPETITION_PAPER_LEDGER" if paper else "INITIAL_CAPITAL",
                   recommended_action="NONE")
    return out


def render(s: dict) -> str:
    rows = [("Mode", s["mode"]), ("Trade Date", s["trade_date"]),
            ("Expected Previous Trading Day", s["expected_previous_trading_day"]),
            ("DataPack Required", "YES" if s["datapack_required"] else "NO"),
            ("Latest DataPack Found", "YES" if s["latest_datapack_found"] else "NO"),
            ("DataPack File", s["datapack_file"] or "-"), ("DataPack Date", s["datapack_date"] or "-"),
            ("Schema Version", s["schema_version"] or "-"), ("Freshness", s["freshness"] or "-"),
            ("Validation", s["validation"] or "-"), ("Settlement Source", s["settlement_source"] or "-"),
            ("Official Portal Provider", s["official_portal_provider"]),
            ("Status", s["status"]), ("Reason", s["reason"] or "-"),
            ("Recommended Action", s["recommended_action"])]
    return "\n".join(f"{k + ':':32s}{v}" for k, v in rows)


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["PRECOMPETITION", "COMPETITION"], default=None)
    ap.add_argument("--trade-date", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    s = status(a.mode, a.trade_date)
    print(json.dumps(s, ensure_ascii=False, indent=1) if a.json else render(s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
