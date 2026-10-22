"""P-1 Team ID decoupling, P-2 market coverage gate, P-5 mode-aware Active Share source gate (approved 2026-10-16)."""
import copy
from pathlib import Path

import pytest

from agent.config import ROOT
from agent.ops import daily_evaluation as DE
from agent.ops import market_coverage as MC
from agent.ops import team as TEAM
from agent.ops.active_share_gate import result_gate, source_status
from agent.ops.common import load_ops_config, sha256_file
from tests.ops.test_competition_day import CLK1, CLK2, T1, T2, run

FROZEN_SHA = "sha256:f34fa02e924011b20c52a4bd42e961169f97e1950e76e04b7e78dc43ac23d2e0"


@pytest.fixture(autouse=True)
def _release_ops_loggers():
    """ops_logger caches one FileHandler per (name, date); drop them so later tests log into their own tmp dirs."""
    yield
    import logging
    for name, lg in list(logging.Logger.manager.loggerDict.items()):
        if name.startswith("ops.") and isinstance(lg, logging.Logger):
            for h in list(lg.handlers):
                h.close()
                lg.removeHandler(h)
            del logging.Logger.manager.loggerDict[name]       # next ops_logger() call builds a fresh logger


def partial_store(src_store, dst: Path, date: str, keep_market: str):
    """Copy of the store where `date` has price rows for ONE market only (the 2026-10-16 incident shape)."""
    import shutil
    from agent.data.loaders import HistoryStore
    dst.mkdir(parents=True, exist_ok=True)
    for p in src_store.root.glob("*.parquet"):
        shutil.copy2(p, dst / p.name)
    st = HistoryStore(dst)
    df = st.load("daily_prices")
    df[(df["date"] != date) | (df["market"] == keep_market)].to_parquet(st.path("daily_prices"), index=False)
    return HistoryStore(dst)


# ---------------------------------------------------------------- P-1
def test_team_id_comes_from_ops_config_not_frozen_strategy():
    ops = copy.deepcopy(load_ops_config())
    assert sha256_file(ROOT / "config" / "strategy_quant_v1.yaml").endswith(FROZEN_SHA.split(":")[1])
    pre = TEAM.resolve("PRECOMPETITION", ops)
    assert pre["status"] == "OK" and pre["team_id"] == "TEAM_TEST" and "ops.yaml" in pre["source"]
    comp = TEAM.resolve("COMPETITION", ops)                 # real config: not configured yet -> never guessed
    assert comp["status"] == "TEAM_ID_NOT_CONFIGURED" and comp["team_id"] is None


@pytest.mark.parametrize("value", [None, "", "TEAM_TEST", "team_test", "TEAM_SIM", "TEAM_XXX"])
def test_competition_rejects_placeholder_team_ids(value):
    ops = {"team": {"competition_team_id": value, "precompetition_team_id": "TEAM_TEST"}}
    assert TEAM.resolve("COMPETITION", ops)["status"] == "TEAM_ID_NOT_CONFIGURED"


def test_competition_accepts_a_configured_team_id():
    ops = {"team": {"competition_team_id": "TEAM_042"}}
    r = TEAM.resolve("COMPETITION", ops)
    assert r["status"] == "OK" and r["team_id"] == "TEAM_042"


def test_competition_cli_refuses_placeholder_team(capsys):
    from agent.competition_day import main
    assert main(["--date", "2026-10-27", "--team-id", "TEAM_TEST", "--mode", "competition", "--offline"]) == 2
    assert "TEAM_ID_NOT_CONFIGURED" in capsys.readouterr().out


def test_datapack_status_blocks_competition_without_team_id():
    from agent.ops.datapack_status import status
    s = status("COMPETITION", "2026-10-28")
    assert s["status"] == "BLOCKED" and s["reason"] == "TEAM_ID_NOT_CONFIGURED"
    assert status("PRECOMPETITION", "2026-10-19")["team_id"] == "TEAM_TEST"


def test_scheduler_no_longer_reads_team_from_strategy_file():
    src = (ROOT / "agent" / "ops" / "scheduled_run.py").read_text(encoding="utf-8")
    assert 'load_strategy("config/strategy_quant_v1.yaml")["team_id"]' not in src
    assert "TEAM_ID_NOT_CONFIGURED" in src


# ---------------------------------------------------------------- P-2
def test_20261016_partial_twse_day_blocked_by_coverage_gate(fixture_store, ops_cfg, tmp_path):
    """Reproduces 2026-10-16: day 2 of the paper chain, T has TPEx rows only (TWSE fetch failed). The coverage gate
    must stop it BEFORE settlement (MARKET_DATA_INCOMPLETE), not at NAV reconciliation."""
    paths = DE.Paths(ledger=tmp_path / "ledger", reports=tmp_path / "rep", logs=tmp_path / "logs")
    assert run(fixture_store, ops_cfg, T1, CLK1, mode="dry-run", initial=True)["status"] == "DRY_RUN_OK"
    assert DE.evaluate(T1, ops_cfg=ops_cfg, store=fixture_store, paths=paths)["status"] == "PASS"
    s2 = run(fixture_store, ops_cfg, T2, CLK2, mode="dry-run", replay_run=str(paths.ledger))
    assert s2["status"] == "DRY_RUN_OK", s2.get("reason")
    st = partial_store(fixture_store, tmp_path / "partial", T2, keep_market="TPEx")
    assert T2 in set(st.dates("daily_prices"))                 # the date "exists" ...
    r = DE.evaluate(T2, ops_cfg=ops_cfg, store=st, paths=paths)
    assert r["status"] == "BLOCKED" and r["blocked_reason"] == "MARKET_DATA_INCOMPLETE"   # ... but is incomplete
    assert "TWSE" in r["market_data"]
    assert not paths.settlement(T2).exists()                   # nothing written to the ledger


def test_20261016_without_gate_reached_nav_reconciliation(fixture_store, ops_cfg, tmp_path, monkeypatch):
    """Control: with the coverage gate disabled the same data reproduces the original NAV_RECONCILIATION_FAILED."""
    paths = DE.Paths(ledger=tmp_path / "ledger", reports=tmp_path / "rep", logs=tmp_path / "logs")
    run(fixture_store, ops_cfg, T1, CLK1, mode="dry-run", initial=True)
    DE.evaluate(T1, ops_cfg=ops_cfg, store=fixture_store, paths=paths)
    run(fixture_store, ops_cfg, T2, CLK2, mode="dry-run", replay_run=str(paths.ledger))
    st = partial_store(fixture_store, tmp_path / "partial", T2, keep_market="TPEx")
    monkeypatch.setattr(MC, "day_coverage", lambda *a, **k: {"status": "COMPLETE", "date": T2, "by_market": {},
                                                              "problems": []})
    r = DE.evaluate(T2, ops_cfg=ops_cfg, store=st, paths=paths)
    assert r["blocked_reason"] == "NAV_RECONCILIATION_FAILED"


def test_coverage_statuses(fixture_store, tmp_path):
    ok = MC.day_coverage(fixture_store, T1)
    assert ok["status"] == "COMPLETE" and ok["by_market"]["TWSE"]["share"] == 1.0
    st = partial_store(fixture_store, tmp_path / "p", T1, keep_market="TPEx")
    bad = MC.day_coverage(st, T1, holdings=["2330"])
    assert bad["status"] == "INCOMPLETE" and "2330" in bad["missing_holdings"]
    assert MC.day_coverage(st, "1999-01-04")["status"] == "MISSING"
    assert MC.incomplete_days(st, [T1, T2]) == [T1]


def test_competition_run_blocks_on_incomplete_previous_day(fixture_store, ops_cfg, tmp_path):
    st = partial_store(fixture_store, tmp_path / "p", T1, keep_market="TPEx")
    s = run(st, ops_cfg, T2, CLK2, mode="dry-run", initial=True)
    assert s["status"] == "BLOCKED" and "MARKET_DATA_INCOMPLETE" in s["reason"]


# ---------------------------------------------------------------- P-5
def test_active_share_source_is_mode_aware(fixture_store, ops_cfg, tmp_path):
    from tests.ops.conftest import store_without_date
    st = store_without_date(fixture_store, tmp_path / "noetf", "1990-01-01", tables=("etf_holdings",))
    comp = source_status(st, T1, ops_cfg, competition=True, fixture=True)
    pre = source_status(st, T1, ops_cfg, competition=False, fixture=True)
    assert comp["level"] == "BLOCK" and comp["code"] == "ACTIVE_SHARE_DATA_MISSING"
    assert pre["level"] == "WARN" and pre["code"] == "ACTIVE_SHARE_DATA_MISSING"
    assert source_status(fixture_store, T1, ops_cfg, competition=True, fixture=True)["level"] == "PASS"


def test_active_share_missing_listed_etf_blocks_only_in_competition(fixture_store, ops_cfg):
    listed = ["00400A", "00401A", "09999A"]                      # 09999A has no published holdings
    import agent.ops.active_share_gate as G
    real = copy.deepcopy(ops_cfg)
    comp = G.source_status(_RealView(fixture_store), T1, real, competition=True, active_etfs=listed)
    pre = G.source_status(_RealView(fixture_store), T1, real, competition=False, active_etfs=listed)
    assert comp["code"] in ("ACTIVE_SHARE_DATA_MISSING", "ACTIVE_SHARE_DATA_STALE") and comp["level"] == "BLOCK"
    assert pre["level"] in ("WARN", "BLOCK")       # STALE (> etf_stale_days_block) stays BLOCK in every mode


def test_unknown_active_share_result_gate():
    assert result_gate(0.42, True) is None
    assert result_gate(None, True)["level"] == "BLOCK"
    assert result_gate(None, True)["code"] == "ACTIVE_SHARE_DATA_MISSING"
    assert result_gate(None, False)["level"] == "WARN"


def test_competition_run_without_benchmark_is_blocked_dry_run_continues(fixture_store, ops_cfg):
    comp = run(fixture_store, ops_cfg, T1, CLK1, mode="competition", initial=True, data_faults={"etf"})
    assert comp["status"] == "BLOCKED" and comp["reason"].startswith("ACTIVE_SHARE_DATA_MISSING")
    assert not comp.get("final_file")


def test_precompetition_run_without_benchmark_warns(fixture_store, ops_cfg):
    dry = run(fixture_store, ops_cfg, T1, CLK1, mode="dry-run", initial=True, data_faults={"etf"})
    assert dry["status"] == "DRY_RUN_OK"
    assert any("ACTIVE_SHARE_UNKNOWN" in n for n in dry["notes"])


def test_active_share_thresholds_unchanged():
    from agent.config import load_strategy
    from agent.engine.rules import load_rulebook
    assert float(load_rulebook().rules.active_share_min) == 0.15
    assert float(load_strategy("config/strategy_quant_v1.yaml")["strategy_buffers"]["active_share_target"]) == 0.3


class _RealView:
    """Fixture store viewed as if its benchmark rows were real (non-synthetic) -> exercises the real-store path."""
    def __init__(self, s):
        self._s = s

    def load(self, t):
        df = self._s.load(t)
        if t == "etf_holdings" and "synthetic" in df:
            df = df.assign(synthetic=False)
        return df
