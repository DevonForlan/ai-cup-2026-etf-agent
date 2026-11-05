"""Issue #33: completed daily evaluations are published to the shared-state branch; downstream only."""
import json
import subprocess

import pytest

from agent.ops import shared_state_evaluations as E
from agent.ops import shared_state_sync as S


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=str(cwd), capture_output=True, text=True, check=True).stdout


def report(date="2026-11-02", etype="COMPETITION_DAY_ESTIMATE", nav="961,809,259", cum="-3.82%", overall="READY",
          comp="PASS", recon="PASS", attr="PASS", active="46.07%（00985A）", mdd="7.01%"):
    rows = [("NAV", nav), ("Daily return", "-1.01%"), ("Cumulative return", cum), ("MDD", mdd), ("Turnover", "0.00%"),
            ("Fees", "0"), ("Tax", "0"), ("Cash weight", "15.43%"), ("Holdings", "24")]
    if active:
        rows.append(("Active Share (official, end of day)", active))
    rows += [("NAV reconciliation", recon), ("Return attribution check", attr), ("Positive holding ratio（diagnostic only）", "33.33%")]
    kp = "\n".join(f"| {k} | {v} |" for k, v in rows)
    return f"""# Daily Evaluation — {date}（{etype}）

> **{etype}** — 正式比賽日預估：**不是官方結算**。

## Previous prediction

| 項目 | 值 |
|---|---|
| D-Plan file | `submissions\\20261102\\FINAL\\D-Plan_TEAM_11442_2026-11-02.json`（v4.3） |
| Starting point | OFFICIAL_SETTLEMENT（2026-10-30） |
| Execution | 0 filled / 0 orders |

## Actual result

| KPI | 值 |
|---|---|
{kp}

## Compliance: **{comp}**

## Holdings result

| Ticker | Name | Weight | Daily return | Contribution |
|---|---|---|---|---|
| 2347 | 聯強 | 3.52% | -5.03% | -0.184% |
| 3081 | 聯亞 | 3.01% | +1.90% | +0.056% |

## Largest positive contributors

- 3081 聯亞 +0.056%

## Largest negative contributors

- 2347 聯強 -0.184%

## Overall: **{overall}**
"""


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
    (root / ".gitignore").write_text("/reports/\n/.worktrees/\n/logs/\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return root, origin


def put(root, text, date="2026-11-02"):
    d = root / "reports" / "daily_evaluations"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{date}_evaluation.md"
    p.write_text(text, encoding="utf-8")
    return p


def show(origin, path):
    return subprocess.run(["git", "--git-dir", str(origin), "show", f"shared-state:{path}"], capture_output=True,
                          check=True).stdout


def test_completed_evaluation_is_published_from_the_report_values(env):
    root, origin = env
    p = put(root, report())
    r = E.publish(p, root)
    assert r["status"] == "SYNCED"
    ev = json.loads(show(origin, f"{E.REL}/2026-11-02/evaluation.json"))
    assert (ev["nav"], ev["daily_return_pct"], ev["cumulative_return_pct"], ev["mdd_pct"]) == (961809259.0, -1.01, -3.82, 7.01)
    assert (ev["cash_weight_pct"], ev["holdings_count"], ev["active_share_pct"], ev["active_share_vs"]) == (15.43, 24, 46.07, "00985A")
    assert ev["compliance"] == ev["nav_reconciliation"] == ev["return_attribution_check"] == "PASS"
    assert ev["largest_negative_contributors"][0] == {"ticker": "2347", "name": "聯強", "contribution_pct": -0.184}
    assert ev["largest_positive_contributors"][0]["ticker"] == "3081" and len(ev["holdings"]) == 2
    assert ev["source_sha256"] == "sha256:" + S._sha(p.read_bytes()) and ev["source_report"] == "reports/daily_evaluations/2026-11-02_evaluation.md"
    latest = json.loads(show(origin, f"{E.REL}/latest.json"))
    assert latest["trade_date"] == "2026-11-02" and latest["cumulative_return_pct"] == -3.82 and latest["nav"] == 961809259.0
    assert latest["evaluation_path"] == f"{E.REL}/2026-11-02/evaluation.json"


def test_estimate_label_is_preserved_and_never_called_official(env):
    root, origin = env
    E.publish(put(root, report()), root)
    latest = json.loads(show(origin, f"{E.REL}/latest.json"))
    assert latest["evaluation_type"] == "COMPETITION_DAY_ESTIMATE" and latest["is_official_settlement"] is False
    md = show(origin, f"{E.REL}/2026-11-02/summary.md").decode("utf-8")
    assert "NOT the organiser's official settlement" in md and "COMPETITION_DAY_ESTIMATE" in md and "-3.82" in md


@pytest.mark.parametrize("kw", [dict(overall="BLOCKED"), dict(comp="FAIL"), dict(recon="FAIL"), dict(attr="FAIL"),
                                dict(etype="PRECOMPETITION_PAPER_RUN"), dict(nav="-"), dict(overall="PARTIAL")])
def test_only_completed_evaluations_are_published(env, kw):
    root, origin = env
    r = E.publish(put(root, report(**kw)), root)
    assert r["status"] in ("SKIPPED", "SYNC_PENDING") and r["status"] != "SYNCED"
    assert not (root / ".worktrees" / "shared-state").exists()


def test_pre_competition_dates_are_never_published(env):
    root, _ = env
    assert E.publish(put(root, report(date="2026-10-21"), "2026-10-21"), root)["status"] == "SKIPPED"


def test_missing_optional_fields_stay_null(env):
    root, origin = env
    E.publish(put(root, report(active=None)), root)
    ev = json.loads(show(origin, f"{E.REL}/2026-11-02/evaluation.json"))
    assert ev["active_share_pct"] is None and ev["active_share_vs"] is None
    assert "not available" in show(origin, f"{E.REL}/2026-11-02/summary.md").decode("utf-8")


def test_repeat_is_idempotent_and_correction_keeps_the_previous_version(env):
    root, origin = env
    p = put(root, report())
    E.publish(p, root)
    n1 = git(origin, "rev-list", "--count", "shared-state").strip()
    assert E.publish(p, root)["status"] == "ALREADY_SYNCED"
    assert git(origin, "rev-list", "--count", "shared-state").strip() == n1
    old = "sha256:" + S._sha(p.read_bytes())
    p = put(root, report(cum="-3.90%"))
    assert E.publish(p, root)["status"] == "SYNCED"
    ev = json.loads(show(origin, f"{E.REL}/2026-11-02/evaluation.json"))
    assert ev["cumulative_return_pct"] == -3.9 and ev["supersedes"][0]["source_sha256"] == old
    arch = json.loads(show(origin, f"{E.REL}/2026-11-02/superseded/{old.replace('sha256:', '')[:8]}/evaluation.json"))
    assert arch["cumulative_return_pct"] == -3.82
    assert json.loads(show(origin, f"{E.REL}/latest.json"))["cumulative_return_pct"] == -3.9


def test_latest_only_moves_forward_and_sweep_backfills_everything(env):
    root, origin = env
    put(root, report(date="2026-11-03", cum="-9.53%"), "2026-11-03")
    put(root, report(date="2026-11-02"), "2026-11-02")
    put(root, report(date="2026-10-21"), "2026-10-21")
    res = E.sweep(root)
    assert sorted(r["trade_date"] for r in res) == ["2026-11-02", "2026-11-03"]
    assert json.loads(show(origin, f"{E.REL}/latest.json"))["trade_date"] == "2026-11-03"
    files = set(git(origin, "ls-tree", "-r", "--name-only", "shared-state").split())
    assert f"{E.REL}/2026-11-02/evaluation.json" in files and not any("2026-10-21" in f for f in files)


def test_sync_failure_never_raises_changes_the_report_and_retries_later(env):
    root, origin = env
    p = put(root, report())
    before = p.read_bytes()
    git(root, "remote", "set-url", "origin", str(origin) + "-missing")
    r = E.publish(p, root)
    assert r["status"] == "SYNC_PENDING"
    assert "2026-11-02" in json.loads((root / "logs" / "shared_state" / "pending_evaluations.json").read_text())["pending"]
    assert p.read_bytes() == before
    git(root, "remote", "set-url", "origin", str(origin))
    out = E.sweep(root)
    assert out and out[0]["status"] == "SYNCED"
    assert not (root / "logs" / "shared_state" / "pending_evaluations.json").exists()


def test_production_checkout_stays_clean_and_only_whitelisted_files_are_published(env):
    root, origin = env
    put(root, report())
    (root / "logs" / "evaluation").mkdir(parents=True)
    (root / "logs" / "evaluation" / "latest_status.json").write_text('{"token": "SECRET-TOKEN"}', encoding="utf-8")
    E.publish(root / "reports" / "daily_evaluations" / "2026-11-02_evaluation.md", root)
    assert git(root, "status", "--porcelain").strip() == "" and git(root, "branch", "--show-current").strip() == "master"
    files = set(git(origin, "ls-tree", "-r", "--name-only", "shared-state").split())
    assert files == {".gitattributes", f"{E.REL}/latest.json", f"{E.REL}/2026-11-02/evaluation.json", f"{E.REL}/2026-11-02/summary.md"}
    assert "SECRET-TOKEN" not in "".join(show(origin, f).decode("utf-8") for f in files)


def test_evaluation_run_hook_cannot_break_the_evaluation(monkeypatch):
    from agent.ops import daily_evaluation as D

    def boom(*a, **k):
        raise RuntimeError("github down")
    monkeypatch.setattr(E, "sweep", boom)
    D._publish_shared_state()          # must not raise
