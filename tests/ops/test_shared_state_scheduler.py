"""Issue #65: scheduler status snapshot for shared-state (redacted whitelist, heartbeat delay)."""
import json
from datetime import datetime, timezone, timedelta

from agent.ops import shared_state_scheduler as X

TZ = timezone(timedelta(hours=8))


def test_start_heartbeat_reports_delay():
    d = X.build("dryrun_1930", "START", None, datetime(2026, 11, 10, 20, 16, 40, tzinfo=TZ))
    assert d["status"] == "RUNNING" and d["run_delay_minutes"] == 46 and d["scheduled_local"] == "19:30"


def test_end_snapshot_is_whitelisted_and_redacted(tmp_path):
    (tmp_path / "logs" / "scheduled").mkdir(parents=True)
    src = {"status": "BLOCKED", "blocked_reason": r"PREFLIGHT_BLOCK at C:\Users\someone\x\y.log", "trade_date": "2026-11-11",
           "log_file": r"C:\Users\someone\logs\a.log", "secret_token": "abc", "run_delay_minutes": 56}
    (tmp_path / "logs" / "scheduled" / "latest_status.json").write_text(json.dumps(src), encoding="utf-8")
    d = X.build("dryrun_1930", "END", tmp_path)
    assert d["status"] == "BLOCKED" and d["run_delay_minutes"] == 56 and d["trade_date_key"] == "2026-11-11"
    assert "log_file" not in d and "secret_token" not in d
    assert "someone" not in json.dumps(d) and "<path>" in d["blocked_reason"]


def test_missing_status_file_is_reported(tmp_path):
    assert X.build("evaluation_1700", "END", tmp_path)["status"] == "STATUS_FILE_MISSING"
