"""Official 開賽前試繳 rehearsal tooling (Issue #4): read-only scan + step-by-step probe. No pre-window D-Plan path:
the competition window guard and the frozen pipeline's C6 check stay exactly as they are."""
import inspect
from datetime import datetime

from agent.competition_day import run_competition_day
from agent.submission import rehearsal as R
from tests.ops.test_competition_day import T1, run


def at(s):
    return datetime.fromisoformat(s + "+08:00")


def test_window_guard_still_blocks_pre_window_generation(fixture_store, ops_cfg):
    s = run(fixture_store, ops_cfg, T1, "2026-10-25T15:03:00+08:00", mode="dry-run", initial=True)
    assert s["status"] == "BLOCKED" and "submission_window_open" in s["reason"]
    assert "rehearsal" not in inspect.signature(run_competition_day).parameters        # no override exists


def test_rehearsal_window_bounds(ops_cfg):
    cfg = dict(ops_cfg, submission=dict(ops_cfg.get("submission") or {}, rehearsal_window={
        "opens": "2026-10-23T20:30:00+08:00", "closes": "2026-10-26T00:00:00+08:00", "trade_date": "2026-10-27"}))
    assert not R.in_window(at("2026-10-23T20:29:59"), cfg)[0]
    assert R.in_window(at("2026-10-24T10:00:00"), cfg)[0]
    assert not R.in_window(at("2026-10-26T00:00:00"), cfg)[0]
    no = dict(ops_cfg, submission={k: v for k, v in (ops_cfg.get("submission") or {}).items() if k != "rehearsal_window"})
    assert R.in_window(at("2026-10-24T10:00:00"), no) == (False, None)
    assert str(R.rehearsal_root("2026-10-27")).endswith("20261027_rehearsal")


def test_probe_click_allowlist_is_narrow():
    assert "登出" not in R.CLICK_ALLOWLIST and "下載資料包" not in R.CLICK_ALLOWLIST
    assert "上傳說明文件" not in R.CLICK_ALLOWLIST                   # the strategy PDF is the Owner's upload
    assert {"上傳試繳檔案", "送出繳交"} <= set(R.CLICK_ALLOWLIST)
    assert not hasattr(R, "generate")                                  # no trial-D-Plan generator
