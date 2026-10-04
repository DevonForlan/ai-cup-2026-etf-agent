import math

import numpy as np
import pandas as pd

from agent.data.loaders import HistoryStore
from agent.data.pit import PITView
from agent.features.feature_engine import FEATURES, build_features
from agent.features.momentum import trailing_return
from agent.features.relative_strength import relative_strength
from agent.features.revenue import revenue_features
from agent.portfolio.ranking import score


def panel():
    idx = [f"2026-01-{i:02d}" for i in range(1, 31)]
    return pd.DataFrame({"A": np.arange(100, 130, dtype=float), "B": np.full(30, 50.0)}, index=idx)


def test_trailing_return_exact():
    p = panel()
    assert trailing_return(p, 5)["A"] == 129 / 124 - 1
    assert trailing_return(p, 5)["B"] == 0
    assert trailing_return(p.head(3), 5).isna().all()      # insufficient history -> NaN (not fabricated)


def test_relative_strength_vs_median():
    p = panel()
    rs = relative_strength(p, 20)
    r = trailing_return(p, 20)
    assert math.isclose(rs["A"], r["A"] - r.median())


def test_revenue_yoy_mom():
    rev = pd.DataFrame([{"ticker": "2330", "year": 2025, "month": 9, "revenue": 100.0},
                        {"ticker": "2330", "year": 2026, "month": 8, "revenue": 110.0},
                        {"ticker": "2330", "year": 2026, "month": 9, "revenue": 121.0}])
    f = revenue_features(rev, ["2330", "2317"])
    assert math.isclose(f.loc["2330", "revenue_yoy"], 0.21)
    assert math.isclose(f.loc["2330", "revenue_mom"], 0.10)
    assert pd.isna(f.loc["2317", "revenue_yoy"])


def test_feature_engine_on_fixture(fixture_store, rb):
    T = "2026-10-27"
    fs = build_features(PITView(fixture_store, f"{T}T07:00:00+08:00"), sorted(rb.universe), T)
    f = fs.features
    assert fs.last_data_date == "2026-10-26"
    assert set(FEATURES) <= set(f.columns)
    assert len(f) == 150
    assert f["ret_20d"].notna().sum() == 150
    assert f["revenue_yoy"].notna().sum() > 100
    assert 0 <= fs.market["breadth_above_ma20"] <= 1


def test_missing_data_is_nan(tmp_path, rb):
    st = HistoryStore(tmp_path)
    fs = build_features(PITView(st, "2026-10-27T07:00:00+08:00"), sorted(rb.universe), "2026-10-27")
    assert fs.features["ret_20d"].isna().all()
    assert fs.last_data_date is None


def test_ranking_uses_config_weights(fixture_store, rb, cfg):
    T = "2026-10-27"
    fs = build_features(PITView(fixture_store, f"{T}T07:00:00+08:00"), sorted(rb.universe), T)
    s = score(fs.features, cfg["score_weights"])
    assert s["rank"].min() == 1 and s["score"].notna().sum() == s["eligible"].sum()
    m = score(fs.features, cfg["score_weights"], "B2_momentum")
    top = m.sort_values("rank").index[0]
    assert top == fs.features["ret_20d"].idxmax()
