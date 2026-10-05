"""Compare two candidate packages and classify the difference (Round 06).

  python agent\\ops\\compare_candidates.py <package_dir_A> <package_dir_B>

Classes (first match wins):
  DECISION_DIFFERENCE        portfolio / orders / market posture differ  (causes listed: code/config/data/settlement)
  CODE_DIFFERENCE            same decision, different git sha
  CONFIG_DIFFERENCE          same decision, different config hashes
  DATA_DIFFERENCE            same decision, different data snapshot or settlement
  NARRATIVE_ONLY_DIFFERENCE  same decision and inputs, only prose differs
  IDENTICAL_DECISION         same decision, inputs and prose (timestamps / run_id may differ)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.ops.fingerprint import decision_core, narrative_text  # noqa: E402


def load_candidate(pkg: Path) -> dict:
    pkg = Path(pkg)
    meta = json.loads((pkg / "run_metadata.json").read_text(encoding="utf-8"))
    dp = next(pkg.glob("D-Plan_*.json"))
    return {"dir": str(pkg), "meta": meta, "doc": json.loads(dp.read_text(encoding="utf-8")), "file": dp.name}


def _diff_list(a, b, key):
    da = {x[0]: x for x in a}
    db = {x[0]: x for x in b}
    out = []
    for t in sorted(set(da) | set(db)):
        if da.get(t) != db.get(t):
            out.append({key: t, "A": da.get(t), "B": db.get(t)})
    return out


def compare(a_dir: Path, b_dir: Path) -> dict:
    A, B = load_candidate(a_dir), load_candidate(b_dir)
    ca, cb = decision_core(A["doc"]), decision_core(B["doc"])
    ma, mb = A["meta"], B["meta"]
    inputs = {
        "code": (ma.get("git_sha"), mb.get("git_sha")),
        "config": (ma.get("config_hashes"), mb.get("config_hashes")),
        "data": (ma.get("data_snapshot_hash"), mb.get("data_snapshot_hash")),
        "settlement": (ma.get("settlement_hash"), mb.get("settlement_hash")),
    }
    changed = [k for k, (x, y) in inputs.items() if x != y]
    detail = {
        "trade_date": (ca["trade_date"], cb["trade_date"]), "team_id": (ca["team_id"], cb["team_id"]),
        "market_view": None if ca["market_view"] == cb["market_view"] else (ca["market_view"], cb["market_view"]),
        "decisions": _diff_list(ca["decisions"], cb["decisions"], "ticker"),
        "no_trade": _diff_list(ca["no_trade"], cb["no_trade"], "ticker"),
        "orders": _diff_list([[f"{o[0]}:{o[1]}", o[2]] for o in ca["orders"]],
                             [[f"{o[0]}:{o[1]}", o[2]] for o in cb["orders"]], "order"),
        "refs": sorted(set(s["source_id"] for s in A["doc"]["sources"]) ^ set(s["source_id"] for s in B["doc"]["sources"])),
        "fingerprint": (ma.get("decision_fingerprint"), mb.get("decision_fingerprint")),
        "dplan_sha256": (ma.get("dplan_sha256"), mb.get("dplan_sha256")),
    }
    same_decision = ca == cb
    if not same_decision:
        cls = "DECISION_DIFFERENCE"
    elif "code" in changed:
        cls = "CODE_DIFFERENCE"
    elif "config" in changed:
        cls = "CONFIG_DIFFERENCE"
    elif "data" in changed or "settlement" in changed:
        cls = "DATA_DIFFERENCE"
    elif narrative_text(A["doc"]) != narrative_text(B["doc"]):
        cls = "NARRATIVE_ONLY_DIFFERENCE"
    else:
        cls = "IDENTICAL_DECISION"
    reason = None
    if cls == "DECISION_DIFFERENCE":
        reason = ("inputs changed: " + ", ".join(changed)) if changed else \
            "NO input changed -> non-deterministic decision (investigate before submitting)"
    return {"class": cls, "same_decision": same_decision, "inputs_changed": changed, "reason": reason,
            "A": {"dir": A["dir"], "run_id": ma.get("run_id"), "file": A["file"]},
            "B": {"dir": B["dir"], "run_id": mb.get("run_id"), "file": B["file"]},
            "inputs": {k: {"A": x, "B": y} for k, (x, y) in inputs.items()}, "detail": detail}


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    a = ap.parse_args(argv)
    r = compare(Path(a.a), Path(a.b))
    print(f"CLASS: {r['class']}")
    if r["reason"]:
        print(f"REASON: {r['reason']}")
    for k in ("decisions", "no_trade", "orders"):
        for d in r["detail"][k][:30]:
            print(f"  {k}: {d}")
    return 0 if r["class"] != "DECISION_DIFFERENCE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
