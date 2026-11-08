"""Issue #49: TACTICAL_OVERRIDE_V2_TECH_LT10 - hard tech < 10 % NAV, <= 30 orders, expiry-first unwind, supersession gate."""
import csv
import hashlib
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from agent.portfolio.constructor import TargetPortfolio
from agent.tactical import override as O
from tests.tactical.test_override import world, run  # noqa: F401  (fixtures / helper shared with the V1 tests)

ROOT = Path(__file__).resolve().parents[2]
T = "2026-10-27"


def make_v2(tmp_path, w, *, ladder=None, tech_max=0.10, design=0.5, guard=0.5, entry=T, exit_="2026-10-28", n_names=6):
    sleeve = w["sleeve"][:n_names]
    doc = {"version": O.VERSION_V2, "enabled": True, "entry_trade_date": entry, "exit_trade_date": exit_, "hold_trading_days": 1,
           "target_tech_weight_max": tech_max, "tech_design_max": design, "tech_guard_max": guard, "max_orders": 30,
           "target_holdings_min": 20, "buy_weight_cap": 0.098,
           "ladder": ladder or [{"cash_target": 0.12, "untouched_max": 0.0, "n_buys": n_names}],
           "sleeve": {t: 1 / len(sleeve) for t in sleeve}, "legacy_sleeve_names": [],
           "reduce_tickers": list(w["tech"]),
           "baseline_holdings": {t: int(s) for t, s in w["held"].items()}}
    p = tmp_path / "v2.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return p


def test_alloc_respects_cap_and_total():
    r = O._alloc(Decimal("0.7"), {"a": Decimal(1), "b": Decimal(1), "c": Decimal(5)}, Decimal("0.4"))
    assert r["c"] == Decimal("0.4") and abs(sum(r.values()) - Decimal("0.7")) < Decimal("1e-9")
    assert O._alloc(Decimal("0.9"), {"a": Decimal(1), "b": Decimal(1)}, Decimal("0.4")) is None


def test_v2_entry_goes_below_target_or_fails_closed(world, rb, cfg, tmp_path):
    res, act = run(world, rb, cfg, T, make_v2(tmp_path, world), tmp_path)
    rec = act.record
    assert rec["version"] == O.VERSION_V2 or rec["status"] == "BLOCKED"
    if rec["status"] == "APPLIED":
        assert rec["tech_weight_after"] < 0.10 and isinstance(res, TargetPortfolio)
        assert len(res.orders) <= 30 and 20 <= len(res.est_holdings) <= 30
        assert res.active_share.minimum_active_share >= O.AS_FLOOR
        assert rec["unwind_plan"]["buy_back"] == rec["sells"] and rec["unwind_plan"]["sell_all"] == rec["buys"]
        assert (tmp_path / "state" / f"{T}_ENTRY_V2.json").is_file()
    else:
        assert rec["status"] == "BLOCKED"                      # never an invalid plan: the untouched Quant result is returned
        assert not any(o.ticker in world["sleeve"][:6] for o in getattr(res, "orders", []))


def test_v2_guard_rejects_tech_at_or_above_target(world, rb, cfg, tmp_path):
    res, act = run(world, rb, cfg, T, make_v2(tmp_path, world, tech_max=0.0001, guard=0.0001), tmp_path)
    assert act.record["status"] == "BLOCKED" and "no ladder step" in act.record["reason"]


def test_v2_blocks_when_a_buy_name_is_technology(world, rb, cfg, tmp_path):
    p = make_v2(tmp_path, world)
    d = yaml.safe_load(p.read_text(encoding="utf-8"))
    d["sleeve"] = {world["tech"][0]: 1.0}
    p.write_text(yaml.safe_dump(d), encoding="utf-8")
    res, act = run(world, rb, cfg, T, p, tmp_path)
    assert act.record["status"] == "BLOCKED" and "tech" in act.record["reason"]


def test_v2_unwind_restores_baseline(world, rb, cfg, tmp_path):
    cpath = make_v2(tmp_path, world)
    res, act = run(world, rb, cfg, T, cpath, tmp_path)
    if act.record["status"] != "APPLIED":
        pytest.skip("fixture book cannot reach the V2 target; covered by the fail-closed tests")
    after, cash2 = dict(res.est_holdings), res.est_cash
    nav2 = sum(Decimal(s) * world["closes"][t] for t, s in after.items()) + cash2
    res2, act2 = run(world, rb, cfg, "2026-10-28", cpath, tmp_path, holdings=after, cash=cash2, nav=nav2)
    assert act2.record["phase"] == "UNWIND" and act2.record["version"] == O.VERSION_V2
    assert act2.record["status"] == "APPLIED"
    for t in world["tech"]:
        assert res2.est_holdings.get(t, 0) == world["held"][t]


def test_legacy_sleeve_counts_as_open(world, tmp_path):
    cpath = make_v2(tmp_path, world)
    d = yaml.safe_load(cpath.read_text(encoding="utf-8"))
    leg = world["sleeve"][-1]
    d["sleeve"] = {world["sleeve"][0]: 1.0}
    d["legacy_sleeve_names"] = [leg]
    cpath.write_text(yaml.safe_dump(d), encoding="utf-8")
    c = O.load_config(cpath)
    held = dict(world["held"])
    assert not O.sleeve_open(held, c)
    held[leg] = 7000
    assert O.sleeve_open(held, c)


def test_resolve_config_prefers_v2_for_its_dates_and_v1_otherwise(world, tmp_path, monkeypatch):
    v2 = make_v2(tmp_path, world, entry="2026-11-09", exit_="2026-11-10")
    monkeypatch.setattr(O, "CONFIG_PATH_V2", v2)
    assert O.resolve_config(None, "2026-11-09")["version"] == O.VERSION_V2
    assert O.resolve_config(None, "2026-11-12")["version"] == O.VERSION_V2          # unwind is expiry-first
    monkeypatch.setattr(O, "CONFIG_PATH_V2", tmp_path / "missing.yaml")
    assert O.resolve_config(None, "2026-11-09")["version"] == O.VERSION                # V2 absent: V1 applies again (rollback)
    assert O.resolve_config(None, "2026-10-01") is None


def test_shipped_v2_config_is_consistent():
    c = O.load_config(ROOT / "config" / "tactical_override_v2.yaml")
    assert c and c["version"] == O.VERSION_V2 and c["entry_trade_date"] == "2026-11-09" and c["exit_trade_date"] == "2026-11-10"
    assert c["frozen_quant_sha256"] == hashlib.sha256((ROOT / "config" / "strategy_quant_v1.yaml").read_bytes()).hexdigest()
    assert float(c["target_tech_weight_max"]) == 0.10 and float(c["tech_guard_max"]) < 0.10
    uni = {r["ticker"] for r in csv.DictReader(open(ROOT / "config" / "universe_150.csv", encoding="utf-8-sig"))}
    tech = set(c["reduce_tickers"])
    assert set(c["sleeve"]) <= uni and not (set(c["sleeve"]) & tech) and len(c["sleeve"]) == 10
    assert abs(sum(c["sleeve"].values()) - 1) < 1e-5
    assert not ({"2753", "1476", "6865", "2412"} & set(c["sleeve"]))
    v1 = O.load_config(ROOT / "config" / "tactical_override_v1.yaml")
    assert set(v1["sleeve"]) <= set(c["sleeve"]) | set(c["legacy_sleeve_names"])
    assert c["baseline_holdings"] == v1["baseline_holdings"] and len(c["baseline_holdings"]) == 24


def test_candidate_gate():
    from agent.ops import tactical_supersede as S
    tc = {"_fingerprint": "f", "target_tech_weight_max": 0.10}
    ok = {"run_id": "r1", "status": "READY_TO_SUBMIT", "validation": "PASS",
          "tactical_override": {"version": O.VERSION_V2, "phase": "ENTRY", "status": "APPLIED", "fingerprint": "f",
                                "tech_weight_after": 0.085, "holdings_after": 22, "active_share_min": 0.5}}
    assert S.candidate_gate(ok, tc, "r1") == (True, [])
    for k, v in (("tech_weight_after", 0.10), ("status", "BLOCKED"), ("fingerprint", "x"), ("holdings_after", 19),
                 ("active_share_min", 0.1), ("version", O.VERSION)):
        bad = {**ok, "tactical_override": {**ok["tactical_override"], k: v}}
        assert S.candidate_gate(bad, tc, "r1")[0] is False, k
    assert S.candidate_gate(ok, tc, "other")[0] is False
    assert S.candidate_gate(None, tc, "r1")[0] is False


def test_data_not_degraded_waiver():
    from agent.ops import tactical_supersede as S
    h = {"sources": [{"source": "twse_prices", "criticality": "CRITICAL", "status": "OK", "stale": False},
                     {"source": "etf_holdings", "criticality": "IMPORTANT", "status": "STALE", "stale": True},
                     {"source": "mops_material_info", "criticality": "OPTIONAL", "status": "FAILED", "stale": False}]}
    prior = {"preflight": {"warns": ["data:etf_holdings"]}}
    assert S.data_not_degraded(h, prior)[0] is True
    assert S.data_not_degraded(h, {"preflight": {"warns": []}})[0] is False          # a NEW important gap is not waived
    h["sources"][0].update(status="FAILED")
    assert S.data_not_degraded(h, prior)[0] is False                                  # critical source never waived
    assert S.data_not_degraded(None, prior)[0] is False


def test_submitted_at_is_that_of_the_superseding_submission(tmp_path):
    import json
    from agent.ops import shared_state_sync as S
    day = tmp_path / "submissions" / "20261109"
    (day / "FINAL").mkdir(parents=True)
    f = day / "FINAL" / "D-Plan_TEAM_11442_2026-11-09.json"
    f.write_bytes(b"{}")
    sha = "sha256:" + S._sha(b"{}")
    hist = [{"at": "A", "to": "READY_TO_SUBMIT"}, {"at": "B", "to": "SUBMITTED_UNVERIFIED"}, {"at": "C", "to": "SUBMISSION_CONFIRMED"},
            {"at": "D", "to": "UNKNOWN"}, {"at": "E", "to": "READY_TO_SUBMIT"}, {"at": "F", "to": "SUBMITTED_UNVERIFIED"},
            {"at": "G", "to": "SUBMISSION_CONFIRMED"}]
    (day / "submission_state.json").write_text(json.dumps({"state": "SUBMISSION_CONFIRMED", "trade_date": "2026-11-09",
                                                           "team_id": "TEAM_11442", "dplan_sha256": sha, "history": hist}))
    r = S.confirmed_record("2026-11-09", tmp_path, team="TEAM_11442")
    assert r["submitted_at"] == "F" and r["confirmed_at"] == "G"
