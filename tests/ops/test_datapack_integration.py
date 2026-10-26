"""Official DataPack integration: validation, freshness gate (official calendar), competition gate without
fallback, precompetition behaviour, settlement_source metadata, providers (no portal automation)."""
import json
import shutil
from pathlib import Path

import pytest

from agent.ops import datapack as DP
from agent.ops import scheduled_run as S
from agent.ops.datapack_downloader import ManualFileProvider, OfficialPortalProvider, fetch_latest_datapack
from tests.ops.test_competition_day import CLK1, CLK2, T1, T2, official_from, run, save_official

FX = Path(__file__).resolve().parents[1] / "fixtures" / "datapack"
ROOT = Path(__file__).resolve().parents[2]
VALID = FX / "official_example_3_1_valid_TEAM_042_2026-10-28.json"


def v(name, trade="2026-10-28", team="TEAM_042"):
    return DP.validate_official_datapack(FX / name, team, trade, first_trade_date="2026-10-27")


# ---------------------------------------------------------------- 1-7 validation
def test_valid_official_example_passes():
    r = v(VALID.name)
    assert r["status"] == "PASS" and r["freshness"] == "FRESH" and r["settlement_date"] == "2026-10-27"
    assert r["official"]["holdings"]["2330"] == 73000 and len(r["official"]["holdings"]) == 22
    assert float(r["official"]["nav"]) == 999795141.0 and r["schema_version"] == "3.0"


@pytest.mark.parametrize("name,needle", [
    ("synthetic_malformed.json", "unreadable JSON"),
    ("synthetic_unsupported_schema.json", "unsupported schema_version"),
    ("synthetic_missing_nav.json", "nav_tradable"),
    ("synthetic_negative_cash.json", "cash"),
    ("synthetic_negative_shares.json", "negative shares"),
    ("synthetic_invalid_code.json", "invalid code"),
    ("synthetic_duplicate_code.json", "duplicate code"),
])
def test_invalid_datapacks_are_blocked(name, needle):
    r = v(name)
    assert r["status"] == "BLOCKED" and r["reason"] == "DATAPACK_INVALID", r
    assert any(needle in p for p in r["problems"]), r["problems"]


def test_nav_identity_is_checked():
    d = json.loads(VALID.read_text(encoding="utf-8"))
    d["account"]["nav_tradable"] += 5000
    r = DP.validate_official_datapack(d, "TEAM_042", "2026-10-28")
    assert r["status"] == "BLOCKED" and any("nav_tradable" in p for p in r["problems"])


# ---------------------------------------------------------------- 8-9 freshness (official calendar)
def test_previous_trading_day_uses_official_calendar():
    assert DP.previous_trading_day("2026-10-28") == "2026-10-27"
    assert DP.previous_trading_day("2026-10-27") == "2026-10-22"        # 10-26 closed, weekend skipped, 10-23
                                                                         # typhoon closure (Issue #11, 2026-10-25)
    assert DP.previous_trading_day("2026-10-12") == "2026-10-08"        # 10-09 closed
    assert DP.previous_trading_day("2026-11-02") == "2026-10-30"


def test_stale_and_not_ready_datapacks():
    r = v("synthetic_stale_TEAM_042.json")                              # prepared for 10-27, we need 10-28
    assert r["status"] == "BLOCKED" and r["reason"] == "DATAPACK_STALE"
    r = v("official_example_3_2b_not_ready_TEAM_042_2026-10-29.json", trade="2026-10-29")
    assert r["status"] == "BLOCKED" and r["reason"] == "DATAPACK_STALE"   # missing prev_settlement, null != empty
    d = json.loads(VALID.read_text(encoding="utf-8"))
    d["as_of_date"] = "2026-10-26"                                      # right trade date, wrong settlement day
    r = DP.validate_official_datapack(d, "TEAM_042", "2026-10-28", first_trade_date="2026-10-27")
    assert r["reason"] == "DATAPACK_STALE" and any("2026-10-27" in p for p in r["problems"])


def test_first_day_datapack_only_on_first_trading_day():
    r = v("official_example_3_2a_first_day_TEAM_042_2026-10-27.json", trade="2026-10-27")
    assert r["status"] == "PASS" and r["freshness"] == "INITIAL_DAY"


# ---------------------------------------------------------------- 10, 12, 13 gate
def _dir_with(tmp_path, *names):
    d = tmp_path / "official"
    d.mkdir(parents=True)
    for n in names:
        shutil.copy2(FX / n, d / n)
    return ManualFileProvider(d)


def test_gate_missing_stale_invalid_and_pass(tmp_path):
    g = DP.datapack_gate("2026-10-28", "TEAM_042", provider=ManualFileProvider(tmp_path / "empty"))
    assert g["status"] == "BLOCKED" and g["reason"] == "DATAPACK_MISSING"
    g = DP.datapack_gate("2026-10-28", "TEAM_042", provider=_dir_with(tmp_path / "a", "synthetic_stale_TEAM_042.json"))
    assert g["status"] == "BLOCKED" and g["reason"] == "DATAPACK_STALE"
    g = DP.datapack_gate("2026-10-28", "TEAM_042", provider=_dir_with(tmp_path / "b", "synthetic_unsupported_schema.json"))
    assert g["status"] == "BLOCKED" and g["reason"] == "DATAPACK_INVALID"
    g = DP.datapack_gate("2026-10-28", "TEAM_042", provider=_dir_with(tmp_path / "c", VALID.name,
                                                                      "synthetic_stale_TEAM_042.json"))
    assert g["status"] == "PASS" and g["settlement_date"] == "2026-10-27" and g["file"].endswith(VALID.name)
    g = DP.datapack_gate("2026-10-27", "TEAM_042", provider=ManualFileProvider(tmp_path / "e2"), initial=True)
    assert g["status"] == "PASS" and g["freshness"] == "INITIAL_DAY"         # day 1: initial capital by the rules
    g = DP.datapack_gate("2026-10-28", "TEAM_042", provider=ManualFileProvider(tmp_path / "e3"), initial=True)
    assert g["status"] == "BLOCKED"                                           # --initial is no escape after day 1


# ---------------------------------------------------------------- 11, 12 scheduler preparation
def _log(tmp_path):
    lg = S.RunLog.__new__(S.RunLog)
    lg.path = tmp_path / "x.log"
    return lg


def test_precompetition_without_datapack_is_allowed(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "paper_start", lambda t, log: {"source": "RESET_INITIAL:x", "ledger": None})
    r = S.competition_preparation("PRECOMPETITION", "2026-10-15", "TEAM_TEST", _log(tmp_path))
    assert r["blocked_reason"] is None and r["datapack_status"] == "NOT_REQUIRED"
    assert r["settlement_source"] == "INITIAL_CAPITAL" and r["label"] == "PRECOMPETITION_PAPER_RUN"
    monkeypatch.setattr(S, "paper_start", lambda t, log: {"source": "CHAIN:2026-10-14", "ledger": "L"})
    r = S.competition_preparation("PRECOMPETITION", "2026-10-15", "TEAM_TEST", _log(tmp_path))
    assert r["settlement_source"] == "PRECOMPETITION_PAPER_LEDGER" and r["extra_args"] == ["--replay-run", "L"]


def test_competition_scheduler_blocks_without_datapack_never_paper(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(S, "paper_start", lambda *a, **k: called.append(1))
    r = S.competition_preparation("COMPETITION", "2026-10-28", "TEAM_042", _log(tmp_path),
                                  provider=ManualFileProvider(tmp_path / "none"))
    assert r["blocked_reason"] == "DATAPACK_MISSING" and r["settlement_source"] == "OFFICIAL_DATAPACK" and not called
    r = S.competition_preparation("COMPETITION", "2026-10-28", "TEAM_042", _log(tmp_path),
                                  provider=_dir_with(tmp_path / "s", "synthetic_stale_TEAM_042.json"))
    assert r["blocked_reason"] == "DATAPACK_STALE"
    r = S.competition_preparation("COMPETITION", "2026-10-28", "TEAM_042", _log(tmp_path),
                                  provider=_dir_with(tmp_path / "ok", VALID.name))
    assert r["blocked_reason"] is None and r["cd_mode"] == "competition" and r["extra_args"] == []


# ---------------------------------------------------------------- 14, 15 competition_day: no fallback + metadata
def test_competition_day_refuses_internal_settlement_without_datapack(fixture_store, ops_cfg, rb):
    from agent.ops.settle_internal import settle_day
    s1 = run(fixture_store, ops_cfg, T1, CLK1, initial=True)
    assert s1["status"] == "READY_TO_SUBMIT"
    assert s1["settlement_source"]["settlement_source"] == "INITIAL_CAPITAL"
    settle_day(T1, store=fixture_store, ops_cfg=ops_cfg, initial_cash=rb.rules.initial_cash)   # internal exists
    s2 = run(fixture_store, ops_cfg, T2, CLK2)
    assert s2["status"] == "BLOCKED" and s2["reason"].startswith("DATAPACK_MISSING")
    assert "start" not in s2                                           # internal ledger never used as a start
    assert run(fixture_store, ops_cfg, T2, CLK2, mode="dry-run")["status"] == "DRY_RUN_OK"   # precompetition ok


def test_competition_day_with_datapack_records_settlement_source(fixture_store, ops_cfg, rb):
    from agent.ops.settle_internal import settle_day
    run(fixture_store, ops_cfg, T1, CLK1, initial=True)
    st = settle_day(T1, store=fixture_store, ops_cfg=ops_cfg, initial_cash=rb.rules.initial_cash)
    save_official(official_from(st), ops_cfg)                         # organiser DataPack lands in the folder
    s2 = run(fixture_store, ops_cfg, T2, CLK2)
    assert s2["status"] == "READY_TO_SUBMIT", s2.get("reason")
    ss = s2["settlement_source"]
    assert ss["settlement_source"] == "OFFICIAL_DATAPACK" and ss["settlement_date"] == T1
    assert ss["datapack_validation"] == "PASS" and ss["datapack_freshness"] == "FRESH" and ss["datapack_file"]
    pkg = Path(s2["package"])
    assert json.loads((pkg / "run_metadata.json").read_text(encoding="utf-8"))["settlement_source"] == ss


# ---------------------------------------------------------------- providers / safety
def test_portal_provider_is_disabled_and_never_downloads():
    r = OfficialPortalProvider().fetch("TEAM_042", "2026-10-28")
    assert r["status"] == "DOWNLOAD_NOT_CONFIGURED"
    assert fetch_latest_datapack("TEAM_042", "2026-10-28", ManualFileProvider(ROOT / "nonexistent"))["portal"][
        "provider_status"] == "DISABLED_PENDING_OFFICIAL_PORTAL_VALIDATION"
    src = (ROOT / "agent/ops/datapack_downloader.py").read_text(encoding="utf-8")
    for bad in ("requests", "urllib", "http.client", "httpx", "cookie", "selenium", "playwright"):
        assert bad not in src.lower().replace("no cookies", "").replace("cookies / tokens", ""), bad


def test_real_config_and_official_folder_are_clean():
    from agent.ops.common import load_ops_config
    c = load_ops_config()
    # run_mode COMPETITION from Day 1 (Owner decision 2026-10-26, PR #8 Decision 1 = A, Issue #16)
    assert "datapack_calendar_override" not in c and S.run_mode(c) == "COMPETITION"
    od = ROOT / c["paths"]["official_datapack_dir"]
    assert not [p for p in od.glob("*.json") if "synthetic" in p.name or "example" in p.name or "SIMULATED" in p.name]
