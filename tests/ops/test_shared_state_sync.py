"""Issue #31: SUBMISSION_CONFIRMED FINALs are published byte-exact to the shared-state branch; downstream only."""
import hashlib
import json
import subprocess

import pytest

from agent.ops import shared_state_sync as S

TEAM = "TEAM_11442"


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
    (root / ".gitignore").write_text("/submissions/\n/.worktrees/\n/logs/\n/data/\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return root, origin


def make_final(root, date="2026-11-02", state="SUBMISSION_CONFIRMED", plan=None, team=TEAM, tamper=False):
    plan = plan or {"trade_date": date, "team_id": team, "orders": [], "no_trade_decisions": [{"ticker": "2337"}],
                    "market_view": {"regime": "risk_off", "stance": "defensive"},
                    "agent_metadata": {"code_version": "git:abc1234"}}
    day = root / "submissions" / date.replace("-", "")
    (day / "FINAL").mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(plan, ensure_ascii=False, indent=2) + "\r\n").encode("utf-8")   # odd EOL on purpose: bytes must survive
    (day / "FINAL" / f"D-Plan_{team}_{date}.json").write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    st = {"trade_date": date, "state": state, "team_id": team,
          "dplan_sha256": "sha256:" + ("0" * 64 if tamper else sha),
          "history": [{"at": "2026-11-01T21:22:32+08:00", "to": "SUBMITTED_UNVERIFIED"},
                      {"at": "2026-11-01T21:22:35+08:00", "to": state}]}
    (day / "submission_state.json").write_text(json.dumps(st), encoding="utf-8")
    return raw, sha


def remote_show(origin, path):
    return subprocess.run(["git", "--git-dir", str(origin), "show", f"shared-state:{path}"], capture_output=True,
                          check=True).stdout


def test_confirmed_final_is_published_byte_exact_with_latest_pointer(env):
    root, origin = env
    raw, sha = make_final(root)
    r = S.sync("2026-11-02", root)
    assert r["status"] == "SYNCED" and r["final_sha256"] == sha
    snap = remote_show(origin, f"{S.REL}/2026-11-02/FINAL.json")
    assert snap == raw and hashlib.sha256(snap).hexdigest() == sha
    latest = json.loads(remote_show(origin, f"{S.REL}/latest.json"))
    assert latest["final_path"] == f"{S.REL}/2026-11-02/FINAL.json" and latest["final_sha256"] == sha
    assert latest["submission_status"] == "SUBMISSION_CONFIRMED" and latest["team_id"] == TEAM
    assert latest["submitted_at"] and latest["synced_at"]
    summary = remote_show(origin, f"{S.REL}/2026-11-02/summary.md").decode("utf-8")
    assert sha in summary and "exact, byte-for-byte snapshot" in summary and "risk_off" in summary
    assert "git:abc1234" in summary
    assert "not available" in summary                       # missing fields are not invented


def test_only_confirmed_dates_are_synced(env):
    root, origin = env
    for st in ("READY_TO_SUBMIT", "SUBMITTED_UNVERIFIED", "NOT_READY"):
        make_final(root, state=st)
        assert S.sync("2026-11-02", root)["status"] == "SKIPPED"
    assert S.sweep(root) == []
    assert not (root / ".worktrees" / "shared-state").exists()


def test_state_file_and_final_that_disagree_are_never_published(env):
    root, _ = env
    make_final(root, tamper=True)
    assert S.sync("2026-11-02", root)["status"] == "SKIPPED"


def test_test_team_plans_are_never_published(env):
    root, _ = env
    make_final(root, team="TEAM_TEST")
    assert S.sync("2026-11-02", root)["status"] == "SKIPPED"


def test_repeat_is_idempotent_no_duplicate_commit(env):
    root, origin = env
    make_final(root)
    S.sync("2026-11-02", root)
    n1 = git(origin, "rev-list", "--count", "shared-state").strip()
    r = S.sync("2026-11-02", root)
    assert r["status"] == "ALREADY_SYNCED"
    assert git(origin, "rev-list", "--count", "shared-state").strip() == n1


def test_superseding_final_keeps_the_previous_one_and_moves_latest(env):
    root, origin = env
    raw1, sha1 = make_final(root)
    S.sync("2026-11-02", root)
    raw2, sha2 = make_final(root, plan={"trade_date": "2026-11-02", "team_id": TEAM, "orders": [{"ticker": "2330"}],
                                        "no_trade_decisions": [], "market_view": {"regime": "neutral"}})
    assert sha1 != sha2 and S.sync("2026-11-02", root)["status"] == "SYNCED"
    assert remote_show(origin, f"{S.REL}/2026-11-02/FINAL.json") == raw2
    assert remote_show(origin, f"{S.REL}/2026-11-02/superseded/{sha1[:8]}/FINAL.json") == raw1
    man = json.loads(remote_show(origin, f"{S.REL}/2026-11-02/manifest.json"))
    assert man["supersedes"] == [sha1] and man["final_sha256"] == sha2
    assert json.loads(remote_show(origin, f"{S.REL}/latest.json"))["final_sha256"] == sha2


def test_backfill_of_an_older_date_does_not_move_latest(env):
    root, origin = env
    make_final(root, date="2026-11-03")
    make_final(root, date="2026-11-02")
    S.sync("2026-11-03", root)
    S.sync("2026-11-02", root)
    assert json.loads(remote_show(origin, f"{S.REL}/latest.json"))["trade_date"] == "2026-11-03"


def test_push_failure_never_raises_leaves_pending_and_retries_later(env):
    root, origin = env
    raw, sha = make_final(root)
    git(root, "remote", "set-url", "origin", str(origin) + "-missing")
    r = S.sync("2026-11-02", root)
    assert r["status"] == "SYNC_PENDING"
    assert "2026-11-02" in json.loads((root / "logs" / "shared_state" / "pending.json").read_text())["pending"]
    st = json.loads((root / "submissions" / "20261102" / "submission_state.json").read_text())
    assert st["state"] == "SUBMISSION_CONFIRMED"           # the submission is untouched
    git(root, "remote", "set-url", "origin", str(origin))
    out = S.sweep(root)
    assert out and out[0]["status"] == "SYNCED"
    assert not (root / "logs" / "shared_state" / "pending.json").exists()
    assert remote_show(origin, f"{S.REL}/2026-11-02/FINAL.json") == raw


def test_production_checkout_stays_clean_and_on_its_branch(env):
    root, _ = env
    make_final(root)
    S.sync("2026-11-02", root)
    assert git(root, "status", "--porcelain").strip() == ""
    assert git(root, "branch", "--show-current").strip() == "master"
    assert git(root, "rev-parse", "HEAD").strip() == git(root, "rev-parse", "master").strip()


def test_only_the_final_and_whitelisted_metadata_are_published(env):
    root, origin = env
    make_final(root)
    day = root / "submissions" / "20261102"
    (day / "receipts.jsonl").write_text('{"cookie": "SECRET-COOKIE"}\n', encoding="utf-8")
    (root / "data" / "submission_evidence").mkdir(parents=True)
    (root / "data" / "submission_evidence" / "shot.png").write_bytes(b"png")
    S.sync("2026-11-02", root)
    files = set(git(origin, "ls-tree", "-r", "--name-only", "shared-state").split())
    assert files == {".gitattributes", f"{S.REL}/latest.json", f"{S.REL}/2026-11-02/FINAL.json", f"{S.REL}/2026-11-02/manifest.json",
                     f"{S.REL}/2026-11-02/summary.md"}
    blob = "".join(remote_show(origin, f).decode("utf-8") for f in files)
    assert "SECRET-COOKIE" not in blob


def test_auto_upload_hook_cannot_break_a_confirmed_submission(monkeypatch):
    from agent.submission import auto_upload as A

    def boom(*a, **k):
        raise RuntimeError("github down")
    monkeypatch.setattr(S, "sweep", boom)
    A._publish_shared_state()          # must not raise
