"""Issue #43: TACTICAL_OVERRIDE_V1 — entry rotation, expiry-first unwind, fail-closed behaviour, toggle, frozen paths untouched."""
import hashlib
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from agent.config import D
from agent.data.pit import PITView
from agent.features.feature_engine import build_features
from agent.pipeline import etf_holdings_from_view
import agent.pipeline as P
from agent.portfolio.constructor import FallbackToPreviousPortfolio, TargetPortfolio, construct
from agent.portfolio.ranking import score
from agent.tactical import override as O

T = "2026-10-27"
ROOT = Path(__file__).resolve().parents[2]


def setup(fixture_store, rb, cfg):
    v = PITView(fixture_store, f"{T}T07:00:00+08:00")
    fs = build_features(v, sorted(rb.universe), T)
    sc = score(fs.features, cfg["score_weights"])
    closes = {t: D(round(float(x), 4)) for t, x in fs.features["close_prev"].dropna().items()}
    etf, meta = etf_holdings_from_view(v)
    return fs, sc, closes, etf, meta


@pytest.fixture
def world(fixture_store, rb, cfg):
    fs, sc, closes, etf, meta = setup(fixture_store, rb, cfg)
    tp = construct(sc, {}, rb.rules.initial_cash, rb.rules.initial_cash, closes, rb, cfg, fs.market, etf, meta)
    assert isinstance(tp, TargetPortfolio)
    held, cash = dict(tp.est_holdings), tp.est_cash
    nav = sum(Decimal(s) * closes[t] for t, s in held.items()) + cash
    order = sorted(held, key=lambda t: -held[t] * closes[t])
    tech = order[: max(len(order) * 2 // 3, 4)]                         # pretend these are the technology cluster
    others = [t for t in sc.sort_values("rank").index if t not in held and sc.at[t, "eligible"]][:6]
    return dict(fs=fs, sc=sc, closes=closes, etf=etf, meta=meta, held=held, cash=cash, nav=nav, tech=tech, sleeve=others)


def make_cfg(tmp_path, w, *, entry=T, exit_="2026-10-28", enabled=True, ladder=(0.20, 0.10, 0.05), sleeve=None, baseline=None):
    sleeve = sleeve or w["sleeve"][:4]
    doc = {"version": "TACTICAL_OVERRIDE_V1", "enabled": enabled, "entry_trade_date": entry, "exit_trade_date": exit_,
           "hold_trading_days": 1, "rotation_nav_pct_ladder": list(ladder),
           "sleeve": {t: 1 / len(sleeve) for t in sleeve}, "sleeve_industry": {t: "x" for t in sleeve},
           "reduce_tickers": list(w["tech"]),
           "baseline_holdings": {t: int(s) for t, s in (baseline if baseline is not None else w["held"]).items()}}
    p = tmp_path / "tact.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return p


def run(world, rb, cfg, phase_date, cpath, tmp_path, holdings=None, cash=None, nav=None):
    holdings = holdings if holdings is not None else world["held"]
    cash = cash if cash is not None else world["cash"]
    nav = nav if nav is not None else world["nav"]
    with O.activate(phase_date, "competition", config_path=cpath, state_dir=tmp_path / "state") as act:
        res = P.construct(world["sc"], holdings, cash, nav, world["closes"], rb, cfg, world["fs"].market, world["etf"], world["meta"])
    return res, act


def test_entry_rotates_tech_into_sleeve_and_stays_legal(world, rb, cfg, tmp_path):
    res, act = run(world, rb, cfg, T, make_cfg(tmp_path, world), tmp_path)
    assert isinstance(res, TargetPortfolio) and act.record["status"] == "APPLIED"
    rec = act.record
    assert rec["tech_weight_after"] < rec["tech_weight_before"] - 0.04
    sells, buys = rec["sells"], rec["buys"]
    assert sells and buys and set(sells) <= set(world["tech"]) and set(buys) <= set(world["sleeve"][:4])
    assert all(v % 1000 == 0 for v in {**sells, **buys}.values())
    assert 20 <= len(res.est_holdings) <= 30 and res.est_cash / res.est_nav < rb.rules.cash_max_weight
    assert all(w <= rb.rules.max_weight(t) for t, w in res.est_weights.items())
    assert res.active_share is not None and res.active_share.minimum_active_share >= O.AS_FLOOR
    assert (tmp_path / "state" / f"{T}_ENTRY.json").is_file()


def test_unwind_restores_the_stored_lots_from_actual_holdings(world, rb, cfg, tmp_path):
    cpath = make_cfg(tmp_path, world)
    res, act = run(world, rb, cfg, T, cpath, tmp_path)
    after, cash2 = dict(res.est_holdings), res.est_cash
    nav2 = sum(Decimal(s) * world["closes"][t] for t, s in after.items()) + cash2
    # the next day: expiry reached, sleeve open -> explicit reverse orders
    res2, act2 = run(world, rb, cfg, "2026-10-28", cpath, tmp_path, holdings=after, cash=cash2, nav=nav2)
    assert act2.record["phase"] == "UNWIND" and act2.record["status"] == "APPLIED", act2.record
    final = dict(res2.est_holdings)
    for t in world["sleeve"][:4]:
        assert t not in final or t in world["held"]
    for t in world["tech"]:
        assert final.get(t, 0) == world["held"][t]
    # unwind only buys tech back / sells sleeve; nothing else is touched
    assert {o.ticker for o in res2.orders} <= set(world["tech"]) | set(world["sleeve"][:4])


def test_unwind_is_noop_when_sleeve_never_opened(world, rb, cfg, tmp_path):
    res, act = run(world, rb, cfg, "2026-10-28", make_cfg(tmp_path, world), tmp_path)
    assert act.record["status"] == "NOOP"
    assert not any(o.ticker in world["sleeve"][:4] for o in res.orders)


def test_unwind_is_expiry_first_even_days_after_the_exit_date(world, rb, cfg, tmp_path):
    cpath = make_cfg(tmp_path, world)
    res, _ = run(world, rb, cfg, T, cpath, tmp_path)
    after, cash2 = dict(res.est_holdings), res.est_cash
    nav2 = sum(Decimal(s) * world["closes"][t] for t, s in after.items()) + cash2
    res2, act2 = run(world, rb, cfg, "2026-11-02", cpath, tmp_path, holdings=after, cash=cash2, nav=nav2)   # late catch-up window
    assert act2.record["status"] == "APPLIED"


def test_entry_fails_closed_when_no_size_passes_and_returns_the_quant_result(world, rb, cfg, tmp_path):
    bad = make_cfg(tmp_path, world, sleeve=["9999"])                    # not in the official universe
    res, act = run(world, rb, cfg, T, bad, tmp_path)
    assert act.record["status"] == "BLOCKED" and "not tradable" in act.record["reason"]
    assert not any(o.ticker == "9999" for o in getattr(res, "orders", []))


def test_unwind_failure_is_reported_as_overdue_never_as_success(world, rb, cfg, tmp_path, monkeypatch):
    cpath = make_cfg(tmp_path, world)
    res, _ = run(world, rb, cfg, T, cpath, tmp_path)
    after, cash2 = dict(res.est_holdings), res.est_cash
    nav2 = sum(Decimal(s) * world["closes"][t] for t, s in after.items()) + cash2
    monkeypatch.setattr(O, "_guards", lambda r, rb_: "forced guard failure")
    res2, act2 = run(world, rb, cfg, "2026-10-28", cpath, tmp_path, holdings=after, cash=cash2, nav=nav2)
    assert act2.record["status"] == "UNWIND_OVERDUE" and act2.record["tactical_status"] == "TACTICAL_UNWIND_OVERDUE"
    assert "retry" in act2.record["reason"]


def test_disabled_missing_or_other_dates_are_noops_and_patch_is_restored(world, rb, cfg, tmp_path):
    orig = P.construct
    for cpath, date in ((make_cfg(tmp_path, world, enabled=False), T), (tmp_path / "missing.yaml", T)):
        res, act = run(world, rb, cfg, date, cpath, tmp_path)
        assert act.summary() is None or act.summary()["status"] == "NOT_TRIGGERED"
    c = make_cfg(tmp_path, world, entry="2030-01-01", exit_="2030-01-02")
    res, act = run(world, rb, cfg, T, c, tmp_path)
    assert act.record is None and P.construct is orig
    with O.activate(T, "historical", config_path=make_cfg(tmp_path, world), state_dir=tmp_path / "s2"):
        assert P.construct is orig                                      # not an operational mode


def test_patch_restored_after_an_exception(world, rb, cfg, tmp_path):
    orig = P.construct
    with pytest.raises(RuntimeError):
        with O.activate(T, "competition", config_path=make_cfg(tmp_path, world), state_dir=tmp_path / "s"):
            raise RuntimeError("boom")
    assert P.construct is orig


def test_program_error_inside_the_override_fails_closed(world, rb, cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(O, "build_entry", lambda *a, **k: (_ for _ in ()).throw(ValueError("bug")))
    res, act = run(world, rb, cfg, T, make_cfg(tmp_path, world), tmp_path)
    assert act.record["status"] == "BLOCKED" and "program error" in act.record["reason"]
    assert isinstance(res, (TargetPortfolio, FallbackToPreviousPortfolio))


def test_fingerprint_is_the_file_hash_and_changes_with_content(world, tmp_path):
    p = make_cfg(tmp_path, world)
    c1 = O.load_config(p)
    assert c1["_fingerprint"] == hashlib.sha256(p.read_bytes()).hexdigest()
    p.write_text(p.read_text(encoding="utf-8") + "# edit\n", encoding="utf-8")
    assert O.load_config(p)["_fingerprint"] != c1["_fingerprint"]


def test_shipped_config_is_consistent_and_does_not_touch_frozen_quant():
    c = O.load_config(ROOT / "config" / "tactical_override_v1.yaml")
    assert c is not None and c["entry_trade_date"] == "2026-11-09" and c["exit_trade_date"] == "2026-11-10"
    assert c["frozen_quant_sha256"] == hashlib.sha256((ROOT / "config" / "strategy_quant_v1.yaml").read_bytes()).hexdigest()
    assert abs(sum(c["sleeve"].values()) - 1) < 1e-6 and set(c["sleeve"]).isdisjoint(c["reduce_tickers"])
    import csv
    uni = {r["ticker"] for r in csv.DictReader(open(ROOT / "config" / "universe_150.csv", encoding="utf-8-sig"))}
    assert set(c["sleeve"]) <= uni and set(c["reduce_tickers"]) <= uni and set(c["baseline_holdings"]) <= uni
    assert not ({"2753", "1476", "6865"} & (set(c["sleeve"]) | set(c["reduce_tickers"])))
    assert len(c["baseline_holdings"]) == 24 and all(v % 1000 == 0 for v in c["baseline_holdings"].values())
