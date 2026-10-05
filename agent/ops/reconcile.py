"""Internal vs official settlement reconciliation -> MATCH | MINOR_DIFFERENCE | BLOCK.

BLOCK means: do not run the next competition day automatically. A human must confirm which
settlement is right; this module never chooses a side and never overwrites official data.

  python agent\\ops\\reconcile.py --date 2026-10-27
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import D  # noqa: E402
from agent.ops.common import load_ops_config, write_json  # noqa: E402
from agent.ops.settlement import ManualFileSettlementProvider, load_internal, path_for  # noqa: E402

MATCH, MINOR, BLOCK = "MATCH", "MINOR_DIFFERENCE", "BLOCK"


def reconcile(internal: dict, official: dict, cfg: dict | None = None) -> dict:
    """internal / official: {holdings, cash, nav, accrued_dividends, warnings}."""
    rc = (cfg or load_ops_config())["reconciliation"]
    diffs, status = [], MATCH

    def bump(level):
        nonlocal status
        order = [MATCH, MINOR, BLOCK]
        if order.index(level) > order.index(status):
            status = level

    hi = {k: int(v) for k, v in (internal.get("holdings") or {}).items() if int(v)}
    ho = {k: int(v) for k, v in (official.get("holdings") or {}).items() if int(v)}
    for t in sorted(set(hi) | set(ho)):
        if hi.get(t, 0) != ho.get(t, 0):
            diffs.append({"field": "shares", "ticker": t, "internal": hi.get(t, 0), "official": ho.get(t, 0)})
            bump(BLOCK if rc["shares_must_match"] else MINOR)
    dc = abs(D(internal["cash"]) - D(official["cash"]))
    if dc > D(rc["cash_rounding_tolerance_twd"]):
        lvl = MINOR if dc <= D(rc["cash_minor_tolerance_twd"]) else BLOCK
        diffs.append({"field": "cash", "internal": str(internal["cash"]), "official": str(official["cash"]),
                      "abs_diff": str(dc), "level": lvl})
        bump(lvl)
    if official.get("nav") is not None and internal.get("nav") is not None:
        n_o = D(official["nav"])
        rel = abs(D(internal["nav"]) - n_o) / n_o if n_o else Decimal(0)
        if rel > 0:
            lvl = MINOR if rel <= D(rc["nav_minor_tolerance_rel"]) else BLOCK
            if abs(D(internal["nav"]) - n_o) > D(rc["cash_rounding_tolerance_twd"]):
                diffs.append({"field": "nav", "internal": str(internal["nav"]), "official": str(official["nav"]),
                              "rel_diff": float(rel), "level": lvl})
                bump(lvl)
    da = abs(D(internal.get("accrued_dividends") or 0) - D(official.get("accrued_dividends") or 0))
    if da > D(rc["accrued_dividend_tolerance_twd"]):
        diffs.append({"field": "accrued_dividends", "abs_diff": str(da)})
        bump(MINOR)
    wi, wo = sorted(internal.get("warnings") or []), sorted(official.get("warnings") or [])
    if wi != wo:
        diffs.append({"field": "warnings", "internal": wi, "official": wo})
        bump(BLOCK)                      # a warning we did not expect (or vice versa) needs a human
    return {"status": status, "diffs": diffs,
            "action": {"MATCH": "continue", "MINOR_DIFFERENCE": "continue with OFFICIAL figures; review diffs",
                       "BLOCK": "STOP: human must confirm the settlement before the next competition run"}[status]}


def reconcile_date(date: str, cfg: dict | None = None, provider=None) -> dict:
    cfg = cfg or load_ops_config()
    internal = load_internal(date, cfg)
    official = (provider or ManualFileSettlementProvider(cfg)).get(date)
    if internal is None or official is None:
        res = {"status": "UNAVAILABLE", "diffs": [],
               "action": "official or internal settlement missing", "internal": internal is not None,
               "official": official is not None}
    else:
        idict = {"holdings": internal.holdings, "cash": str(internal.cash), "nav": str(internal.nav),
                 "accrued_dividends": str(internal.accrued_dividends), "warnings": [w["rule"] for w in internal.warnings]}
        res = reconcile(idict, official, cfg)
    res["date"] = date
    write_json(path_for(date, "reconciliation", cfg), res)
    return res


def accept_official(date: str, confirmed_by: str, note: str = "", cfg: dict | None = None) -> dict:
    """HUMAN decision after a BLOCK: the official settlement is correct. The internal ledger is replaced by
    official holdings/cash/NAV (agent_state and history kept); the old file is kept as *_superseded_<ts>.json."""
    import shutil
    from datetime import datetime
    from agent.ops.common import TPE
    from agent.ops.settlement import apply_official, save_internal
    if not confirmed_by.strip():
        raise ValueError("confirmed_by is required: this is a human decision")
    cfg = cfg or load_ops_config()
    internal = load_internal(date, cfg)
    official = ManualFileSettlementProvider(cfg).get(date)
    if internal is None or official is None:
        raise RuntimeError("both the internal and the official settlement must exist")
    ts = datetime.now(TPE)
    src = path_for(date, "internal", cfg)
    shutil.copy2(src, src.with_name(src.stem + f"_superseded_{ts:%Y%m%d_%H%M%S}.json"))
    save_internal(apply_official(internal, official), cfg)
    rec = reconcile_date(date, cfg)
    rec.update(human_decision={"accepted": "official", "confirmed_by": confirmed_by, "note": note,
                               "at": ts.isoformat()})
    write_json(path_for(date, "reconciliation", cfg), rec)
    return rec


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="settlement date (the previous trading day)")
    ap.add_argument("--accept-official", action="store_true",
                    help="HUMAN decision: official settlement is correct; replace the internal ledger")
    ap.add_argument("--confirmed-by", default="", help="name of the person making the decision (required)")
    ap.add_argument("--note", default="")
    a = ap.parse_args(argv)
    r = accept_official(a.date, a.confirmed_by, a.note) if a.accept_official else reconcile_date(a.date)
    print(f"RECONCILIATION {a.date}: {r['status']} -> {r['action']}")
    for d in r["diffs"]:
        print("  ", d)
    return 0 if r["status"] in ("MATCH", "MINOR_DIFFERENCE") else 2


if __name__ == "__main__":
    raise SystemExit(main())
