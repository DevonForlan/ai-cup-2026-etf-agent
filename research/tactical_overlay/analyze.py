"""RESEARCH ONLY (Issue #14). Gate G1–G7 and outcome mapping exactly as PRE_REGISTRATION.md §5–§7.
Reads results/overlay_windows.csv, overlay_placebo.csv, market_signals.csv; writes results/gate.csv, gate.json,
regime_breakdown.csv."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lab as L  # noqa: E402

OUT = HERE / "results"


def block_boot_lb(x: np.ndarray, block: int = 4, n: int = 2000, q: float = 0.10, seed: int = 14) -> float:
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(len(x) / block))
    starts = np.arange(len(x) - block + 1)
    means = [np.concatenate([x[s:s + block] for s in rng.choice(starts, nb)])[:len(x)].mean() for _ in range(n)]
    return float(np.quantile(means, q))


def holm(p: dict) -> dict:
    items = sorted(p.items(), key=lambda kv: kv[1])
    m, out, run = len(items), {}, 0.0
    for i, (k, v) in enumerate(items):
        run = max(run, min(1.0, (m - i) * v))
        out[k] = run
    return out


def main() -> int:
    ow = pd.read_csv(OUT / "overlay_windows.csv")
    pl = pd.read_csv(OUT / "overlay_placebo.csv") if (OUT / "overlay_placebo.csv").exists() else None
    nov = ow[ow["set"] == "NOV23"]
    dense = ow[ow["set"] == "DENSE24"].sort_values("start")
    base_n = nov[nov["variant"] == "BASE"].set_index("wid")
    rows, pvals = [], {}
    for v in L.VARIANTS:
        g = nov[nov["variant"] == v].set_index("wid")
        disc, oos = g[g["period"] == "DISCOVERY"], g[g["period"] == "OOS"]
        dd = dense[(dense["variant"] == v) & (dense["period"] == "OOS")]["d_ret"].to_numpy()
        dd_disc = dense[(dense["variant"] == v) & (dense["period"] == "DISCOVERY")]["d_ret"].to_numpy()
        bo = base_n[base_n["period"] == "OOS"]
        x = oos["d_ret"].to_numpy()
        p = L.signflip_p(x)
        pvals[v] = p
        pl_means = pl[pl["variant"] == v].groupby("k")["d_ret"].mean().to_numpy() if pl is not None else np.array([])
        r = {"variant": v, "family": v[:2],
             "disc_mean_d": disc["d_ret"].mean(), "disc_dense_mean_d": float(dd_disc.mean()) if len(dd_disc) else np.nan,
             "oos_mean_d": x.mean(), "oos_median_d": float(np.median(x)), "oos_wins": int((x > 0).sum()), "oos_n": len(x),
             "dense_oos_mean_d": float(dd.mean()) if len(dd) else np.nan,
             "dense_oos_lb90": block_boot_lb(dd) if len(dd) >= 8 else np.nan,
             "placebo_p95": float(np.quantile(pl_means, 0.95)) if len(pl_means) else np.nan,
             "oos_mean_d_mdd": oos["d_mdd"].mean(),
             "oos_worst_mdd_delta": oos["mdd"].max() - bo["mdd"].max(),
             "oos_top_decile": float((oos["pctile_exitcost"] >= 90).mean()), "base_top_decile": float((bo["pctile_exitcost"] >= 90).mean()),
             "oos_top_decile_nav": float((oos["pctile_nav"] >= 90).mean()), "base_top_decile_nav": float((bo["pctile_nav"] >= 90).mean()),
             "oos_turnover": oos["turnover"].mean(), "base_turnover": bo["turnover"].mean(),
             "oos_cost_pct": oos["cost_pct"].mean(), "base_cost_pct": bo["cost_pct"].mean(),
             "violations": int(g["violations"].sum() + dense[dense["variant"] == v]["violations"].sum()),
             "violations_official": int(g["violations_official"].sum() + dense[dense["variant"] == v]["violations_official"].sum()),
             "signflip_p": p}
        r["G1"] = r["oos_mean_d"] >= 0.005
        r["G2"] = r["oos_wins"] >= 7
        r["G3"] = bool(r["dense_oos_lb90"] > 0)
        r["G4"] = bool(r["oos_mean_d"] > r["placebo_p95"]) if not np.isnan(r["placebo_p95"]) else False
        r["G5"] = (r["oos_mean_d_mdd"] <= 0.01) and (r["oos_worst_mdd_delta"] <= 0.02)
        r["G6"] = r["oos_top_decile"] >= r["base_top_decile"]
        r["G7"] = r["violations_official"] == 0          # official compliance (see REPORT §deviations)
        r["ALL"] = all(r[f"G{i}"] for i in range(1, 8))
        rows.append(r)
    gate = pd.DataFrame(rows)
    hp = holm(pvals)
    gate["holm_p"] = gate["variant"].map(hp)
    carried = {}
    for fam, vs in L.FAMILIES.items():
        sub = gate[gate["variant"].isin(vs)].sort_values("disc_mean_d", ascending=False)
        best = sub.iloc[0]
        carried[fam] = best["variant"] if best["disc_mean_d"] > 0 else None
    gate["carried"] = gate.apply(lambda r: carried.get(r["family"]) == r["variant"], axis=1)
    gate.to_csv(OUT / "gate.csv", index=False)
    passing = gate[gate["carried"] & gate["ALL"]]["variant"].tolist()
    ms = pd.read_csv(OUT / "market_signals.csv") if (OUT / "market_signals.csv").exists() else None
    advisory = []
    if ms is not None:
        for (sig, tgt), g in ms.groupby(["signal", "target"]):
            o, d = g[g["period"] == "OOS"], g[g["period"] == "DISCOVERY"]
            if len(o) and len(d) and o["p"].iloc[0] < 0.05 and np.sign(o["rho"].iloc[0]) == np.sign(d["rho"].iloc[0]):
                advisory.append({"signal": sig, "target": tgt, "rho_oos": o["rho"].iloc[0], "p_oos": o["p"].iloc[0],
                                 "rho_disc": d["rho"].iloc[0]})
    outcome = "PROMOTION_CANDIDATE" if passing else ("ADD_ADVISORY_LAYER_ONLY" if advisory else "KEEP_FROZEN_ONLY")
    # regime breakdown (NOV23 + DENSE24 OOS): up / down market by EW return, high / low breadth at start
    data_mk = None
    try:
        data_mk = L.Data().sig["market"]
    except Exception:  # noqa: BLE001
        pass
    reg = []
    for st, gw in (("NOV23", nov), ("DENSE24", dense)):
        b = gw[gw["variant"] == "BASE"].set_index("start")
        for v in ["BASE"] + L.VARIANTS:
            g = gw[gw["variant"] == v].set_index("start")
            for s in g.index:
                mkt = "UP" if b.loc[s, "ew_ret"] > 0 else "DOWN"
                br = data_mk.at[s, "breadth"] if data_mk is not None and s in data_mk.index else np.nan
                reg.append({"set": st, "variant": v, "start": s, "period": g.loc[s, "period"], "market": mkt,
                            "breadth_start": "HIGH" if br >= 0.5 else ("LOW" if br == br else "NA"),
                            "ret": g.loc[s, "ret"], "d_ret": g.loc[s, "d_ret"], "ew_ret": b.loc[s, "ew_ret"]})
    rb = pd.DataFrame(reg)
    rb.to_csv(OUT / "regime_breakdown.csv", index=False)
    res = {"outcome": outcome, "passing": passing, "carried": carried, "advisory_signals": advisory}
    (OUT / "gate.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    pd.set_option("display.width", 250)
    print(gate[["variant", "carried", "disc_mean_d", "oos_mean_d", "oos_wins", "dense_oos_mean_d", "dense_oos_lb90",
                "placebo_p95", "oos_mean_d_mdd", "oos_top_decile", "base_top_decile", "violations", "violations_official", "holm_p"]
               + [f"G{i}" for i in range(1, 8)]].round(4).to_string(index=False))
    print(json.dumps(res, ensure_ascii=False, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
