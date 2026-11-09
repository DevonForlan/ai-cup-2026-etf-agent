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


def test_v2_direct_resume_claims_dates_and_never_patches(tmp_path, monkeypatch):
    import yaml
    import agent.pipeline as P
    from agent.tactical import override as TO
    cfg = yaml.safe_load(open(TO.CONFIG_PATH_V2, encoding="utf-8"))
    assert cfg["exit_mode"] == TO.EXIT_RESUME
    t = TO.load_config(TO.CONFIG_PATH_V2)
    assert TO.phase_for(t, "2026-11-09") == "ENTRY"
    assert TO.phase_for(t, "2026-11-10") == "RESUME" and TO.phase_for(t, "2026-11-20") == "RESUME"
    # the V2 config claims every later date, so the superseded V1 config (UNWIND from 11/10) can never apply
    for d in ("2026-11-10", "2026-11-11", "2026-11-25"):
        assert TO.resolve_config(None, d)["version"] == TO.VERSION_V2
        assert TO.is_active(d, "competition", prev_holdings={"2002": 1000}) is False
    orig = P.construct
    # Issue #61 made 2026-11-10 a one-time forced rebalance (patched, see the dedicated tests below); the plain RESUME path is covered here
    # with the same config minus that one key, so the original assertion (Frozen Quant constructs alone, no patch) is kept.
    cfg.pop("resume_full_rebalance_date")
    plain = tmp_path / "v2_plain_resume.yaml"
    plain.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    with TO.activate("2026-11-10", "competition", config_path=plain, state_dir=tmp_path) as act:
        assert P.construct is orig                       # Frozen Quant v1 constructs alone
    p = tmp_path / "2026-11-10_RESUME_V2.json"
    assert p.exists() and "FROZEN_QUANT_RESUMED" in p.read_text(encoding="utf-8")
    with TO.activate("2026-11-11", "competition", state_dir=tmp_path):
        assert P.construct is orig
    assert not (tmp_path / "2026-11-11_RESUME_V2.json").exists()
    with TO.activate("2026-11-10", "dry-run", state_dir=tmp_path):
        assert P.construct is orig


# ----------------------------------------------------------------------------- Issue #61: one-time full Frozen Quant v1 rebalance
def test_forced_rebalance_date_and_activation_calls_unchanged_constructor_with_true(tmp_path, monkeypatch):
    import json
    import agent.pipeline as P
    from agent.portfolio import constructor as K
    from agent.tactical import override as TO
    t = TO.load_config(TO.CONFIG_PATH_V2)
    assert t["resume_full_rebalance_date"] == "2026-11-10" and t["exit_mode"] == TO.EXIT_RESUME
    assert TO.is_forced_rebalance(t, "2026-11-10") is True
    assert TO.is_forced_rebalance(t, "2026-11-11") is False and TO.is_forced_rebalance(t, "2026-11-09") is False
    seen = {}

    def fake_construct(scores, prev_holdings, prev_cash, nav_prev, closes_prev, rb, cfg, market, etf_holdings=None, etf_meta=None,
                       method=None, holding_days=None, is_rebalance_day=True, regime_override=None, guard=None):
        seen["flag"] = is_rebalance_day
        return K.FallbackToPreviousPortfolio("fake hold")

    monkeypatch.setattr(P, "construct", fake_construct)
    with TO.activate("2026-11-10", "competition", state_dir=tmp_path) as act:
        assert P.construct is not fake_construct
        res = P.construct({}, {"2330": 1000}, 0, 1, {"2330": 1}, None, {}, {}, is_rebalance_day=False)
    assert seen["flag"] is True and isinstance(res, K.FallbackToPreviousPortfolio)   # only the cadence flag changed; result returned as is
    assert P.construct is fake_construct                                             # always restored
    rec = json.loads((tmp_path / "2026-11-10_RESUME_REBALANCE_V2.json").read_text(encoding="utf-8"))
    assert rec["status"] == "FULL_REBALANCE_FALLBACK" and rec["decision_authority"] == "FROZEN_QUANT_V1" and rec["rebalance_day_flag_from_pipeline"] is False
    # other dates / modes are not touched
    with TO.activate("2026-11-11", "competition", state_dir=tmp_path):
        assert P.construct is fake_construct
    with TO.activate("2026-11-10", "dry-run", state_dir=tmp_path):
        assert P.construct is fake_construct


def test_stage_to_decision_cap_defers_smallest_sells_first(monkeypatch):
    from decimal import Decimal as Dm
    from agent.portfolio import constructor as K
    from agent.tactical import override as TO
    calls = []

    def fake_finalize(tw, nt, prev_h, prev_cash, nav, closes, rb, cfg, eh, em, regime, stance, why, cash_rng, info, notes):
        calls.append(sorted(set(nt)))
        if len(calls) < 2:
            return K.FallbackToPreviousPortfolio("too many orders")
        o = type("O", (), {"ticker": "D", "side": "BUY", "shares": 1000})()
        return K.TargetPortfolio(tw, Dm(0), [], [o], regime, stance, why, cash_rng, info, {}, Dm(0), Dm(1), {}, None)

    monkeypatch.setattr(K, "_finalize", fake_finalize)
    monkeypatch.setattr(TO.B, "regime_from_market", lambda m, c: ("risk_on", "neutral", (0.02, 0.2), "t"))
    closes = {"A": Dm(10), "B": Dm(10), "C": Dm(10), "D": Dm(10)}
    prev_h = {"A": 10000, "B": 5000, "C": 2000}
    tw = {"A": Dm(0), "B": Dm(0), "C": Dm("0.02"), "D": Dm("0.5")}
    plan = (tw, prev_h, set(), Dm(1_000_000), closes, 1000)
    out = TO._stage_to_decision_cap(plan, Dm(0), None, {}, {}, None, None, {}, None)
    assert out is not None
    res, deferred, needed = out
    assert deferred == ["B", "A"][:2] or deferred == ["B", "A"]          # smallest-value sells first: B (50k) then A (100k)
    assert calls[0] == ["B"] and calls[1] == ["A", "B"] and needed >= 3


def test_rebalance_gate_fail_closed():
    from agent.ops import tactical_supersede as S
    cfg = {"frozen_quant_sha256": "f34fa02e924011b20c52a4bd42e961169f97e1950e76e04b7e78dc43ac23d2e0", "_fingerprint": "fp"}
    good_t = {"phase": "RESUME_REBALANCE", "status": "FROZEN_QUANT_FULL_REBALANCE", "decision_authority": "FROZEN_QUANT_V1",
              "frozen_quant_sha256": cfg["frozen_quant_sha256"], "fingerprint": "fp", "orders": 30, "holdings_after": 27,
              "active_share_min": 0.35, "cash_weight_after": 0.15}
    good = {"run_id": "r", "status": "READY_TO_SUBMIT", "validation": "PASS", "fallback": False, "tactical_override": good_t}
    assert S.candidate_gate(good, cfg, "r") == (True, [])
    for k, v in (("status", "FULL_REBALANCE_FALLBACK"), ("orders", 31), ("orders", 0), ("holdings_after", 19),
                 ("active_share_min", 0.10), ("cash_weight_after", 0.26), ("fingerprint", "x"), ("decision_authority", "TACTICAL")):
        ok, why = S.candidate_gate(dict(good, tactical_override=dict(good_t, **{k: v})), cfg, "r")
        assert not ok and why, (k, v)
    assert not S.candidate_gate(dict(good, validation="FAIL"), cfg, "r")[0]
    assert not S.candidate_gate(dict(good, fallback=True), cfg, "r")[0]
    assert not S.candidate_gate(good, cfg, "other-run")[0]
