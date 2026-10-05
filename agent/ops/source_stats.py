"""Source reliability dashboard (Round 06) from LIVE refresh evidence only (rehearsal replays excluded).

  python agent\\ops\\source_stats.py [--extra-etf-dir <dir> ...]
  -> reports/source_reliability.csv, reports/round06_etf_reliability.csv

source_reliability.csv: source, criticality, attempts, success, failure, stale, fallback, median_latency,
p95_latency, last_success (one attempt = one refresh run's status for that source; latency = fetch duration).
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT  # noqa: E402
from agent.ops.common import load_ops_config, ops_path  # noqa: E402


def _p95(xs):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(0.95 * len(xs)))] if xs else None


def collect(extra_etf_dirs: list[Path] | None = None) -> tuple[list[dict], list[dict]]:
    cfg = load_ops_config()
    logs = ops_path(cfg, "ops_logs_dir")
    agg: dict[str, dict] = {}
    runs = []
    for d in sorted(x for x in logs.glob("*") if x.is_dir()):
        h = d / "data_health_history.jsonl"
        if h.exists():
            runs += [json.loads(x) for x in h.read_text(encoding="utf-8").splitlines() if x.strip()]
        elif (d / "data_health.json").exists():                 # Round 05 runs (no history file)
            runs.append(json.loads((d / "data_health.json").read_text(encoding="utf-8")))
    for j in runs:
        for s in j["sources"]:
            if s["status"] == "SKIPPED" or (s.get("detail") or {}).get("mode") == "replay-store":
                continue
            if "offline mode" in (s.get("error") or ""):        # simulated network-down drill, not a live attempt
                continue
            a = agg.setdefault(s["source"], {"source": s["source"], "criticality": s["criticality"], "attempts": 0,
                                             "success": 0, "failure": 0, "stale": 0, "fallback": 0, "_lat": [],
                                             "last_success": None})
            a["attempts"] += 1
            a["_lat"].append(float(s.get("duration") or 0))
            if s["status"] == "OK":
                a["success"] += 1
                a["last_success"] = max(a["last_success"] or "", s.get("fetched_at") or "")
            elif s["status"] == "STALE":
                a["stale"] += 1
            elif s["status"] == "CACHED":
                a["fallback"] += 1
            else:
                a["failure"] += 1
            if (s.get("detail") or {}).get("by_status", {}).get("STALE_FALLBACK"):
                a["fallback"] += 1
    rows = []
    for a in agg.values():
        lat = a.pop("_lat")
        rows.append(dict(a, median_latency=round(statistics.median(lat), 2) if lat else None,
                         p95_latency=round(_p95(lat), 2) if lat else None))
    etf: dict[str, dict] = {}
    dirs = [ops_path(cfg, "etf_snapshots_dir")] + list(extra_etf_dirs or [])
    for d in dirs:
        for m in sorted(Path(d).rglob("manifest_*.json")):
            j = json.loads(m.read_text(encoding="utf-8"))
            for f in j["files"]:
                st = f.get("status", "OK")
                e = etf.setdefault(f["etf"], {"etf": f["etf"], "attempts": 0, "ok": 0, "retry_ok": 0,
                                              "previous_date": 0, "stale_fallback": 0, "last_holdings_date": None})
                e["attempts"] += 1
                e[{"OK": "ok", "RETRY_OK": "retry_ok", "PREVIOUS_DATE": "previous_date"}.get(st, "stale_fallback")] += 1
                if f.get("holdings_date"):
                    e["last_holdings_date"] = max(e["last_holdings_date"] or "", f["holdings_date"])
    return sorted(rows, key=lambda r: r["source"]), sorted(etf.values(), key=lambda r: r["etf"])


def write(rows, etf_rows) -> tuple[Path, Path]:
    out1, out2 = ROOT / "reports" / "source_reliability.csv", ROOT / "reports" / "round06_etf_reliability.csv"
    cols = ["source", "criticality", "attempts", "success", "failure", "stale", "fallback", "median_latency",
            "p95_latency", "last_success"]
    with open(out1, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    with open(out2, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["etf", "attempts", "ok", "retry_ok", "previous_date", "stale_fallback",
                                          "last_holdings_date"])
        w.writeheader()
        w.writerows(etf_rows)
    return out1, out2


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--extra-etf-dir", action="append", default=[])
    a = ap.parse_args(argv)
    rows, etf = collect([Path(x) for x in a.extra_etf_dir])
    for r in rows:
        print(r)
    print(write(rows, etf))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
