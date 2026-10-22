"""Runtime Team ID resolution (P-1): OPERATIONS config, decoupled from the frozen strategy file.

config/ops.yaml
    team:
      competition_team_id: null        # the OFFICIAL id from the organiser; null -> TEAM_ID_NOT_CONFIGURED
      precompetition_team_id: TEAM_TEST

PRECOMPETITION -> precompetition_team_id (a placeholder such as TEAM_TEST is fine for paper runs).
COMPETITION    -> competition_team_id; missing or a placeholder -> TEAM_ID_NOT_CONFIGURED (callers BLOCK).
config/strategy_quant_v1.yaml (frozen, sha256-pinned) is never read for the team id any more. Never guesses an id.
"""
from __future__ import annotations

PLACEHOLDERS = {"", "NONE", "NULL", "TEAM_TEST", "TEAM_SIM", "TEAM_XXX", "TEAM_REHEARSAL", "TEAM_ID", "TBD"}


def is_placeholder(team_id: str | None) -> bool:
    t = str(team_id or "").strip().upper()
    return t in PLACEHOLDERS or t.startswith("TEAM_TEST")


def resolve(mode: str | None = None, ops_cfg: dict | None = None) -> dict:
    """{'team_id', 'source', 'status': 'OK' | 'TEAM_ID_NOT_CONFIGURED', 'mode'}. Pure on the given ops_cfg."""
    from agent.ops.common import load_ops_config
    ops_cfg = ops_cfg if ops_cfg is not None else load_ops_config()
    if mode is None:
        from agent.ops.scheduled_run import run_mode
        mode = run_mode(ops_cfg)
    mode = str(mode).upper()
    team = ops_cfg.get("team") or {}
    if mode == "COMPETITION":
        tid = team.get("competition_team_id")
        tid = None if tid is None else str(tid).strip()
        ok = bool(tid) and not is_placeholder(tid)
        return {"mode": mode, "team_id": tid if ok else None, "source": "config/ops.yaml:team.competition_team_id",
                "status": "OK" if ok else "TEAM_ID_NOT_CONFIGURED", "configured_value": tid}
    tid = str(team.get("precompetition_team_id") or "TEAM_TEST").strip()
    return {"mode": mode, "team_id": tid, "source": "config/ops.yaml:team.precompetition_team_id", "status": "OK",
            "configured_value": tid}
