"""RESEARCH ONLY. Applies ACCEPTANCE_GATE.md (fixed before results) to screened factors and ablation combos.
Inputs: results/portfolio_single.csv, portfolio_valuation.csv, portfolio_gate.csv, portfolio_placebo.csv,
ic_incremental.csv, screening_discovery.csv. Output: results/gate_results.csv, results/gate_summary.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "research" / "factor_research" / "results"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_results import paired  # noqa: E402

VAL_FACTORS = {"earnings_yield", "book_to_price", "div_yield", "roe_proxy", "eps_ttm_growth"}


def load(name):
    p = RES / name
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


def main() -> int:
    single = pd.concat([load("portfolio_single.csv"), load("portfolio_valuation.csv")], ignore_index=True)
    single = single.drop_duplicates(["sid", "wid", "cost_mult", "slippage"])
    gate = load("portfolio_gate.csv")
    placebo = load("portfolio_placebo.csv")
    allrows = pd.concat([single, gate, placebo], ignore_index=True).drop_duplicates(["sid", "wid", "cost_mult", "slippage"])
    pr = paired(allrows)
    pr.to_csv(RES / "paired_all.csv", index=False)
    inc = load("ic_incremental.csv")
    scr = load("screening_discovery.csv")
    # valuation screening (same rule, DISCOVERY only)
    vrows = []
    for f in VAL_FACTORS:
        d = pr[(pr.sid == f"F_{f}") & (pr.period == "DISCOVERY") & (pr.n > 0)]
        dic = inc[(inc.factor == f) & (inc.period == "DISCOVERY")]["delta_ic"]
        if len(d) and len(dic):
            vrows.append({"factor": f, "disc_d_ret": float(d["d_ret_mean"].iloc[0]), "disc_delta_ic": float(dic.iloc[0]),
                          "screen_pass": bool(d["d_ret_mean"].iloc[0] > 0 and dic.iloc[0] > 0)})
    scr = pd.concat([scr[~scr.factor.isin(VAL_FACTORS)], pd.DataFrame(vrows)], ignore_index=True)
    scr.to_csv(RES / "screening_discovery_all.csv", index=False)
    passed = scr[scr.screen_pass].factor.tolist()
    # placebo null on OOS (official cost)
    plo = pr[pr.sid.str.startswith("P_") & (pr.period == "OOS") & (pr.n == 12)]["d_ret_mean"]
    pl_mean, pl_sd, pl_max = float(plo.mean()), float(plo.std()), float(plo.max())
    pl_95 = pl_mean + 1.645 * pl_sd
    plo2 = pr[pr.sid.str.startswith("P2_") & (pr.period == "OOS") & (pr.n == 12)]["d_ret_mean"]
    pl2_95 = float(plo2.mean() + 1.645 * plo2.std()) if len(plo2) > 1 else np.nan

    def P(sid, per="OOS"):
        x = pr[(pr.sid == sid) & (pr.period == per)]
        return x.iloc[0] if len(x) else None

    def cost_row(sid, cm, sl):
        """paired OOS delta vs BASE_V1 under the same cost setting"""
        g = allrows[(allrows.cost_mult == cm) & (allrows.slippage == sl)]
        a = g[g.sid == sid].set_index("wid")["ret"]
        b = g[g.sid == "BASE_V1"].set_index("wid")["ret"]
        j = a.to_frame("a").join(b.to_frame("b"), how="inner")
        j = j[j.index.isin([w for w in j.index])]
        return float((j["a"] - j["b"]).mean()) if len(j) else np.nan, len(j)

    COMBO_COMPONENTS = {"A_REV3M+FOREIGN5": ["rev_3m_yoy", "foreign_5"]}

    def evaluate(sid, factor=None, kind="factor"):
        comps = COMBO_COMPONENTS.get(sid)
        o = P(sid)
        if o is None or o["n"] < 12:
            return None
        r = {"sid": sid, "kind": kind, "oos_n": int(o["n"]), "oos_d_ret_mean": o["d_ret_mean"], "oos_d_ret_median": o["d_ret_median"],
             "ci_lo": o["ci_lo"], "ci_hi": o["ci_hi"], "win_share": o["win_share"],
             "disc_d_ret": P(sid, "DISCOVERY")["d_ret_mean"] if P(sid, "DISCOVERY") is not None else np.nan,
             "val_d_ret": P(sid, "VALIDATION")["d_ret_mean"], "hold_d_ret": P(sid, "HOLDOUT")["d_ret_mean"]}
        g = {}
        g["G1_median_and_mean"] = bool(o["ret_median"] >= o["ret_median_b"] and o["d_ret_mean"] > 0)
        if factor or comps:
            c15, n1 = cost_row(sid, 1.5, 0.0)
            s20, n2 = cost_row(sid, 1.0, 0.002)
            c125, _ = cost_row(sid, 1.25, 0.0)
            s10, _ = cost_row(sid, 1.0, 0.001)
            r.update(d_cost125=c125, d_cost15=c15, d_slip10=s10, d_slip20=s20)
            g["G2_cost"] = bool(n1 >= 12 and n2 >= 12 and c15 >= 0 and s20 >= 0)
        else:
            g["G2_cost"] = None                                   # not run for combos unless a combo passes the rest
        g["G3_worst_window"] = bool(o["worst"] >= o["worst_b"] - 0.01)
        g["G4_mdd"] = bool(o["mdd_mean"] <= o["mdd_mean_b"] + 0.01 and o["mdd_max"] <= o["mdd_max_b"] + 0.02)
        if factor or comps:
            fl = [factor] if factor else comps
            iv = inc[inc.factor.isin(fl) & inc.period.isin(["VALIDATION", "HOLDOUT"])]["delta_ic"]
            g["G5_rank_ic"] = bool(len(iv) == 2 * len(fl) and (iv >= 0).all())     # combo: every component
            if factor:
                r["delta_ic_val"], r["delta_ic_hold"] = (list(iv) + [np.nan, np.nan])[:2]
            sens = []
            for m in ("0.8", "0.9", "1.1", "1.2"):
                s = P(f"S_{factor or sid}_x{m}")
                sens.append(s["d_ret_mean"] if s is not None and s["n"] >= 12 else np.nan)
            r.update({f"sens_x{m}": v for m, v in zip(("0.8", "0.9", "1.1", "1.2"), sens)})
            ok = sum(1 for v in sens + [o["d_ret_mean"]] if v == v and v >= 0)
            g["G6_sensitivity"] = bool(ok >= 4)
        else:
            g["G5_rank_ic"] = None
            g["G6_sensitivity"] = None
        g["G7_turnover"] = bool(o["post1_turn"] <= o["post1_turn_b"] + 0.5)
        g["G8_cost_level"] = bool(o["cost"] <= o["cost_b"] * 1.5)
        g["G9_active_share"] = bool(pd.isna(o["as_min"]) or o["as_min"] >= 0.15)
        g["G10_compliance"] = bool(o["viol"] <= o["viol_b"] and o["vfail"] == 0)
        g["G11_fallback"] = bool(o["fallback"] == 0)
        g["G12_pit"] = True if not factor else factor != "mops_count_5"     # all others PIT_SAFE (FACTOR_DATA_AUDIT)
        g["G13_daily_data"] = "CONDITIONAL_NEW_FETCHER" if (factor in VAL_FACTORS) else True
        r.update(g)
        r.update(post1_turn=o["post1_turn"], post1_turn_b=o["post1_turn_b"], cost=o["cost"], cost_b=o["cost_b"],
                 mdd_mean=o["mdd_mean"], mdd_mean_b=o["mdd_mean_b"], worst=o["worst"], worst_b=o["worst_b"],
                 as_min=o["as_min"], rand_pct_median=o["rand_pct_median"], rand_pct_median_b=o["rand_pct_median_b"],
                 sortino=o["sortino"], sortino_b=o["sortino_b"], cvar95=o["cvar95"], cvar95_b=o["cvar95_b"])
        hard = [v for k, v in g.items() if k.startswith("G") and v is not None and v != "CONDITIONAL_NEW_FETCHER"]
        r["gate_pass"] = bool(all(hard)) and all(v is not None for k, v in g.items() if k in ("G2_cost", "G5_rank_ic", "G6_sensitivity"))
        r["beats_placebo_95"] = bool(o["d_ret_mean"] > (pl2_95 if comps else pl_95))
        r["ci_excludes_zero"] = bool(o["ci_lo"] > 0)
        return r

    rows = [evaluate(f"F_{f}", f) for f in passed]
    abl = sorted({s for s in pr.sid if s.startswith("A_") and not s.startswith("A_REV+") and s not in
                  ("A_REV", "A_INST", "A_TREND", "A_LIQ", "A_INST+TREND")})
    rows += [evaluate(s, None, "ablation") for s in abl]
    rows = [r for r in rows if r]
    out = pd.DataFrame(rows)
    out.to_csv(RES / "gate_results.csv", index=False)
    summ = {"screened": passed, "placebo_oos": {"mean": pl_mean, "sd": pl_sd, "max": pl_max, "p95": pl_95, "n": int(len(plo))},
            "placebo2_oos": {"mean": float(plo2.mean()) if len(plo2) else None, "sd": float(plo2.std()) if len(plo2) > 1 else None,
                             "max": float(plo2.max()) if len(plo2) else None, "p95": pl2_95, "n": int(len(plo2))},
            "gate_pass": out[out.gate_pass].sid.tolist() if len(out) else [],
            "gate_pass_and_beats_placebo": out[out.gate_pass & out.beats_placebo_95].sid.tolist() if len(out) else []}
    (RES / "gate_summary.json").write_text(json.dumps(summ, indent=1), encoding="utf-8")
    pd.set_option("display.width", 260)
    cols = ["sid", "oos_d_ret_mean", "ci_lo", "ci_hi", "val_d_ret", "hold_d_ret"] + [c for c in out.columns if c.startswith("G")] + ["gate_pass", "beats_placebo_95"]
    print(out[cols].round(4).to_string())
    print(json.dumps(summ, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
