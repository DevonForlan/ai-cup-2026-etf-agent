"""RESEARCH ONLY. W1–W5 (Round 03 windows) compatibility runs for the gate-passing candidates."""
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
import run_portfolio_study as R  # noqa: E402

W = {"W1": "2025-10-27", "W2": "2025-03-24", "W3": "2026-04-01", "W4": "2025-02-13", "W5": "2026-08-28"}
CANDS = {"BASE_V1": {}, "F_foreign_5": {"foreign_5": 0.2}, "F_rev_3m_yoy": {"rev_3m_yoy": 0.2},
         "A_REV3M+FOREIGN5": {"rev_3m_yoy": 0.2, "foreign_5": 0.2}}

if __name__ == "__main__":
    jobs = [{"sid": f"W_{k}", "extra": v, "wid": w, "start": s, "period": "W1-W5"} for k, v in CANDS.items()
            for w, s in W.items()]
    with ProcessPoolExecutor(10, initializer=R._init) as ex:
        rows = list(ex.map(R.run_one, jobs))
    d = pd.DataFrame(rows)
    d.to_csv(HERE / "results" / "portfolio_w1w5.csv", index=False)
    print(d.pivot(index="sid", columns="wid", values="ret").mul(100).round(2).to_string())
