"""competition_day end-to-end on the synthetic fixture store: day 1 -> internal settlement -> official
settlement -> reconciliation -> day 2; plus reconciliation BLOCK, cash-drift recovery, LLM failures,
deadline guard and optional-data failure. Nothing is ever uploaded."""
import json
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from agent.competition_day import operator_summary, run_competition_day
from agent.llm.providers.mock import MockProvider
from agent.ops.common import Clock
from agent.ops.settle_internal import settle_day
from agent.ops.settlement import load_internal, save_internal, save_official
from tests.ops.conftest import CLEAN_GIT
from tests.ops.test_ops_units import _fake

T1, T2 = "2026-10-26", "2026-10-27"
CLK1, CLK2 = "2026-10-25T20:00:00+08:00", "2026-10-26T20:00:00+08:00"
OK = ("READY_TO_SUBMIT", "DRY_RUN_OK")


def run(store, ops_cfg, date, clock, mode="competition", **kw):
    kw.setdefault("skip_refresh", True)
    return run_competition_day(date, "TEAM_TEST", mode, store=store, store_is_fixture=True, ops_cfg=ops_cfg,
                               clock=Clock(clock), git=CLEAN_GIT, archive_readonly=False, **kw)


def day1_settled(store, ops_cfg, rb):
    s = run(store, ops_cfg, T1, CLK1, initial=True)
    assert s["status"] == "READY_TO_SUBMIT", s.get("reason")
    st = settle_day(T1, store=store, ops_cfg=ops_cfg, initial_cash=rb.rules.initial_cash)
    assert st.agent_state, "agent_state must come from the FINAL package"
    return s, st


def official_from(st, **over):
    d = {"date": st.date, "holdings": st.holdings, "cash": str(st.cash), "nav": str(st.nav),
         "accrued_dividends": str(st.accrued_dividends), "warnings": [w["rule"] for w in st.warnings],
         "source": "test manual copy"}
    d.update(over)
    return d


def test_e2e_two_days_with_official_settlement(fixture_store, ops_cfg, rb):
    s1, st = day1_settled(fixture_store, ops_cfg, rb)
    assert s1["final_file"].endswith(f"D-Plan_TEAM_TEST_{T1}.json") and s1["sha256"].startswith("sha256:")
    assert Path(s1["archive"], "ARCHIVE_MANIFEST.json").exists()
    save_official(official_from(st), ops_cfg)
    s2 = run(fixture_store, ops_cfg, T2, CLK2)
    assert s2["status"] == "READY_TO_SUBMIT", s2.get("reason")
    assert s2["reconciliation"]["status"] == "MATCH" and s2["validation"] == "PASS"
    assert s2["degradation_level"] in (1, 2)
    meta = json.loads(Path(s2["package"], "run_metadata.json").read_text(encoding="utf-8"))
    for k in ("trade_date", "generated_at", "git_sha", "git_dirty", "python_version", "config_hashes",
              "prompt_versions", "data_snapshot_hash", "settlement_hash", "dplan_sha256", "provider", "model",
              "llm_replay_id", "run_durations"):
        assert k in meta
    txt = operator_summary(s2)
    assert "READY_TO_SUBMIT" in txt and s2["sha256"] in txt
    summ = Path(ops_cfg["paths"]["ops_logs_dir"]) / "20261027" / "competition_day_summary.json"
    assert json.loads(summ.read_text(encoding="utf-8"))["status"] == "READY_TO_SUBMIT"


def test_reconciliation_share_mismatch_blocks_run(fixture_store, ops_cfg, rb):
    _, st = day1_settled(fixture_store, ops_cfg, rb)
    h = dict(st.holdings)
    t = sorted(h)[0]
    h[t] += 1000
    save_official(official_from(st, holdings=h), ops_cfg)
    s2 = run(fixture_store, ops_cfg, T2, CLK2)
    assert s2["status"] == "BLOCKED" and "settlement_reconciled" in s2["reason"]
    assert s2["reconciliation"]["status"] == "BLOCK"
    assert not (Path(ops_cfg["paths"]["submissions_dir"]) / "20261027").exists()     # no package, no FINAL


def test_missing_official_settlement_blocks_competition_not_dry_run(fixture_store, ops_cfg, rb):
    day1_settled(fixture_store, ops_cfg, rb)
    assert run(fixture_store, ops_cfg, T2, CLK2)["status"] == "BLOCKED"
    assert run(fixture_store, ops_cfg, T2, CLK2, mode="dry-run")["status"] == "DRY_RUN_OK"


def test_cash_drift_previous_portfolio_is_rebalanced_not_kept(fixture_store, ops_cfg, rb):
    """Round 04 regression rule: a passively drifted portfolio (cash > 25%) must not be carried forward."""
    _, st = day1_settled(fixture_store, ops_cfg, rb)
    extra = st.nav * Decimal("0.6")
    st.cash += extra
    st.nav += extra
    save_internal(st, ops_cfg)
    save_official(official_from(st), ops_cfg)
    s2 = run(fixture_store, ops_cfg, T2, CLK2)
    assert s2["status"] == "READY_TO_SUBMIT", s2.get("reason")
    assert "previous_portfolio_legal" in s2["preflight"]["warns"]
    assert s2["orders"] > 0 and s2["portfolio"]["cash_ratio_est"] < 0.25


@pytest.fixture
def mock_llm_cfg(tmp_path):
    p = tmp_path / "llm_mock.yaml"
    base = yaml.safe_load(Path("config/llm_narrative_v1.yaml").read_text(encoding="utf-8"))
    base.update(provider="mock", model="mock-rules-v1", retries=1, log_calls=False)
    p.write_text(yaml.safe_dump(base, allow_unicode=True), encoding="utf-8")
    return str(p)


@pytest.mark.parametrize("mode", ["timeout", "rate_limit", "bad_json"])
def test_llm_failure_falls_back_to_template_and_dplan_passes(fixture_store, ops_cfg, mock_llm_cfg, mode):
    s = run(fixture_store, ops_cfg, T1, CLK1, mode="dry-run", initial=True, llm_config=mock_llm_cfg,
            llm_provider=MockProvider("mock-rules-v1", mode))
    assert s["status"] == "DRY_RUN_OK" and s["validation"] == "PASS"
    assert s["llm"]["used"] is False and s["llm"]["failed"] >= 1
    assert s["degradation_level"] == 1


def test_llm_ok_is_level0_and_orders_equal_template(fixture_store, ops_cfg, mock_llm_cfg, tmp_path):
    s_llm = run(fixture_store, ops_cfg, T1, CLK1, mode="dry-run", initial=True, llm_config=mock_llm_cfg,
                llm_provider=MockProvider("mock-rules-v1", "normal"))
    assert s_llm["degradation_level"] == 0 and s_llm["llm"]["used"]
    import copy
    cfg2 = copy.deepcopy(ops_cfg)
    for k in cfg2["paths"]:
        cfg2["paths"][k] = cfg2["paths"][k].replace(str(Path(ops_cfg["paths"]["submissions_dir"]).parent),
                                                    str(tmp_path / "t"))
    s_tpl = run(fixture_store, cfg2, T1, CLK1, mode="dry-run", initial=True)
    o1 = json.loads(Path(s_llm["final_file"]).read_text(encoding="utf-8"))
    o2 = json.loads(Path(s_tpl["final_file"]).read_text(encoding="utf-8"))
    assert o1["orders"] == o2["orders"] and o1["decisions"] == o2["decisions"]


def test_deadline_package_only_skips_llm_and_refresh(fixture_store, ops_cfg, mock_llm_cfg):
    s = run(fixture_store, ops_cfg, T1, "2026-10-26T08:47:00+08:00", mode="dry-run", initial=True,
            llm_config=mock_llm_cfg, llm_provider=MockProvider("mock-rules-v1", "normal"), skip_refresh=False,
            refresh_fetchers=_fake())
    assert s["deadline"]["phase"] == "PACKAGE_ONLY" and s["status"] == "DRY_RUN_OK"
    assert s["llm"] == {"used": False, "mode": "template"}
    assert any("refresh skipped" in n for n in s["notes"]) and any("LLM disabled" in n for n in s["notes"])


def test_past_cutoff_never_promoted_to_final(fixture_store, ops_cfg):
    s = run(fixture_store, ops_cfg, T1, "2026-10-26T09:05:00+08:00", initial=True)
    assert s["status"] == "LATE_PAST_CUTOFF" and "final_file" not in s
    assert not (Path(ops_cfg["paths"]["submissions_dir"]) / "20261026" / "FINAL_CANDIDATE.txt").exists()


def test_optional_source_failure_never_blocks_quant_dplan(fixture_store, ops_cfg):
    s = run(fixture_store, ops_cfg, T1, CLK1, mode="dry-run", initial=True, skip_refresh=False,
            refresh_fetchers=_fake(latest="2026-10-23", fail={"us_market", "taifex_night", "mops_material_info",
                                                               "mops_revenue_first_seen"}))
    assert s["status"] == "DRY_RUN_OK" and s["validation"] == "PASS"


def test_critical_source_failure_blocks(fixture_store, ops_cfg):
    s = run(fixture_store, ops_cfg, T1, CLK1, initial=True, skip_refresh=False,
            refresh_fetchers=_fake(latest="2026-10-23", fail={"twse_prices"}))
    assert s["status"] == "BLOCKED" and "twse_prices" in s["reason"]
