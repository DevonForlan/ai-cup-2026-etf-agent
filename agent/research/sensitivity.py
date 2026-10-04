"""Generate ±10% / ±20% parameter-perturbation variants for candidate strategies.

  python agent\\research\\sensitivity.py --ids HN_rev,HN_full,HN_trend --out reports\\sensitivity_strategies.yaml

Perturbations (each one-at-a-time, deterministic):
  * all non-zero score weights × (1 ± 0.1 / 0.2) with an alternating sign pattern (2 draws per level)
  * target_holdings ±10% / ±20% (rounded, kept inside the official 20–30 band with buffers)
  * cash range (regime cash_by_regime) × 0.8 / × 1.2
  * min_holding_days / rebalance_threshold × 0.8 / × 1.2
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agent.config import load_strategy  # noqa: E402
from agent.research.strategies import registry, resolve  # noqa: E402


def variants(base_cfg: dict, s: dict) -> list[dict]:
    cfg = resolve(base_cfg, s)
    out = []
    w = cfg["score_weights"]
    keys = [k for k, v in w.items() if v]
    for lvl in (0.1, 0.2):
        for draw in (0, 1):
            nw = dict(w)
            for i, k in enumerate(keys):
                sign = 1 if (i + draw) % 2 == 0 else -1
                nw[k] = round(w[k] * (1 + sign * lvl), 6)
            out.append((f"w{'+-' if draw == 0 else '-+'}{int(lvl * 100)}", {"score_weights": nw}))
    t = cfg["strategy_buffers"]["target_holdings"]
    for lvl in (-0.2, -0.1, 0.1, 0.2):
        nt = max(21, min(29, round(t * (1 + lvl))))
        out.append((f"hold{nt}", {"strategy_buffers.target_holdings": nt,
                                  "strategy_buffers.target_holdings_min": max(20, nt - 1),
                                  "strategy_buffers.target_holdings_max": min(30, nt + 2)}))
    for m in (0.8, 1.2):
        cr = {k: [round(v[0] * m, 4), round(min(v[1] * m, 0.2), 4)] for k, v in cfg["regime"]["cash_by_regime"].items()}
        out.append((f"cash{int(m * 100)}", {"regime.cash_by_regime": cr}))
        tv = dict(cfg["turnover"])
        tv["min_holding_days"] = max(1, round(tv.get("min_holding_days", 1) * m))
        tv["rebalance_threshold"] = round(tv.get("rebalance_threshold", 0.015) * m, 4)
        out.append((f"turn{int(m * 100)}", {"turnover": tv}))
    res = []
    for name, ov in out:
        o = copy.deepcopy(s["overrides"])
        o.update(ov)
        res.append({"strategy_id": f"S_{s['strategy_id']}_{name}", "group": "sensitivity",
                    "desc": f"{s['strategy_id']} perturbation {name}", "overrides": o,
                    "parent": s["strategy_id"]})
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", required=True)
    ap.add_argument("--out", default="reports/sensitivity_strategies.yaml")
    a = ap.parse_args(argv)
    base = load_strategy()
    reg = {s["strategy_id"]: s for s in registry()}
    allv = []
    for sid in a.ids.split(","):
        allv += variants(base, reg[sid])
    Path(a.out).write_text(yaml.safe_dump(allv, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(len(allv), "variants ->", a.out)


if __name__ == "__main__":
    main()
