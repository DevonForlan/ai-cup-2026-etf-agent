"""RESEARCH ONLY (Issue #14). Gate R0: the replay engine must reproduce the frozen Quant v1 NAV on NOV23
(|window-return difference| <= 0.30 pp; mean |daily NAV diff| <= 0.10%) before any overlay result is trusted."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
import lab as L  # noqa: E402

MAIN_RUNS = Path(r"C:/Users/devon.tseng/Desktop/個人/AI CUP 2026玉山人工智慧公開挑戰賽/runtime/overlay_bt")


def main() -> int:
    data = L.Data()
    wins = json.loads((L.ROOT / "research" / "factor_research" / "results" / "windows.json").read_text(encoding="utf-8"))
    rows = []
    for w in wins:
        run = L.load_run(MAIN_RUNS / f"BASE_V1__{w['wid']}__c1.0_s0.0")
        rp = L.replay(run["days"], run, data)
        fz = np.array(run["nav"])
        rr = np.array(rp["nav"])
        rows.append({"wid": w["wid"], "period": w["period"], "frozen_ret": fz[-1] / L.INIT - 1, "replay_ret": rr[-1] / L.INIT - 1,
                     "diff_pp": (rr[-1] - fz[-1]) / L.INIT * 100, "mean_abs_daily_diff_pct": float(np.mean(np.abs(rr / fz - 1)) * 100),
                     "violations": rp["violations"]})
    df = pd.DataFrame(rows)
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    df.to_csv(out / "r0_replay_validation.csv", index=False)
    ok = bool((df["diff_pp"].abs() <= 0.30).all() and (df["mean_abs_daily_diff_pct"] <= 0.10).all())
    print(df.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("R0", "PASS" if ok else "FAIL", "max|diff| pp", round(df["diff_pp"].abs().max(), 3),
          "max mean|daily| %", round(df["mean_abs_daily_diff_pct"].max(), 3))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
