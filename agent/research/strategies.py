"""Strategy registry for Round 03 research: ablations, turnover matrix, weight search.

Each strategy = base config (config/strategy.yaml) + overrides (dotted keys). The full resolved
config is snapshotted with every run. Keep the set small and explainable (no brute force)."""
from __future__ import annotations

import copy
import hashlib
import json

# ---- factor groups (percentile-rank features; weights are relative, roughly sum 1) ----
MOM = {"ret_20d": 0.6, "ret_60d": 0.4}
RS = {"relative_strength_20d": 0.5, "relative_strength_60d": 0.3, "distance_to_52w_high": 0.2}
INST = {"institutional_flow_5d": 0.6, "institutional_flow_20d": 0.4}
REV = {"revenue_yoy": 0.7, "revenue_mom": 0.3}
RISK = {"volatility_20d": -1.0}

ZERO = {k: 0.0 for k in ["ret_5d", "ret_20d", "ret_60d", "relative_strength_20d", "relative_strength_60d",
                         "distance_to_52w_high", "institutional_flow_5d", "institutional_flow_20d",
                         "revenue_yoy", "revenue_mom", "volatility_20d", "volume_ratio_5d"]}


def mix(**groups: float) -> dict[str, float]:
    """mix(MOM=0.4, INST=0.3, ...) -> flat score_weights."""
    table = {"MOM": MOM, "RS": RS, "INST": INST, "REV": REV, "RISK": RISK}
    w = dict(ZERO)
    for g, gw in groups.items():
        for f, fw in table[g].items():
            w[f] = round(w[f] + gw * fw, 6)
    return w


# Round 02 turnover behaviour (for clean factor ablations)
R02_TURNOVER = {"score_ema_alpha": 1.0, "entry_rank": 25, "hold_rank": 35, "min_holding_days": 0,
                "rebalance_threshold": 0.015, "swap_score_margin": 0.10, "turnover_penalty_lambda": 0,
                "rebalance_every": 1, "max_new_names_per_day": 5}
# a moderate controlled default (starting point of the turnover matrix; NOT tuned on results)
CTRL = {"score_ema_alpha": 0.4, "entry_rank": 20, "hold_rank": 35, "min_holding_days": 3,
        "rebalance_threshold": 0.01, "swap_score_margin": 0.05, "turnover_penalty_lambda": 1,
        "rebalance_every": 1, "max_new_names_per_day": 3}

FULL_V1 = mix(MOM=0.30, RS=0.20, INST=0.20, REV=0.20, RISK=0.10)


def _s(sid: str, group: str, desc: str, weights: dict, turnover: dict, **extra) -> dict:
    ov = {"score_weights": weights, "turnover": turnover, "baseline.method": extra.pop("method", "B0_score_tiered")}
    ov.update(extra)
    return {"strategy_id": sid, "group": group, "desc": desc, "overrides": ov}


def registry() -> list[dict]:
    S = []
    # ---- ablations (Round-02 turnover so only the factor set changes) ----
    S += [
        _s("A1_mom", "ablation", "Momentum only", mix(MOM=1), R02_TURNOVER),
        _s("A2_rs", "ablation", "Relative strength only", mix(RS=1), R02_TURNOVER),
        _s("A3_inst", "ablation", "Institutional flow only", mix(INST=1), R02_TURNOVER),
        _s("A4_rev", "ablation", "Revenue only", mix(REV=1), R02_TURNOVER),
        _s("A5_mom_rs", "ablation", "Momentum + RS", mix(MOM=0.5, RS=0.5), R02_TURNOVER),
        _s("A6_mom_inst", "ablation", "Momentum + Institutional", mix(MOM=0.5, INST=0.5), R02_TURNOVER),
        _s("A7_inst_rev", "ablation", "Institutional + Revenue", mix(INST=0.5, REV=0.5), R02_TURNOVER),
        _s("A8_mom_inst_rev", "ablation", "Mom + Inst + Rev", mix(MOM=0.34, INST=0.33, REV=0.33), R02_TURNOVER),
        _s("A9_full", "ablation", "Full Quant v1 (Round-02 turnover)", FULL_V1, R02_TURNOVER),
        _s("A10_full_ctrl", "ablation", "Full Quant v1 + turnover controls", FULL_V1, CTRL),
    ]
    # ---- baselines ----
    S += [
        _s("BL_mom_weekly", "baseline", "20d momentum Top25, weekly rebalance", mix(MOM=1),
           dict(R02_TURNOVER, rebalance_every=5, max_new_names_per_day=25, swap_score_margin=0.0)),
        _s("BL_inst_weekly", "baseline", "5d institutional Top25, weekly rebalance", mix(INST=1),
           dict(R02_TURNOVER, rebalance_every=5, max_new_names_per_day=25, swap_score_margin=0.0)),
        _s("BL_r02_B3", "baseline", "Round-02 B3 (5d institutional, daily)", {"institutional_flow_5d": 1.0, **{k: 0 for k in ZERO if k != "institutional_flow_5d"}},
           {"hold_buffer": 10, "no_trade_band": 0.015, "swap_score_margin": 0.10, "max_new_names_per_day": 5},
           method="B3_institutional"),
        _s("BL_r02_B0", "baseline", "Round-02 B0 default", None, None),
    ]
    # ---- turnover matrix: one-at-a-time around CTRL on FULL_V1, plus a few combos ----
    one = [("score_ema_alpha", [1.0, 0.6, 0.25]), (("entry_rank", "hold_rank"), [(15, 30), (25, 40)]),
           ("min_holding_days", [1, 5]), ("rebalance_threshold", [0.005, 0.015]),
           ("swap_score_margin", [0.02, 0.10]), ("turnover_penalty_lambda", [0, 2, 5]),
           ("rebalance_every", [2, 3, 5])]
    for key, vals in one:
        for v in vals:
            t = dict(CTRL)
            if isinstance(key, tuple):
                t[key[0]], t[key[1]] = v
                name = f"{key[0]}{v[0]}_{key[1]}{v[1]}"
            else:
                t[key] = v
                name = f"{key}{v}"
            S.append(_s(f"T_{name}", "turnover", f"CTRL with {name}", FULL_V1, t))
    S += [
        _s("T_strong", "turnover", "strong hysteresis", FULL_V1,
           dict(CTRL, score_ema_alpha=0.25, entry_rank=15, hold_rank=40, min_holding_days=5,
                swap_score_margin=0.10, turnover_penalty_lambda=2)),
        _s("T_weekly_ctrl", "turnover", "CTRL + weekly", FULL_V1, dict(CTRL, rebalance_every=5)),
        _s("T_light", "turnover", "light controls", FULL_V1,
           dict(CTRL, score_ema_alpha=0.6, min_holding_days=1, turnover_penalty_lambda=0.5)),
    ]
    # ---- factor weight search under CTRL (few, reasoned configs) ----
    W = {
        "W_A_mom40": mix(MOM=0.40, INST=0.30, REV=0.20, RISK=0.10),
        "W_B_inst40": mix(INST=0.40, MOM=0.30, REV=0.20, RISK=0.10),
        "W_C_rev30": mix(REV=0.30, MOM=0.30, INST=0.30, RISK=0.10),
        "W_D_rs_inst": mix(RS=0.35, INST=0.35, REV=0.20, RISK=0.10),
        "W_E_trend": mix(MOM=0.30, RS=0.30, INST=0.30, RISK=0.10),
        "W_F_norisk": mix(MOM=0.35, RS=0.20, INST=0.25, REV=0.20),
    }
    for k, w in W.items():
        S.append(_s(k, "weights", k, w, CTRL))
    # ---- low-frequency "pick & hold" family (cost-aware; added after round-03 first batch showed
    #      transaction costs dominate): rebalance every 10 days or never (compliance-only trades) ----
    HOLD10 = dict(CTRL, rebalance_every=10, min_holding_days=5, rebalance_threshold=0.02)
    HOLDN = dict(CTRL, rebalance_every=100, min_holding_days=5, rebalance_threshold=0.02)
    for name, w in (("full", FULL_V1), ("mom40", W["W_A_mom40"]), ("trend", W["W_E_trend"]),
                    ("rev", mix(REV=1)), ("inst_rev", mix(INST=0.5, REV=0.5)), ("mom", mix(MOM=1))):
        S.append(_s(f"H10_{name}", "hold", f"{name} factors, rebalance every 10 days", w, HOLD10))
        S.append(_s(f"HN_{name}", "hold", f"{name} factors, buy day-1 then hold (compliance only)", w, HOLDN))
    # ---- regime v0 on/off (soft cash range only) ----
    S.append(_s("R_ctrl_regime", "regime", "CTRL + regime v0", FULL_V1, CTRL, **{"regime.use_v0": True}))
    S.append(_s("R_h10_regime", "regime", "H10 full + regime v0", FULL_V1, HOLD10, **{"regime.use_v0": True}))
    return S


def resolve(base: dict, strategy: dict) -> dict:
    cfg = copy.deepcopy(base)
    for k, v in strategy["overrides"].items():
        if v is None:
            continue
        node = cfg
        parts = k.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        if parts[-1] == "turnover" and isinstance(v, dict):
            node["turnover"] = dict(v)
        else:
            node[parts[-1]] = copy.deepcopy(v)
    cfg["strategy_name"] = strategy["strategy_id"]
    return cfg


def config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:10]
