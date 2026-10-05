"""ETF refresh: sequential vs small parallel (Round 06). Live network; issuer sites are hit twice (60 requests
total + retries), concurrency <= 4. Compares duration, errors, retry/fallback status and DATA EQUALITY.

  python agent\\ops\\etf_parallel_test.py [--workers 4]      -> reports/round06_etf_parallel.json
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT  # noqa: E402
from agent.data.loaders import HistoryStore  # noqa: E402
from agent.ops.common import Clock, load_ops_config, write_json  # noqa: E402


def _holdings(manifest: Path) -> dict:
    m = json.loads(manifest.read_text(encoding="utf-8"))
    out = {}
    for f in m["files"]:
        if f.get("file"):
            rows = json.loads((manifest.parent / f["file"]).read_text(encoding="utf-8"))
            out[f["etf"]] = {"status": f["status"], "date": f["holdings_date"],
                             "rows": sorted((r["ticker"], round(float(r["weight"]), 8)) for r in rows)}
        else:
            out[f["etf"]] = {"status": f["status"], "date": f.get("holdings_date"), "rows": None}
    return out


def run(workers: int = 4) -> dict:
    from agent.ops.refresh_daily import _fetch_etf
    res = {}
    for label, w in (("sequential", 1), ("parallel", workers)):
        tmp = Path(tempfile.mkdtemp(prefix=f"etf_{label}_"))
        cfg = copy.deepcopy(load_ops_config())
        cfg["paths"]["etf_snapshots_dir"] = str(tmp)
        ctx = {"ops_cfg": cfg, "store": HistoryStore(), "run_date": Clock().now().strftime("%Y-%m-%d"),
               "wall": Clock(), "etf_max_workers": w}
        t = time.perf_counter()
        err = None
        try:
            r = _fetch_etf(ctx)
        except Exception as e:  # noqa: BLE001
            r, err = {"detail": {}}, f"{type(e).__name__}: {e}"
        dt = time.perf_counter() - t
        mf = sorted(tmp.rglob("manifest_*.json"))
        res[label] = {"workers": w, "duration_sec": round(dt, 1), "error": err,
                      "by_status": r["detail"].get("by_status"), "fallback": [x["etf"] for x in r["detail"].get("etfs_fallback", [])],
                      "_holdings": _holdings(mf[-1]) if mf else {}}
    a, b = res["sequential"].pop("_holdings"), res["parallel"].pop("_holdings")
    both = [e for e in a if a[e]["rows"] is not None and b.get(e, {}).get("rows") is not None]
    diff = [e for e in both if (a[e]["date"], a[e]["rows"]) != (b[e]["date"], b[e]["rows"])]
    res["comparison"] = {"etfs_fetched_both": len(both), "data_differences": diff,
                         "speedup": round(res["sequential"]["duration_sec"] / max(res["parallel"]["duration_sec"], 0.1), 2),
                         "status_differences": [e for e in a if a[e]["status"] != b.get(e, {}).get("status")]}
    res["recommendation"] = ("parallel safe on this run (identical data, no extra errors); keep max_workers small"
                             if not diff and not res["parallel"]["error"] and
                             (res["parallel"]["by_status"] or {}).get("STALE_FALLBACK", 0) <=
                             (res["sequential"]["by_status"] or {}).get("STALE_FALLBACK", 0)
                             else "keep sequential (max_workers: 1)")
    write_json(ROOT / "reports" / "round06_etf_parallel.json", res)
    return res


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    print(json.dumps(run(min(a.workers, 5)), indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
