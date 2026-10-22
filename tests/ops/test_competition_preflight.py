"""Competition preflight (agent/ops/competition_preflight.py): read-only, never switches run_mode."""
from pathlib import Path

from agent.ops import competition_preflight as CP


def test_venv_launcher_pairs_are_one_logical_run():
    cmd = r'"C:\x\.venv\Scripts\python.exe" -m agent.ops.scheduled_run'
    procs = [{"ProcessId": 10, "ParentProcessId": 1, "CommandLine": cmd},
             {"ProcessId": 11, "ParentProcessId": 10, "CommandLine": cmd}]
    assert [p["ProcessId"] for p in CP.logical_runs(procs)] == [10]


def test_two_independent_invocations_are_two_runs():
    cmd = r'"C:\x\.venv\Scripts\python.exe" agent\competition_day.py --date 2026-10-27'
    procs = [{"ProcessId": 10, "ParentProcessId": 1, "CommandLine": cmd},
             {"ProcessId": 11, "ParentProcessId": 10, "CommandLine": cmd},
             {"ProcessId": 20, "ParentProcessId": 2, "CommandLine": cmd},
             {"ProcessId": 21, "ParentProcessId": 20, "CommandLine": cmd}]
    assert len(CP.logical_runs(procs)) == 2


def test_placeholder_team_id_blocks(monkeypatch):
    monkeypatch.setattr(CP, "resolve_team_id", lambda: ("TEAM_TEST", "x"))  # placeholder
    r = CP.check_team_id()
    assert r["level"] == CP.BLOCKED and "TEAM_ID_NOT_CONFIGURED" in r["detail"]
    monkeypatch.setattr(CP, "resolve_team_id", lambda: ("TEAM_042", "x"))
    assert CP.check_team_id()["level"] == CP.READY


def test_precompetition_run_mode_is_warning_not_switched():
    r = CP.check_run_mode({"run_mode": "PRECOMPETITION"})
    assert r["level"] == CP.WARNING
    assert CP.check_run_mode({"run_mode": "COMPETITION"})["level"] == CP.READY


def test_tool_never_writes_config():
    src = Path(CP.__file__).read_text(encoding="utf-8")
    for bad in ("ops.yaml\").write", "write_text(yaml", "safe_dump", "Set-ScheduledTask", "Register-ScheduledTask",
                "schtasks /change", "schtasks /create"):
        assert bad not in src
