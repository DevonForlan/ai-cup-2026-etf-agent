"""Print the daily operator runbook for a trade date with each step's state (done / pending) from artifacts.

  python agent\\ops\\runbook.py --date 2026-10-27 --team-id TEAM_042
Full text: docs/COMPETITION_DAILY_RUNBOOK.md and docs/EMERGENCY_RUNBOOK.md.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.ops.common import load_ops_config, ops_path, ymd  # noqa: E402


def steps(trade_date: str, team_id: str, ops_cfg: dict) -> list[tuple[str, str, Path | None]]:
    logs = ops_path(ops_cfg, "ops_logs_dir") / ymd(trade_date)
    sub = ops_path(ops_cfg, "submissions_dir") / ymd(trade_date)
    sdir = ops_path(ops_cfg, "settlement_dir")
    py = r".venv\Scripts\python.exe"
    return [
        ("T-1 ~19:00  put the official T-1 settlement (if published) into data/settlement/<T-1>_official.json|csv",
         "(manual; see EMERGENCY_RUNBOOK §settlement)", None),
        ("T-1 ~19:30  data refresh", rf"{py} agent\ops\refresh_daily.py --date {trade_date}", logs / "data_health.json"),
        ("T-1 ~19:45  preflight", rf"{py} agent\ops\preflight.py --date {trade_date} --mode competition",
         logs / "preflight.json"),
        ("T-1 ~20:00  competition day run (package + FINAL_CANDIDATE, NO upload)",
         rf"{py} agent\competition_day.py --date {trade_date} --team-id {team_id} --mode competition",
         sub / "FINAL_CANDIDATE.txt"),
        ("T-1 ~20:10  healthcheck", rf"{py} agent\ops\healthcheck.py --date {trade_date} --mode competition",
         logs / "healthcheck.json"),
        ("T-1 ~20:15  HUMAN: read FINAL_CANDIDATE.txt, check date/team/sha256, upload that ONE file manually,"
         " save the platform receipt into submissions/<date>/", "(manual)", None),
        ("T   ~15:30  internal settlement of T after close data",
         rf"{py} agent\ops\settle_internal.py --date {trade_date} --refresh", sdir / f"{ymd(trade_date)}_internal.json"),
    ]


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--team-id", default="TEAM_XXXXX")
    a = ap.parse_args(argv)
    cfg = load_ops_config()
    print(f"DAILY RUNBOOK  trade date {a.date}  team {a.team_id}")
    for i, (what, cmd, art) in enumerate(steps(a.date, a.team_id, cfg), 1):
        state = "-" if art is None else ("DONE" if art.exists() else "PENDING")
        print(f"{i}. [{state:7s}] {what}\n      {cmd}")
    print("Never upload anything from candidates/. Upload only the file named in FINAL_CANDIDATE.txt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
