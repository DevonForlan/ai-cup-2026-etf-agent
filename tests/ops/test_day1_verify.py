"""Issue #16: the Day-1 18:00 verification is read-only, fails loudly and never passes on a broken prerequisite."""
from pathlib import Path

import pytest

from agent.ops import day1_verify as V

SRC = (Path(V.__file__)).read_text(encoding="utf-8")


def test_module_has_no_write_commit_push_decision_or_portal_code():
    for bad in ("git commit", "\"commit\"", "\"push\"", "write_text(\"run_mode", "competition_day", "run_competition_day",
                "auto_upload.execute", "portal_driver", "set_input_files", "ops.yaml\", \"w\"", "yaml.safe_dump"):
        assert bad not in SRC, bad
    assert "ls-remote" in SRC                                    # origin sync without fetch


@pytest.fixture
def isolated_logs(monkeypatch, tmp_path):
    ops = V.load_ops_config()
    ops = dict(ops, paths=dict(ops["paths"], ops_logs_dir=str(tmp_path / "ops")))
    monkeypatch.setattr(V, "load_ops_config", lambda: ops)
    return ops, tmp_path


def test_failure_is_never_silent(monkeypatch, isolated_logs):
    _, tmp = isolated_logs
    monkeypatch.setattr(V, "git_checks", lambda: (_ for _ in ()).throw(RuntimeError("git unavailable")))
    r = V.verify(dry_run=True)
    assert r["RUN_MODE_SWITCH_STATUS"] == "FAIL" and r["MANUAL_ACTION_REQUIRED"] == "YES"
    assert any("git unavailable" in x for x in r["failure_reasons"])
    assert (tmp / "ops" / "day1" / "latest.json").exists() and (tmp / "ops" / "day1" / "verify.jsonl").exists()


def test_all_pass_only_when_every_check_passes(monkeypatch, isolated_logs):
    ok = lambda name: [V._check(name, True, "ok")]  # noqa: E731
    monkeypatch.setattr(V, "git_checks", lambda: ok("branch_is_master"))
    monkeypatch.setattr(V, "config_checks", lambda ops: [V._check(n, True, d) for n, d in (
        ("run_mode_competition", "run_mode=COMPETITION"), ("team_id", "TEAM_11442 (OK)"), ("quant_fingerprint", V.FROZEN_SHA),
        ("auto_upload_disabled", "auto_upload.enabled=False"), ("previous_trading_day", "datapack=2026-10-22 refresh=2026-10-22"))])
    monkeypatch.setattr(V, "task_checks", lambda: ok("task_1930_exists"))
    monkeypatch.setattr(V, "preflight_checks", lambda: ([V._check("competition_preflight_no_blocked", True, "overall=WARNING"),
                                                         V._check("preflight_competition_initial", True, "PREFLIGHT WARN")],
                                                        {"warnings": ["submission_window: not open yet"]}))
    r = V.verify()
    assert r["RUN_MODE_SWITCH_STATUS"] == "PASS" and r["MANUAL_ACTION_REQUIRED"] == "NO"
    assert r["RUN_MODE"] == "COMPETITION" and r["TEAM_ID"] == "TEAM_11442" and r["PREVIOUS_TRADING_DAY"] == "2026-10-22"
    assert r["QUANT_FREEZE"] == "PASS" and r["AUTO_UPLOAD_ENABLED"] == "false" and r["COMPETITION_PREFLIGHT"] == "PASS"
    assert r["NEXT_FORMAL_RUN"] == "2026-10-26T19:30:00+08:00" and r["warnings"]          # warnings reported, not hidden
    monkeypatch.setattr(V, "config_checks", lambda ops: [V._check("run_mode_competition", False, "run_mode=PRECOMPETITION")])
    r = V.verify()
    assert r["RUN_MODE_SWITCH_STATUS"] == "FAIL" and "run_mode_competition: run_mode=PRECOMPETITION" in r["failure_reasons"]


def test_config_checks_on_current_config_report_real_values():
    ops = V.load_ops_config()
    names = {c["check"]: c for c in V.config_checks(ops)}
    bound = (ops.get("team") or {}).get("competition_team_id") == V.TEAM      # TEAM_11442 binding arrives with PR #8
    assert names["team_id"]["status"] == ("PASS" if bound else "FAIL")
    assert names["run_mode_competition"]["status"] == ("PASS" if ops.get("run_mode") == "COMPETITION" else "FAIL")
    assert names["quant_fingerprint"]["status"] == "PASS"
    assert names["auto_upload_disabled"]["status"] == "PASS"
    assert names["plan_1930_targets_day1"]["detail"].startswith("plan at 2026-10-26T19:30:00+08:00")
