"""Round 06 tools: security scan (redaction), backup / restore (no secrets, hash verified, no overwrite),
readiness score caps, network-degraded behaviour, source stats."""
import json
import zipfile
from pathlib import Path

import pytest

from agent.ops.common import Clock


def _fake_secret(prefix: str, n: int) -> str:
    return prefix + "".join("abcdefghijklmnopqrstuvwxyzABCDEFGHIJ0123456789"[i % 46] for i in range(n))


def test_security_scan_detects_and_redacts(tmp_path):
    from agent.ops.security_scan import scan, write_report
    g = _fake_secret("AI" + "za", 35)
    o = _fake_secret("sk" + "-", 40)
    f = tmp_path / "leak.py"
    f.write_text(f'GEMINI = "{g}"\nOPENAI="{o}"\npwd = "harmless"\n'
                 f'url = "postgres://user:{"pa" + "ss"}word123@host/db"\n', encoding="utf-8")
    clean = tmp_path / "clean.py"
    clean.write_text("x = 1\npassword = '********'\n", encoding="utf-8")
    res = scan([f, clean], include_untracked_logs=False)
    types = {x["type"] for x in res["findings"]}
    assert {"google_api_key", "openai_api_key", "connection_string"} <= types
    assert all(x["file"].endswith("leak.py") for x in res["findings"])
    out = write_report(res, tmp_path / "scan.md")
    txt = out.read_text(encoding="utf-8") + out.with_suffix(".json").read_text(encoding="utf-8")
    assert g not in txt and o not in txt                                  # never the full secret


def test_security_scan_env_value_match(tmp_path, monkeypatch):
    from agent.ops.security_scan import scan
    v = _fake_secret("zz", 30)
    monkeypatch.setenv("GEMINI_API_KEY", v)
    f = tmp_path / "log.jsonl"
    f.write_text('{"prompt": "...' + v + '..."}\n', encoding="utf-8")
    res = scan([f], include_untracked_logs=False)
    assert any(x["type"] == "env_value:GEMINI_API_KEY" for x in res["findings"])
    assert res["env_keys_present"]["GEMINI_API_KEY"] == "PRESENT"


def test_backup_restore_excludes_secrets_and_never_overwrites(tmp_path, ops_cfg):
    from agent.ops.backup import backup, restore, verify
    sd = Path(ops_cfg["paths"]["settlement_dir"])
    sd.mkdir(parents=True)
    (sd / "20261026_internal.json").write_text("{}", encoding="utf-8")
    (sd / ".env").write_text("GEMINI_API_KEY=should-never-be-backed-up", encoding="utf-8")
    z = backup(tmp_path / "bk", ops_cfg=ops_cfg, base=tmp_path)
    names = zipfile.ZipFile(z).namelist()
    assert not any(n.endswith(".env") for n in names) and "BACKUP_MANIFEST.json" in names
    assert not any("data/history" in n or "data/raw" in n for n in names)
    assert verify(z) == []
    r = restore(z, tmp_path / "restored")
    assert r["restored_files"] >= 1
    with pytest.raises(FileExistsError):
        restore(z, tmp_path / "restored")


def test_readiness_caps_at_dry_run_without_nc1(monkeypatch):
    from agent.ops import readiness as R
    res = R.assess({"ok": True, "failed": 0, "summary": "n passed"})
    assert res["level"] != "COMPETITION_READY"
    assert res["nc1_status"] == "unknown" and "NC-1" in (res["cap_reason"] or "")
    assert any("NC-1" in b for b in res["blockers"])


def test_network_down_t1_stored_degraded_missing_blocks(fixture_store, ops_cfg, tmp_path):
    from agent.competition_day import run_competition_day
    from agent.ops.refresh_daily import offline_fetchers
    from tests.ops.conftest import CLEAN_GIT, store_without_date
    kw = dict(store_is_fixture=True, ops_cfg=ops_cfg, clock=Clock("2026-10-25T20:00:00+08:00"), git=CLEAN_GIT,
              archive_readonly=False, initial=True, refresh_fetchers=offline_fetchers(), write_report=False)
    s = run_competition_day("2026-10-26", "TEAM_TEST", "dry-run", store=fixture_store, **kw)
    assert s["status"] == "DRY_RUN_OK" and s["degradation_level"] == 2 and s["data_health"] == "WARN"
    st = store_without_date(fixture_store, tmp_path / "st", "2026-10-23")
    b = run_competition_day("2026-10-26", "TEAM_TEST", "dry-run", store=st, **kw)
    assert b["status"] == "BLOCKED" and "twse_prices" in b["reason"]     # never an outdated critical price


def test_source_stats_counts_attempts(tmp_path, monkeypatch):
    import agent.ops.source_stats as S
    logs = tmp_path / "logs"
    d = logs / "20261006"
    d.mkdir(parents=True)
    rec = lambda st: {"sources": [{"source": "twse_prices", "criticality": "CRITICAL", "status": st,  # noqa: E731
                                    "duration": 1.0, "fetched_at": "2026-10-05T15:00:00+08:00", "detail": {}}]}
    (d / "data_health_history.jsonl").write_text("\n".join(json.dumps(rec(s)) for s in ("OK", "STALE", "OK", "CACHED")),
                                                 encoding="utf-8")
    cfg = {"paths": {"ops_logs_dir": str(logs), "etf_snapshots_dir": str(tmp_path / "etf")}}
    monkeypatch.setattr(S, "load_ops_config", lambda: cfg)
    rows, etf = S.collect()
    r = rows[0]
    assert (r["attempts"], r["success"], r["stale"], r["fallback"], r["failure"]) == (4, 2, 1, 1, 0)
