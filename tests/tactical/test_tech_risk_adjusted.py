"""Issue #68: risk-adjusted technology policy (pure-function tests; no network, no local history)."""
import hashlib
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd

from agent.config import ROOT
from agent.tactical import tech_overweight as TW
from agent.tactical import tech_regime as RG

TECH = {f"T{i}" for i in range(30)}


def _prices(drift_tech, vol_tech=0.0, days=30):
    rows = []
    for t in sorted(TECH) + ["N1", "N2", "N3"]:
        px = 100.0
        for d in range(days):
            r = (drift_tech if t in TECH else 0.0) + (vol_tech if (t in TECH and d % 2) else -vol_tech if t in TECH else 0.0)
            px *= 1 + r
            rows.append({"date": f"2026-10-{d + 1:02d}", "ticker": t, "open": px, "close": px, "volume": 1000})
    return pd.DataFrame(rows)


def _overnight(sox5=0.03, sox1=0.01, txf=0.005):
    rows = [{"date": f"2026-10-{d + 1:02d}", "symbol": "SOX", "close": 100 * (1 + sox5 / 5) ** d, "ret": sox1 if d == 29 else 0.0} for d in range(30)]
    rows += [{"date": "2026-10-30", "symbol": "TXF_NIGHT", "close": 1.0, "ret": txf}]
    return pd.DataFrame(rows)


def test_regime_bands():
    strong = RG.classify_regime(_prices(0.004), _overnight(), TECH, {})
    assert (strong["regime"], strong["band_min"], strong["band_max"]) == ("STRONG", 0.90, 0.95)
    defensive = RG.classify_regime(_prices(0.004, vol_tech=0.03), _overnight(), TECH, {})
    assert defensive["regime"] == "DEFENSIVE" and defensive["band_max"] == 0.88 and any("vol" in r for r in defensive["reasons"])
    assert RG.classify_regime(_prices(0.004), _overnight(sox1=-0.03), TECH, {})["regime"] == "DEFENSIVE"       # SOX overnight drop
    normal = RG.classify_regime(_prices(0.004), _overnight(sox5=-0.01), TECH, {})                              # strength test not fully met
    assert normal["regime"] == "NORMAL" and (normal["band_min"], normal["band_max"]) == (0.87, 0.92)
    assert RG.classify_regime(None, None, TECH, {})["missing_inputs"]                                          # missing data is explicit, never fatal


def test_composite_score_uses_all_signals():
    base = {"rs5": 0.0, "rs20": 0.0, "flow5": 0.0, "vol20": 0.02, "gap_max5": 0.01, "move_max5": 0.01}
    sig = {f"T{i}": dict(base) for i in range(6)}
    sig["T0"].update(rs5=0.1, rs20=0.1, flow5=0.2)                     # strong, with flow
    sig["T1"].update(vol20=0.08)                                       # very volatile
    sig["T2"].update(gap_max5=0.09)                                    # extreme gap
    rank = {t: 10 for t in sig}
    z = RG.composite_score(sig, rank, {})
    assert z["T0"] == max(z.values()) and z["T1"] < z["T3"] and z["T2"] < z["T3"]
    better_rank = RG.composite_score(sig, {**rank, "T3": 1}, {})
    assert better_rank["T3"] > z["T3"]                                 # Frozen Quant rank is part of the score


def test_bucket_cap_limits_concentration():
    tw = {f"T{i}": Decimal("0.01") for i in range(8)} | {"T8": Decimal("0.04"), "T9": Decimal("0.04"), "N1": Decimal("0.40"), "N2": Decimal("0.40")}
    bucket = {f"T{i}": ("memory" if i < 8 else "asic") for i in range(10)}
    w, _, _ = TW.overlay_weights(tw, set(), {f"T{i}": i + 1 for i in range(10)}, {}, set(bucket), 0.50, Decimal("0.09"), mode="proportional",
                                 bucket_of=bucket, bucket_cap=Decimal("0.20"))
    assert sum(v for t, v in w.items() if bucket.get(t) == "memory") <= Decimal("0.2000001")
    free, _, _ = TW.overlay_weights(tw, set(), {f"T{i}": i + 1 for i in range(10)}, {}, set(bucket), 0.50, Decimal("0.09"), mode="proportional")
    assert sum(v for t, v in free.items() if bucket.get(t) == "memory") > Decimal("0.2")   # the cap was binding


def test_tilt_multiplier_shifts_increment_to_better_names():
    tw = {"T0": Decimal("0.05"), "T1": Decimal("0.05"), "N1": Decimal("0.40")}
    w, _, _ = TW.overlay_weights(tw, set(), {"T0": 1, "T1": 2}, {}, {"T0", "T1"}, 0.20, Decimal("0.20"), mult={"T0": 2.0, "T1": 0.5})
    assert w["T0"] > w["T1"]


def test_utility_penalises_single_risk_factor_and_cost():
    z = {f"T{i}": 0.0 for i in range(4)}
    sg = {t: 0.02 for t in z}
    w = {t: 0.2 for t in z}
    one = RG.utility(w, z, sg, {t: "memory" for t in z}, 0.0, {})
    spread = RG.utility(w, z, sg, {"T0": "a", "T1": "b", "T2": "c", "T3": "d"}, 0.0, {})
    assert spread["utility"] > one["utility"] and spread["risk"] < one["risk"]                 # same tickers, concentrated factor = riskier
    assert RG.utility(w, z, sg, {t: "a" for t in z}, 0.001, {})["utility"] < RG.utility(w, z, sg, {t: "a" for t in z}, 0.0, {})["utility"]


def test_trade_cost_sell_tax_and_turnover():
    orders = [SimpleNamespace(ticker="A", shares=1000, side="BUY"), SimpleNamespace(ticker="B", shares=1000, side="SELL")]
    cost, turn = RG.trade_cost(orders, {"A": 100, "B": 100}, 1_000_000, {})
    assert abs(turn - 0.2) < 1e-9 and cost > 0.2 * 0.001425 * 2 + 0.1 * 0.003 * 0           # sell side carries tax
    assert RG.trade_cost([], {}, 1, {}) == (0.0, 0.0)


def test_policy_effective_from_1116_and_history_untouched():
    cfg = TW.load_config()
    assert TW.resolve("2026-11-13")["policy"] is None and TW.resolve("2026-11-15")["policy"] is None   # #65 history dates keep the old search
    for d in ("2026-11-16", "2026-11-27", "2027-01-04"):
        r = TW.resolve(d)
        assert r["policy"] == "risk_adjusted" and r["target_tech_weight_min"] == 0.85 and r["risk_adjusted"]["bucket_cap"] == 0.30
    b = cfg["risk_adjusted"]["buckets"]
    assert {"memory_storage", "pcb_ccl_materials", "asic_ic_design"} <= set(b)
    assert not (set(b["memory_storage"]) & set(b["asic_ic_design"]))
    assert hashlib.sha256((ROOT / "config/strategy_quant_v1.yaml").read_bytes()).hexdigest() == \
        "f34fa02e924011b20c52a4bd42e961169f97e1950e76e04b7e78dc43ac23d2e0"
