"""Round 03 turnover controls: EMA smoothing, rank buffer, min holding days, swap margin,
turnover penalty, rebalance frequency (hold mode), state rollover, git/competition guard."""
import copy
from decimal import Decimal

import pandas as pd
import pytest

from agent.config import D
from agent.data.pit import PITView
from agent.features.feature_engine import build_features
from agent.pipeline import etf_holdings_from_view, update_state_after_settlement
from agent.portfolio import baseline as B
from agent.portfolio.constructor import TargetPortfolio, construct
from agent.portfolio.ranking import apply_turnover_scoring, score

T = "2026-10-27"


def make_scores(n=60):
    idx = [f"{1000 + i}" for i in range(n)]
    sc = pd.DataFrame({"score": [1 - i / n for i in range(n)], "eligible": True}, index=idx)
    sc["rank"] = range(1, n + 1)
    return sc


def cfg_with(cfg, **tv):
    c = copy.deepcopy(cfg)
    c["turnover"].update(tv)
    return c


def test_defaults_backward_compatible(cfg):
    tp = B.turnover_params({"strategy_buffers": cfg["strategy_buffers"],
                            "turnover": {"hold_buffer": 10, "no_trade_band": 0.015}})
    assert tp["hold_rank"] == cfg["strategy_buffers"]["target_holdings"] + 10
    assert tp["rebalance_threshold"] == 0.015 and tp["score_ema_alpha"] == 1.0 and tp["rebalance_every"] == 1


def test_rank_buffer_entry_and_hold(cfg):
    sc = make_scores()
    held = {t: 1000 for t in sc.index[10:35]}            # ranks 11..35 held
    c = cfg_with(cfg, entry_rank=20, hold_rank=30, max_new_names_per_day=5, swap_score_margin=0.5)
    sel, info = B.select_names(sc, held, c)
    rank = {t: i + 1 for i, t in enumerate(sc.index)}
    assert all(rank[t] <= 20 for t in info["new"])          # new names only from top 20
    assert all(rank[t] <= 30 for t in info["kept"])         # holdings ranked 31..35 dropped
    assert set(info["dropped"]) == {t for t in held if rank[t] > 30}


def test_min_holding_protects_recent_entries(cfg):
    sc = make_scores()
    held = {sc.index[45]: 1000}                              # rank 46: outside hold_rank
    c = cfg_with(cfg, hold_rank=30, min_holding_days=3, extreme_exit_rank=50)
    _, info = B.select_names(sc, held, c, holding_days={sc.index[45]: 1})
    assert sc.index[45] in info["kept"] and sc.index[45] in info["protected"]
    _, info2 = B.select_names(sc, held, c, holding_days={sc.index[45]: 3})
    assert sc.index[45] in info2["dropped"]
    c2 = cfg_with(cfg, hold_rank=30, min_holding_days=3, extreme_exit_rank=40)   # extreme exit overrides
    _, info3 = B.select_names(sc, held, c2, holding_days={sc.index[45]: 1})
    assert sc.index[45] in info3["dropped"]


def test_swap_margin_blocks_small_improvements(cfg):
    sc = make_scores()
    held = {t: 1000 for t in sc.index[1:26]}                 # ranks 2..26 held; rank 1 is outside
    big = cfg_with(cfg, entry_rank=25, hold_rank=40, swap_score_margin=0.9)
    _, info = B.select_names(sc, held, big)
    assert sc.index[0] not in info["new"]                    # cannot beat weakest by 0.9
    small = cfg_with(cfg, entry_rank=25, hold_rank=40, swap_score_margin=0.0)
    _, info2 = B.select_names(sc, held, small)
    assert sc.index[0] in info2["new"]


def test_ema_and_penalty():
    sc = make_scores(5)
    tp = {"score_ema_alpha": 0.25, "turnover_penalty_lambda": 2, "turnover_cost_score_units": 0.02}
    prev = {sc.index[0]: 0.0}
    out, ema = apply_turnover_scoring(sc, prev, {sc.index[1]}, tp)
    assert ema[sc.index[0]] == pytest.approx(0.25 * 1.0)                 # 0.25*raw + 0.75*0
    assert out.loc[sc.index[1], "score"] == pytest.approx(0.8)           # held: no penalty
    assert out.loc[sc.index[2], "score"] == pytest.approx(0.6 - 0.04)    # not held: -lambda*units
    out1, _ = apply_turnover_scoring(sc, prev, set(), {"score_ema_alpha": 1.0, "turnover_penalty_lambda": 0,
                                                       "turnover_cost_score_units": 0.02})
    assert out1["score"].tolist() == sc["score"].tolist()               # alpha=1, lambda=0 -> baseline


def test_state_rollover_entry_dates():
    st = {"day_index": 3, "entry_date": {"2330": "2026-10-26"}, "entry_index": {"2330": 0}}
    s2 = update_state_after_settlement(st, {"2330": 1000}, {"2330": 1000, "2454": 2000}, "2026-10-29")
    assert s2["entry_date"]["2454"] == "2026-10-29" and s2["entry_index"]["2454"] == 3
    s3 = update_state_after_settlement(s2, {"2330": 1000, "2454": 2000}, {"2454": 2000}, "2026-10-30")
    assert "2330" not in s3["entry_date"]


def _setup(fixture_store, rb, cfg):
    v = PITView(fixture_store, f"{T}T07:00:00+08:00")
    fs = build_features(v, sorted(rb.universe), T)
    sc = score(fs.features, cfg["score_weights"])
    closes = {t: D(round(float(x), 4)) for t, x in fs.features["close_prev"].dropna().items()}
    etf, meta = etf_holdings_from_view(v)
    return fs, sc, closes, etf, meta


def test_non_rebalance_day_holds_everything(fixture_store, rb, cfg):
    fs, sc, closes, etf, meta = _setup(fixture_store, rb, cfg)
    tp = construct(sc, {}, rb.rules.initial_cash, rb.rules.initial_cash, closes, rb, cfg, fs.market, etf, meta)
    held = tp.est_holdings
    nav = sum(Decimal(s) * closes[t] for t, s in held.items()) + tp.est_cash
    # shuffle scores so a rebalance day WOULD trade
    sc2 = sc.copy()
    sc2["score"] = sc2["score"].sample(frac=1, random_state=1).values
    sc2["rank"] = sc2["score"].rank(ascending=False, method="first")
    hold = construct(sc2, held, tp.est_cash, nav, closes, rb, cfg, fs.market, etf, meta, is_rebalance_day=False)
    assert isinstance(hold, TargetPortfolio) and not hold.orders
    assert all(p.action == "NO_TRADE" for p in hold.plan)
    reb = construct(sc2, held, tp.est_cash, nav, closes, rb, cfg, fs.market, etf, meta, is_rebalance_day=True)
    assert reb.orders


def test_competition_mode_blocks_dirty_tree(monkeypatch):
    import agent.pipeline as P
    monkeypatch.setattr(P, "_CODE_VERSION", ("git:abc1234-dirty", True))
    monkeypatch.setattr(P, "code_version", lambda refresh=False: "git:abc1234-dirty")
    with pytest.raises(P.DirtyWorkingTreeError):
        P.require_clean_tree()


def test_code_version_format():
    import re
    from agent.pipeline import code_version
    assert re.fullmatch(r"git:[0-9a-f]{7,12}(-dirty)?|git:unknown", code_version(refresh=True))


def test_odd_lot_holding_is_locked_not_traded(fixture_store, rb, cfg):
    """Stock dividends can leave odd shares; derive-orders.v2 would then emit a non-lot order.
    The constructor must keep such a holding untouched (NO_TRADE) and never fall back."""
    fs, sc, closes, etf, meta = _setup(fixture_store, rb, cfg)
    tp = construct(sc, {}, rb.rules.initial_cash, rb.rules.initial_cash, closes, rb, cfg, fs.market, etf, meta)
    held = dict(tp.est_holdings)
    worst = max(sc.index, key=lambda t: sc.loc[t, "rank"] if sc.loc[t, "rank"] == sc.loc[t, "rank"] else -1)
    held[worst] = 10_500                                   # odd shares in a deselected name
    nav = sum(Decimal(s) * closes[t] for t, s in held.items()) + tp.est_cash
    r = construct(sc, held, tp.est_cash, nav, closes, rb, cfg, fs.market, etf, meta)
    assert isinstance(r, TargetPortfolio), getattr(r, "reason", "")
    assert all(o.shares % 1000 == 0 for o in r.orders)
    assert worst not in {o.ticker for o in r.orders}
    assert any(p.ticker == worst and p.action == "NO_TRADE" and p.reason == "odd_lot_locked" for p in r.plan)
