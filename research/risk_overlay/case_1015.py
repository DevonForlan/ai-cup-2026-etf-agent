"""RESEARCH ONLY — counterfactual case study for the 2026-10-15 paper-trading loss. Reads the paper ledger; never
modifies predictions, D-Plans or the ledger. Output: results/case_1015.json
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
warnings.filterwarnings("ignore")
import overlay_lab as L  # noqa: E402
from agent.data.loaders import HistoryStore  # noqa: E402
from agent.engine.rules import load_rulebook  # noqa: E402


def overnight_asof(m: pd.DataFrame, ts: str) -> dict:
    t = pd.Timestamp(ts)
    out = {}
    for sym in ("SOX", "NDX", "SPX", "TSM", "TXF_NIGHT", "USDTWD"):
        g = m[(m.symbol == sym) & (m.ts <= t)].sort_values("ts")
        if sym == "USDTWD":
            g = g.assign(ret=g["close"] / g["close"].shift(5) - 1)
        if len(g) and (t - g.ts.iloc[-1]) <= pd.Timedelta(hours=L.STALE_H):
            out["USDTWD_5d" if sym == "USDTWD" else sym] = (float(g.ret.iloc[-1]), str(g.ts.iloc[-1]))
    return out


def main() -> int:
    store = HistoryStore()
    rules = load_rulebook().rules
    s = L.build_signals(store, ["2026-10-16"])
    m = store.load("market_overnight").copy()
    m["ts"] = pd.to_datetime(m["available_at"].astype(str).str[:19])
    S = L.candidate_states(s)
    v = L.votes(s)
    res = {"decision_points": {}}
    # (b) the paper workflow generated the 10/15 prediction at 2026-10-14 21:26 (price data through 10/14 close)
    b = s.loc["2026-10-15"].copy()
    ov = overnight_asof(m, "2026-10-14T21:26:41")
    for k in ("SOX", "NDX", "SPX", "TSM", "TXF_NIGHT", "USDTWD_5d"):
        b[k] = ov.get(k, (float("nan"), None))[0]
    vb = L.votes(pd.DataFrame([b]))
    for name, row, vv in (("T=2026-10-14 07:00", s.loc["2026-10-14"], v.loc["2026-10-14"]),
                          ("paper run 2026-10-14 21:26 for T=10/15", b, vb.iloc[0]),
                          ("T=2026-10-15 07:00", s.loc["2026-10-15"], v.loc["2026-10-15"])):
        res["decision_points"][name] = {
            "signals": {k: (None if pd.isna(row[k]) else round(float(row[k]), 4)) for k in
                        ("breadth", "ew_trend20", "ew_dd60", "ew_vol20", "SOX", "NDX", "SPX", "TSM", "TXF_NIGHT", "USDTWD_5d")},
            "votes_on": [k for k in L.VOTES if bool(vv[k])], "n_votes": int(vv["n_votes"])}
    res["decision_points"]["paper run 2026-10-14 21:26 for T=10/15"]["overnight_used"] = {k: x[1] for k, x in ov.items()}
    res["states"] = {d: S.loc[d].to_dict() for d in ("2026-10-14", "2026-10-15", "2026-10-16")}
    # counterfactual: paper portfolio at 10/14 close, overlay acts at 10/15 VWAP (decision 10/15 07:00)
    led = json.loads((ROOT / "data" / "paper_ledger" / "settlement" / "2026-10-14.json").read_text(encoding="utf-8"))
    nav, cash = float(led["nav"]), float(led["cash"])
    px = store.load("daily_prices")
    p14 = px[px.date == "2026-10-14"].set_index("ticker")
    p15 = px[px.date == "2026-10-15"].set_index("ticker")
    h = {t: int(sh) for t, sh in led["holdings"].items() if int(sh) > 0}
    w = {t: sh * float(p14.loc[t, "close"]) / nav for t, sh in h.items()}
    inv = sum(w.values())
    fs_vol = None
    try:
        from agent.pipeline import cached_features
        fs = cached_features(store, "2026-10-15T07:00:00+08:00", "2026-10-15", sorted(load_rulebook().universe))[0]
        vol = fs.features["volatility_20d"].dropna()
        fs_vol = set(vol[vol >= vol.quantile(0.80)].index)
        reg = fs.market.get("breadth_above_ma20")
    except Exception:  # noqa: BLE001
        reg = None
    v1_lo, v1_hi = 0.03, 0.07          # v1 regime on 10/15 = risk_on (prediction file) -> cash range 3-7%
    base_ret = sum(w[t] * (float(p15.loc[t, "close"]) / float(p14.loc[t, "close"]) - 1) for t in w)
    cf = {}
    for cand, (act_name, trig) in L.CANDIDATES.items():
        st = S.loc["2026-10-15", trig]
        act = L.ACTIONS[act_name]
        out = {"state_at_10_15_0700": st, "state_at_10_14_0700": S.loc["2026-10-14", trig]}
        if st == "NORMAL" or not act[st]["cash"]:
            out.update(sold_nav=0.0, saved_nav=0.0, day_return=base_ret)
            cf[cand] = out
            continue
        spec = act[st]
        lo, hi = max(spec["cash"][0], v1_lo), min(max(spec["cash"][1], v1_hi), 0.19)
        mid = (lo + hi) / 2
        tgt = dict(w)
        trimmed = 0.0
        if spec["vol_cap"] and fs_vol:
            for t in fs_vol & set(tgt):
                if tgt[t] > spec["vol_cap"] + 0.002:
                    trimmed += tgt[t] - spec["vol_cap"]
                    tgt[t] = spec["vol_cap"]
        amt = min(inv - trimmed - (1 - mid), act["max_delever"] - trimmed)
        names = sorted(tgt, key=lambda t: -tgt[t])[:max(1, int(amt / 0.0025))]
        tot = sum(tgt[t] for t in names)
        for t in names:
            tgt[t] -= amt * tgt[t] / tot
        saved, sold = 0.0, 0.0
        for t in w:
            d = w[t] - tgt[t]
            if d > 0.002:
                vw, cl = float(p15.loc[t, "vwap"]), float(p15.loc[t, "close"])
                # sold at 10/15 VWAP instead of being marked at 10/15 close; value fraction measured at 10/14 close
                frac = d * float(p15.loc[t, "vwap"]) / float(p14.loc[t, "close"])
                saved += frac * (1 - cl / vw) - frac * float(rules.sell_fee_rate + rules.transaction_tax_rate)
                sold += frac
        out.update(target_cash=[lo, hi], sold_nav=sold, vol_cap_trim_nav=trimmed, saved_nav=saved,
                   day_return=base_ret + saved, saved_twd=saved * nav)
        cf[cand] = out
    res["paper_portfolio"] = {"nav_10_14": nav, "cash_ratio_10_14": cash / nav, "holdings": len(h),
                              "actual_return_10_15": float(json.loads((ROOT / "data" / "paper_ledger" / "settlement" /
                                                                      "2026-10-15.json").read_text(encoding="utf-8"))["nav"]) / nav - 1,
                              "recomputed_return_10_15": base_ret,
                              "gap_close14_to_vwap15": sum(w[t] * (float(p15.loc[t, "vwap"]) / float(p14.loc[t, "close"]) - 1) for t in w),
                              "vwap15_to_close15": sum(w[t] * float(p15.loc[t, "vwap"]) / float(p14.loc[t, "close"]) *
                                                       (float(p15.loc[t, "close"]) / float(p15.loc[t, "vwap"]) - 1) for t in w)}
    res["counterfactual_10_15"] = cf
    # non-PIT upper bound: had the 10/14 entry already held the A / C cash level
    res["non_pit_upper_bound"] = {f"cash_{c:.0%}_at_entry": (c - cash / nav) * (-base_ret / inv) for c in (0.14, 0.17)}
    (HERE / "results" / "case_1015.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
