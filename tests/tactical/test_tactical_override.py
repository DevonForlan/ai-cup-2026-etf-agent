"""Issue #43 tactical override: planner, entry/exit hook, ledger, fail-closed behaviour (synthetic prices, real rulebook)."""
import copy
import hashlib
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest
import yaml

from agent.config import D, load_strategy
from agent.engine.rules import load_rulebook
from agent.ops.common import load_ops_config
from agent.portfolio.constructor import FallbackToPreviousPortfolio
from agent.tactical import hook as H
from agent.tactical import ledger as LG
from agent.tactical import planner as PL
from agent.tactical.spec import load_spec

RB = load_rulebook()
CFG = load_strategy("config/strategy_quant_v1.yaml")
UNI = sorted(RB.universe)
TECH = UNI[:12]            # pretend these are tech
NONTECH = UNI[12:60]
BUYS = NONTECH[:6]
HOLD_NT = NONTECH[6:18]    # 12 held non-tech names -> 24 names total


def _world():
    closes = {t: D(50 + (i % 7) * 10) for i, t in enumerate(UNI)}
    hold = {t: 1_000_000 for t in TECH}
    hold.update({t: 400_000 for t in HOLD_NT})
    cash = D(120_000_000)
    nav = cash + sum(D(s) * closes[t] for t, s in hold.items())
    return closes, hold, cash, nav


def _spec_files(tmp_path, **over):
    sm = tmp_path / "sm.csv"
    sm.write_text("ticker,sector,source\n" + "".join(f"{t},{'半導體業' if t in TECH else '金融保險業'},x\n" for t in UNI),
                  encoding="utf-8")
    body = {"id": "TACT_TEST", "version": 1, "enabled": True, "entry_trade_date": "2026-11-09", "hold_trading_days": 1,
            "exit_trade_dates": {1: "2026-11-10", 2: "2026-11-11"}, "unwind_even_if_disabled": True,
            "target_rotation_nav_pct": 0.10, "tech_sector_labels": ["半導體業"], "sector_map": str(sm),
            "min_sell_nav_pct_per_name": 0.0015, "max_new_names": 6, "max_weight_per_new_name": 0.05,
            "buy_names": [{"ticker": t} for t in BUYS], "forbidden_tickers": ["2753", "1476", "6865"],
            "unwind_scales": [1.0, 0.75, 0.5, 0.25]}
    body.update(over)
    sp = tmp_path / "spec.yaml"
    sp.write_text(yaml.safe_dump({"tactical_override": body}, allow_unicode=True), encoding="utf-8")
    ops = copy.deepcopy(load_ops_config())
    ops["tactical"] = {"enabled": True, "spec": str(sp),
                       "spec_sha256": "sha256:" + hashlib.sha256(sp.read_bytes()).hexdigest()}
    ops["paths"]["tactical_dir"] = str(tmp_path / "tact")
    return ops, sp


def _quant(prev_h):
    return SimpleNamespace(is_fallback=False, marker="QUANT", selection={})


def _run(ctx, td, hold, cash, nav, closes, quant=None):
    ctx.trade_date = td
    ctx.outcome["trade_date"] = td
    scores = pd.DataFrame({"rank": [1.0]}, index=[UNI[0]])
    return H._apply(ctx, quant or _quant(hold), scores, hold, cash, nav, closes, RB, CFG, None, None, None)


def test_plan_entry_is_deterministic_lot_sized_and_balanced():
    closes, hold, cash, nav = _world()
    sm = {t: ("半導體業" if t in TECH else "金融保險業") for t in UNI}
    body = yaml.safe_load(open("config/tactical/tactical_override_20261109.yaml", encoding="utf-8"))["tactical_override"]
    body = dict(body, buy_names=[{"ticker": t} for t in BUYS], target_rotation_nav_pct=0.10)
    kw = dict(lot=1000, buy_fee=RB.rules.buy_fee_rate, sell_fee=RB.rules.sell_fee_rate, sell_tax=RB.rules.transaction_tax_rate)
    a = PL.plan_entry(body, sm, hold, closes, nav, set(UNI), **kw)
    b = PL.plan_entry(body, sm, hold, closes, nav, set(UNI), **kw)
    assert a.sells == b.sells and a.buys == b.buys
    assert all(q % 1000 == 0 and q > 0 for q in list(a.sells.values()) + list(a.buys.values()))
    assert set(a.sells) <= set(TECH) and set(a.buys) == set(BUYS)
    assert 0.09 < a.rotated_nav_pct < 0.11 and a.tech_pct_after < a.tech_pct_before
    assert a.bought_value <= a.sold_value


def test_forbidden_and_non_universe_buys_rejected():
    closes, hold, cash, nav = _world()
    sm = {t: "半導體業" for t in TECH}
    body = {"buy_names": [{"ticker": "2753"}], "tech_sector_labels": ["半導體業"], "target_rotation_nav_pct": 0.1,
            "min_sell_nav_pct_per_name": 0.001, "forbidden_tickers": ["2753"]}
    with pytest.raises(PL.PlanError):
        PL.plan_entry(body, sm, hold, closes, nav, set(UNI), lot=1000, buy_fee=D("0.001425"), sell_fee=D("0.001425"),
                      sell_tax=D("0.003"))


def test_entry_then_exit_restores_book_and_closes_ledger(tmp_path):
    closes, hold, cash, nav = _world()
    ops, _ = _spec_files(tmp_path)
    ctx = H.Context("2026-11-09", ops, ops["paths"]["tactical_dir"])
    res = _run(ctx, "2026-11-09", hold, cash, nav, closes)
    assert ctx.outcome["applied"] and not getattr(res, "marker", None), ctx.outcome
    assert 20 <= len(res.est_holdings) <= 30 and res.cash_weight_est < RB.rules.cash_max_weight
    assert max(res.est_weights.values()) <= RB.rules.other_max_weight
    sl = LG.load(ops["paths"]["tactical_dir"], "TACT_TEST")
    assert sl["state"] == "PLANNED" and sl["exit_trade_date"] == "2026-11-10"
    # official book after the entry trades (organiser settlement) -> exit day
    h2 = dict(res.est_holdings)
    c2 = res.est_cash
    ctx2 = H.Context("2026-11-10", ops, ops["paths"]["tactical_dir"])
    res2 = _run(ctx2, "2026-11-10", h2, c2, c2 + sum(D(s) * closes[t] for t, s in h2.items()), closes)
    assert ctx2.outcome["mode"] == "EXIT" and ctx2.outcome["applied"], ctx2.outcome
    assert res2.est_holdings == hold                      # fully restored lot for lot
    assert LG.load(ops["paths"]["tactical_dir"], "TACT_TEST")["state"] == "UNWIND_PLANNED"
    # day after: holdings restored -> ledger closes, frozen result used
    q = _quant(res2.est_holdings)
    ctx3 = H.Context("2026-11-11", ops, ops["paths"]["tactical_dir"])
    out = _run(ctx3, "2026-11-11", res2.est_holdings, res2.est_cash, nav, closes, q)
    assert out is q and LG.load(ops["paths"]["tactical_dir"], "TACT_TEST")["state"] == "CLOSED_UNWOUND"


def test_exit_when_entry_never_happened_is_not_entered(tmp_path):
    closes, hold, cash, nav = _world()
    ops, _ = _spec_files(tmp_path)
    ctx = H.Context("2026-11-09", ops, ops["paths"]["tactical_dir"])
    _run(ctx, "2026-11-09", hold, cash, nav, closes)
    q = _quant(hold)
    ctx2 = H.Context("2026-11-10", ops, ops["paths"]["tactical_dir"])
    assert _run(ctx2, "2026-11-10", hold, cash, nav, closes, q) is q       # submission failed -> book untouched
    assert LG.load(ops["paths"]["tactical_dir"], "TACT_TEST")["state"] == "CLOSED_NOT_ENTERED"


def test_overdue_flag_and_never_silently_extended(tmp_path):
    closes, hold, cash, nav = _world()
    ops, _ = _spec_files(tmp_path)
    ctx = H.Context("2026-11-09", ops, ops["paths"]["tactical_dir"])
    res = _run(ctx, "2026-11-09", hold, cash, nav, closes)
    h2, c2 = dict(res.est_holdings), res.est_cash
    n2 = c2 + sum(D(s) * closes[t] for t, s in h2.items())
    ctx2 = H.Context("2026-11-11", ops, ops["paths"]["tactical_dir"])      # exit window (11/10) was missed
    res2 = _run(ctx2, "2026-11-11", h2, c2, n2, closes)
    assert ctx2.outcome["flag"] == "TACTICAL_UNWIND_OVERDUE"
    assert LG.load(ops["paths"]["tactical_dir"], "TACT_TEST")["state"] == "OVERDUE"
    assert res2.est_holdings == hold                                      # still unwound with priority


def test_disabled_or_unpinned_spec_never_enters_but_still_unwinds(tmp_path):
    closes, hold, cash, nav = _world()
    ops, sp = _spec_files(tmp_path)
    ops["tactical"]["spec_sha256"] = "sha256:" + "0" * 64          # tamper -> pin mismatch
    ctx = H.Context("2026-11-09", ops, ops["paths"]["tactical_dir"])
    q = _quant(hold)
    assert _run(ctx, "2026-11-09", hold, cash, nav, closes, q) is q and "disabled" in ctx.outcome["blocked"]
    assert LG.load(ops["paths"]["tactical_dir"], "TACT_TEST") is None
    ops["tactical"]["enabled"] = False
    assert load_spec(ops).enabled is False


def test_entry_fails_closed_to_frozen_result_on_quant_fallback_and_errors(tmp_path):
    closes, hold, cash, nav = _world()
    ops, _ = _spec_files(tmp_path)
    ctx = H.Context("2026-11-09", ops, ops["paths"]["tactical_dir"])
    fb = FallbackToPreviousPortfolio("data")
    assert _run(ctx, "2026-11-09", hold, cash, nav, closes, fb) is fb
    ops2, _ = _spec_files(tmp_path, buy_names=[{"ticker": "2753"}] + [{"ticker": t} for t in BUYS[:5]])   # ineligible name
    ctx2 = H.Context("2026-11-09", ops2, ops2["paths"]["tactical_dir"])
    q = _quant(hold)
    out = _run(ctx2, "2026-11-09", hold, cash, nav, closes, q)
    assert out is q and ctx2.outcome["blocked"] and not ctx2.outcome["applied"]


def test_other_dates_are_untouched(tmp_path):
    closes, hold, cash, nav = _world()
    ops, _ = _spec_files(tmp_path)
    ctx = H.Context("2026-11-12", ops, ops["paths"]["tactical_dir"])
    q = _quant(hold)
    assert _run(ctx, "2026-11-12", hold, cash, nav, closes, q) is q and ctx.outcome["mode"] == "NONE"


def test_real_spec_pinned_and_frozen_quant_untouched():
    ops = load_ops_config()
    sp = load_spec(ops)
    assert sp.pin_ok and sp.enabled and sp.exit_date == "2026-11-10" and sp.hold_days == 1
    assert not ({"2753", "1476", "6865"} & {b["ticker"] for b in sp.body["buy_names"]})
    assert {b["ticker"] for b in sp.body["buy_names"]} <= set(RB.universe)
    frozen = hashlib.sha256(open("config/strategy_quant_v1.yaml", "rb").read()).hexdigest()
    assert frozen == "f34fa02e924011b20c52a4bd42e961169f97e1950e76e04b7e78dc43ac23d2e0"
