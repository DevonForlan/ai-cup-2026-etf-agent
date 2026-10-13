"""Official DataPack (資料包) import — DataPack 規格書 v4.3 (2026-10-12).

The DataPack is the organiser's settlement of our team after the latest completed trading day
(holdings / cash / nav_tradable / compliance). It is downloaded MANUALLY by the operator from the
participant back office (登入參賽者後台 →「文件繳交」→「下載資料包」); the agent never logs in, never
downloads it and never calls any private endpoint.

    .venv\\Scripts\\python.exe -m agent.ops.datapack --file <downloaded.json> --team-id TEAM_XXX --trade-date T --operator "name"

Import = strict validation -> archived copy (sha256) -> data/settlement/<as_of>_official.json +
<as_of>_confirmation.json (the same files ManualFileSettlementProvider / preflight already use).
The DataPack is a machine-produced official file, so no double entry is needed; it is still refused when
anything does not match (team, trade date, missing settlement, NAV identity).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import D  # noqa: E402
from agent.ops.common import TPE, load_ops_config, sha256_file, sha256_json, write_json, ymd  # noqa: E402
from agent.ops.settlement import normalize_official, path_for, settlement_dir  # noqa: E402

NAV_TOLERANCE = Decimal("1")          # yuan; nav_tradable = cash + Σ shares × close_price (spec §2.4)


def parse_datapack(dp: dict, team_id: str, trade_date: str) -> tuple[dict | None, list[str], list[str], dict]:
    """-> (official settlement dict | None, problems (BLOCK), warnings, info). Never guesses a missing value."""
    probs, warns = [], []
    info = {"as_of_date": dp.get("as_of_date"), "missing": dp.get("missing"),
            "prev_day_orders": dp.get("prev_day_orders"), "compliance": dp.get("compliance"),
            "schema_version": dp.get("schema_version"), "generated_at": dp.get("generated_at")}
    if dp.get("doc_type") != "DataPack":
        probs.append(f"doc_type {dp.get('doc_type')!r} != 'DataPack'")
    if dp.get("team_id") != team_id:
        probs.append(f"team_id {dp.get('team_id')!r} != {team_id!r}")
    if dp.get("trade_date") != trade_date:
        probs.append(f"trade_date {dp.get('trade_date')!r} != {trade_date!r} (download again inside the window)")
    missing = list(dp.get("missing") or [])
    if "prev_settlement" in missing:
        probs.append("missing contains prev_settlement: settlement not produced yet -> download again later")
    if "prev_close" in missing:
        warns.append("missing contains prev_close: cash_ratio_tradable null, some server checks will be 'skipped'")
    acct, hold = dp.get("account"), dp.get("holdings")
    if acct is None or hold is None:
        probs.append("account / holdings is null (null is NOT an empty portfolio)")
    pdo = dp.get("prev_day_orders") or {}
    if pdo.get("outcome") == "voided":
        warns.append(f"previous day's orders VOIDED: {pdo.get('void_reasons')}")
    if pdo.get("excluded_codes"):
        warns.append(f"previous day's excluded codes (no fill): {pdo.get('excluded_codes')}")
    comp = dp.get("compliance") or {}
    if comp.get("violations"):
        warns.append(f"official violations (days, cumulative): {comp.get('violations')}")
    if probs:
        return None, probs, warns, info
    if dp.get("as_of_date") is None:                       # first trading day: account is the true all-cash value
        info["initial_day"] = True
        if hold or Decimal(str(acct.get("holdings_count", 0))) != 0:
            probs.append("as_of_date null but holdings present")
            return None, probs, warns, info
        return None, probs, warns + ["first trading day (as_of_date null): use --initial"], info
    shares = {}
    receivable = {}
    value = Decimal(0)
    for h in hold:
        code = str(h["code"])
        if int(h.get("shares") or 0) > 0:
            shares[code] = int(h["shares"])
            if h.get("close_price") is not None:
                value += D(h["shares"]) * D(h["close_price"])
            else:
                warns.append(f"{code}: close_price null (counted as 0 in nav_tradable by the system)")
        if int(h.get("receivable_shares") or 0) > 0:
            receivable[code] = int(h["receivable_shares"])
    cash, nav = D(acct["cash"]), D(acct["nav_tradable"])
    if abs(cash + value - nav) > NAV_TOLERANCE:
        probs.append(f"nav_tradable {nav} != cash + Σ shares×close {cash + value} (file damaged?)")
    if int(acct.get("holdings_count", len(shares))) != len(shares):
        probs.append(f"holdings_count {acct.get('holdings_count')} != {len(shares)} rows with shares > 0")
    if probs:
        return None, probs, warns, info
    if receivable:
        warns.append(f"receivable (stock dividend) shares, not tradable: {receivable}")
    info["receivable_shares"] = receivable
    off = normalize_official({"date": dp["as_of_date"], "holdings": shares, "cash": str(cash), "nav": str(nav),
                              "accrued_dividends": str(D(acct.get("receivable_cash") or 0)),
                              "warnings": [f"{i.get('check_code')}:{i.get('status')}" for i in
                                           (comp.get("incidents") or []) if i.get("date") == dp["as_of_date"]],
                              "source": f"official DataPack (schema {dp.get('schema_version')}, generated "
                                        f"{dp.get('generated_at')})"})
    return off, probs, warns, info


def import_datapack(file: Path, team_id: str, trade_date: str, operator: str, ops_cfg: dict | None = None,
                    supersede_reason: str | None = None) -> dict:
    ops_cfg = ops_cfg or load_ops_config()
    res = {"file": str(file), "status": "BLOCK", "problems": [], "warnings": []}
    if not operator.strip():
        res["problems"].append("--operator is required")
    try:
        dp = json.loads(Path(file).read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        res["problems"].append(f"unreadable JSON: {e}")
        return res
    off, probs, warns, info = parse_datapack(dp, team_id, trade_date)
    res["problems"] += probs
    res["warnings"] += warns
    res["info"] = info
    if info.get("initial_day") and not probs:
        res["status"] = "INITIAL_DAY"
        return res
    if res["problems"] or off is None:
        return res
    raw_dir = settlement_dir(ops_cfg) / "datapack"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_copy = raw_dir / f"{ymd(trade_date)}_DataPack_{team_id}.json"
    if not raw_copy.exists() or sha256_file(raw_copy) != sha256_file(Path(file)):
        if raw_copy.exists():
            raw_copy.replace(raw_copy.with_name(raw_copy.stem + f"_superseded_{datetime.now(TPE):%Y%m%d_%H%M%S}.json"))
        shutil.copy2(file, raw_copy)
    dst = path_for(off["date"], "official", ops_cfg)
    if dst.exists():
        same = json.loads(dst.read_text(encoding="utf-8"))
        if {k: same.get(k) for k in ("holdings", "cash", "nav")} == {k: off[k] for k in ("holdings", "cash", "nav")}:
            res["warnings"].append(f"{dst.name} already holds the same figures")
        elif not supersede_reason:
            res["problems"].append(f"{dst.name} exists with different figures; pass --supersede-reason (old kept)")
            return res
        dst.replace(dst.with_name(dst.stem + f"_superseded_{datetime.now(TPE):%Y%m%d_%H%M%S}.json"))
    off.update(entered_by=operator, entered_at=datetime.now(TPE).isoformat())
    write_json(dst, off)
    write_json(path_for(off["date"], "confirmation", ops_cfg), {
        "date": off["date"], "entered_at": off["entered_at"], "source": off["source"], "operator": operator,
        "input_file": str(raw_copy), "input_file_sha256": sha256_file(raw_copy), "verify_file": None,
        "double_entry": "NOT_NEEDED_OFFICIAL_DATAPACK", "official_snapshot_reference": str(raw_copy),
        "official_json_sha256": sha256_file(dst),
        "content_hash": sha256_json({k: off[k] for k in ("holdings", "cash", "nav", "accrued_dividends", "warnings")}),
        "warnings": res["warnings"], "datapack": info, "confirmed": True,
        "confirmed_at": datetime.now(TPE).isoformat(), "supersede_reason": supersede_reason})
    res.update(status="IMPORTED", official=str(dst), as_of_date=off["date"], holdings=len(off["holdings"]))
    return res


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Import the official DataPack downloaded from the back office")
    ap.add_argument("--file", required=True)
    ap.add_argument("--team-id", required=True)
    ap.add_argument("--trade-date", required=True, help="the trade date you are about to submit for")
    ap.add_argument("--operator", required=True)
    ap.add_argument("--supersede-reason", default=None)
    a = ap.parse_args(argv)
    r = import_datapack(Path(a.file), a.team_id, a.trade_date, a.operator, supersede_reason=a.supersede_reason)
    print(f"DATAPACK {a.trade_date}: {r['status']}" + (f" as_of {r.get('as_of_date')}" if r.get("as_of_date") else ""))
    for p in r["problems"]:
        print("  BLOCK:", p)
    for w in r["warnings"]:
        print("  WARN :", w)
    return 0 if r["status"] in ("IMPORTED", "INITIAL_DAY") else 2


if __name__ == "__main__":
    raise SystemExit(main())
