"""Issue #43: tactical records are published to shared-state, honest about submission status, downstream only."""
import json
import subprocess

import pytest

from agent.ops import shared_state_sync as S
from agent.ops import shared_state_tactical as TS


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=str(cwd), capture_output=True, text=True, check=True).stdout


@pytest.fixture
def env(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    root = tmp_path / "root"
    root.mkdir()
    git(root, "init", "-q", "-b", "master")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    git(root, "remote", "add", "origin", str(origin))
    (root / "README.md").write_text("prod\n", encoding="utf-8")
    (root / ".gitignore").write_text("/logs/\n/.worktrees/\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return root, origin


def put(root, name, rec):
    d = root / "logs" / "tactical"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(rec), encoding="utf-8")


def show(origin, path):
    return subprocess.run(["git", "--git-dir", str(origin), "show", f"shared-state:{path}"], capture_output=True, check=True).stdout


REC = {"trade_date": "2026-11-09", "phase": "ENTRY", "status": "APPLIED", "version": "TACTICAL_OVERRIDE_V1", "fingerprint": "abc",
       "x_effective": 0.2, "sells": {"2337": 77000}, "buys": {"2891": 366000}}


def test_record_is_published_with_unconfirmed_status_and_latest_pointer(env):
    root, origin = env
    put(root, "2026-11-09_ENTRY.json", REC)
    r = TS.publish(root)
    assert r[0]["status"] == "SYNCED"
    doc = json.loads(show(origin, "shared_state/tactical/2026-11-09_ENTRY.json"))
    assert doc["submission_status"] == "NOT_CONFIRMED" and doc["final_sha256"] is None      # never claims a confirmation it lacks
    assert doc["sells"] == REC["sells"] and doc["version"] == "TACTICAL_OVERRIDE_V1"
    latest = json.loads(show(origin, "shared_state/tactical/latest.json"))
    assert latest["trade_date"] == "2026-11-09" and latest["phase"] == "ENTRY" and latest["record_path"].endswith("ENTRY.json")


def test_republish_is_idempotent_and_unwind_overdue_is_visible(env):
    root, origin = env
    put(root, "2026-11-09_ENTRY.json", REC)
    TS.publish(root)
    assert TS.publish(root)[0]["status"] == "ALREADY_SYNCED"
    put(root, "2026-11-10_UNWIND.json", {"trade_date": "2026-11-10", "phase": "UNWIND", "status": "UNWIND_OVERDUE",
                                        "tactical_status": "TACTICAL_UNWIND_OVERDUE", "version": "TACTICAL_OVERRIDE_V1", "fingerprint": "abc"})
    TS.publish(root)
    latest = json.loads(show(origin, "shared_state/tactical/latest.json"))
    assert latest["phase"] == "UNWIND" and latest["tactical_status"] == "TACTICAL_UNWIND_OVERDUE"


def test_failure_never_raises_and_keeps_production_clean(env):
    root, origin = env
    put(root, "2026-11-09_ENTRY.json", REC)
    git(root, "remote", "set-url", "origin", str(origin) + "-missing")
    r = TS.publish(root)
    assert r[-1]["status"] == "SYNC_PENDING"
    assert git(root, "status", "--porcelain").strip() == "" and git(root, "branch", "--show-current").strip() == "master"


def test_sweep_hook_publishes_tactical_without_breaking_submission_sync(env):
    root, origin = env
    put(root, "2026-11-09_ENTRY.json", REC)
    (root / "submissions").mkdir()
    assert S.sweep(root) == []                       # no confirmed FINALs, still no exception
    assert json.loads(show(origin, "shared_state/tactical/latest.json"))["trade_date"] == "2026-11-09"
