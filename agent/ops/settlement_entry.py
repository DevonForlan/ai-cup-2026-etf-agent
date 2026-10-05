"""Safe manual entry of the OFFICIAL settlement (NC-1: the organiser's settlement interface is unknown, so an
operator copies it from the official back office). No GUI, no browser automation, no OCR, no login.

  python agent\\ops\\settlement_entry.py --template                         (write templates\\settlement_official_template.*)
  python agent\\ops\\settlement_entry.py --date 2026-10-27 --file official_A.csv --verify-file official_B.csv ^
         --operator "name" --source "back office 庫存明細 2026-10-27 18:40" --snapshot-ref "screenshot_1840.png" --confirm

Checks (any failure -> BLOCK, nothing is written): trade date, ticker format + 150-stock universe, duplicate
ticker, shares integer >= 0, cash >= 0, NAV > 0, NAV == sum(shares x close) + cash within tolerance (when the
date's closes are in the store), file format. Warnings: shares not a multiple of 1000 (stock dividends, NC-7).
--verify-file: an independent second entry; both must be identical -> DOUBLE_ENTRY_MATCH, else BLOCK.
Writes data/settlement/YYYYMMDD_official.json + YYYYMMDD_confirmation.json. It never touches strategy logic.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date as _date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT, load_universe  # noqa: E402
from agent.ops.common import TPE, load_ops_config, sha256_file, sha256_json, write_json  # noqa: E402
from agent.ops.settlement import normalize_official, path_for  # noqa: E402

SPECIAL = ("__DATE__", "__CASH__", "__NAV__", "__ACCRUED__", "__WARNINGS__")
TICKER_RE = re.compile(r"^\d{4}[0-9A-Z]?$")


class EntryError(ValueError):
    pass


def _dec(x, what: str) -> Decimal:
    try:
        return Decimal(str(x).replace(",", "").strip())
    except (InvalidOperation, AttributeError):
        raise EntryError(f"{what}: not a number: {x!r}")


def parse_file(path: Path) -> tuple[dict, list[str]]:
    """-> (raw dict {date?, holdings{t: shares-str}, cash, nav, accrued, warnings}, format problems)."""
    path = Path(path)
    probs: list[str] = []
    if not path.exists():
        return {}, [f"file not found: {path}"]
    if path.suffix.lower() == ".json":
        try:
            d = json.loads(path.read_text(encoding="utf-8-sig"))
        except ValueError as e:
            return {}, [f"invalid JSON: {e}"]
        h = d.get("holdings")
        if isinstance(h, list):                      # also accept [{"ticker":..,"shares":..}]
            raw = [(str(x.get("ticker")), x.get("shares")) for x in h]
        elif isinstance(h, dict):
            raw = [(str(k), v) for k, v in h.items()]
        else:
            return {}, ["holdings missing"]
        return {"date": d.get("date"), "rows": raw, "cash": d.get("cash"), "nav": d.get("nav"),
                "accrued": d.get("accrued_dividends", 0), "warnings": d.get("warnings") or []}, probs
    out = {"date": None, "rows": [], "cash": None, "nav": None, "accrued": 0, "warnings": []}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for i, row in enumerate(csv.reader(f), 1):
            if not row or not "".join(row).strip() or row[0].strip().startswith("#"):
                continue
            k = row[0].strip()
            if k.lower() == "ticker":
                continue
            if len(row) < 2:
                probs.append(f"line {i}: expected 2 columns")
                continue
            v = row[1].strip()
            if k == "__DATE__":
                out["date"] = v
            elif k == "__CASH__":
                out["cash"] = v
            elif k == "__NAV__":
                out["nav"] = v
            elif k == "__ACCRUED__":
                out["accrued"] = v or 0
            elif k == "__WARNINGS__":
                out["warnings"] = [w.strip() for w in v.split(";") if w.strip()]
            elif k.startswith("__"):
                probs.append(f"line {i}: unknown special row {k}")
            else:
                out["rows"].append((k, v))
    return out, probs


def validate(raw: dict, trade_date: str, *, ops_cfg: dict | None = None, closes: dict | None = None
             ) -> tuple[dict | None, list[str], list[str]]:
    """-> (normalized official dict | None, BLOCK problems, warnings)."""
    ops_cfg = ops_cfg or load_ops_config()
    tol = Decimal(str((ops_cfg.get("settlement_entry") or {}).get("nav_tolerance_rel", 0.0005)))
    probs, warns = [], []
    try:
        d0 = _date.fromisoformat(trade_date)
        if d0.weekday() >= 5:
            probs.append(f"trade date {trade_date} is a weekend")
    except ValueError:
        probs.append(f"invalid trade date {trade_date!r}")
    if raw.get("date") and raw["date"] != trade_date:
        probs.append(f"file date {raw['date']} != --date {trade_date}")
    uni = set(load_universe())
    holdings: dict[str, int] = {}
    for t, v in raw.get("rows", []):
        if not TICKER_RE.match(t):
            probs.append(f"bad ticker format {t!r}")
            continue
        if t not in uni:
            probs.append(f"{t} not in the 150-stock universe")
        if t in holdings:
            probs.append(f"duplicate ticker {t}")
            continue
        try:
            x = _dec(v, f"shares of {t}")
        except EntryError as e:
            probs.append(str(e))
            continue
        if x != x.to_integral_value():
            probs.append(f"shares of {t} not an integer: {v}")
            continue
        if x < 0:
            probs.append(f"shares of {t} negative: {v}")
            continue
        holdings[t] = int(x)
        if int(x) % 1000:
            warns.append(f"{t}: {int(x)} shares is not a multiple of 1000 (stock dividend odd lot? NC-7)")
    cash = nav = None
    try:
        cash = _dec(raw.get("cash"), "cash") if raw.get("cash") not in (None, "") else None
        if cash is None:
            probs.append("cash missing (__CASH__)")
        elif cash < 0:
            probs.append(f"cash negative: {cash}")
    except EntryError as e:
        probs.append(str(e))
    try:
        nav = _dec(raw.get("nav"), "nav") if raw.get("nav") not in (None, "") else None
        if nav is None:
            probs.append("NAV missing (__NAV__)")
        elif nav <= 0:
            probs.append(f"NAV must be > 0: {nav}")
    except EntryError as e:
        probs.append(str(e))
    try:
        accrued = _dec(raw.get("accrued") or 0, "accrued")
    except EntryError as e:
        probs.append(str(e))
        accrued = Decimal(0)
    if not holdings and not probs:
        warns.append("no holdings (all cash) - correct only for an all-cash day")
    if closes and cash is not None and nav and holdings:
        missing = [t for t in holdings if t not in closes]
        if missing:
            warns.append(f"no close in store for {missing}: NAV sum check skipped")
        else:
            calc = sum(Decimal(s) * Decimal(str(closes[t])) for t, s in holdings.items()) + cash
            rel = abs(calc - nav) / nav
            if rel > tol:
                probs.append(f"NAV {nav:,.2f} != sum(shares x close) + cash = {calc:,.2f} (diff {float(rel):.4%} > {float(tol):.4%})")
    elif not closes:
        warns.append("closes for this date not in store: NAV sum check skipped")
    if probs:
        return None, probs, warns
    return normalize_official({"date": trade_date, "holdings": holdings, "cash": str(cash), "nav": str(nav),
                               "accrued_dividends": str(accrued), "warnings": raw.get("warnings") or []}), probs, warns


def store_closes(trade_date: str) -> dict:
    from agent.data.loaders import HistoryStore
    p = HistoryStore().load("daily_prices")
    p = p[p["date"] == trade_date]
    return {r.ticker: float(r.close) for r in p.itertuples() if r.close == r.close}


def import_settlement(trade_date: str, file: Path, *, verify_file: Path | None = None, operator: str = "",
                      source: str = "", snapshot_ref: str | None = None, notes: str = "", confirm: bool = False,
                      supersede_reason: str | None = None, ops_cfg: dict | None = None,
                      closes: dict | None = None) -> dict:
    ops_cfg = ops_cfg or load_ops_config()
    res = {"date": trade_date, "file": str(file), "status": "BLOCK", "problems": [], "warnings": []}
    if not operator.strip():
        res["problems"].append("--operator is required")
    if not source.strip():
        res["problems"].append("--source is required (where the figures were copied from)")
    raw, fprobs = parse_file(file)
    res["problems"] += fprobs
    closes = closes if closes is not None else store_closes(trade_date)
    off, vprobs, warns = validate(raw, trade_date, ops_cfg=ops_cfg, closes=closes) if raw else (None, [], [])
    res["problems"] += vprobs
    res["warnings"] += warns
    if verify_file is not None:
        raw2, f2 = parse_file(verify_file)
        off2, v2, _ = validate(raw2, trade_date, ops_cfg=ops_cfg, closes=closes) if raw2 else (None, [], [])
        if f2 or v2 or off2 is None:
            res["problems"] += [f"verify file: {x}" for x in (f2 + v2 or ["unreadable"])]
        elif off is not None:
            a = {k: off[k] for k in ("holdings", "cash", "nav", "accrued_dividends", "warnings")}
            b = {k: off2[k] for k in ("holdings", "cash", "nav", "accrued_dividends", "warnings")}
            if a != b:
                diffs = [t for t in sorted(set(a["holdings"]) | set(b["holdings"]))
                         if a["holdings"].get(t) != b["holdings"].get(t)]
                diffs += [k for k in ("cash", "nav", "accrued_dividends", "warnings") if a[k] != b[k]]
                res["problems"].append(f"DOUBLE_ENTRY_MISMATCH: {diffs[:20]}")
            else:
                res["double_entry"] = "DOUBLE_ENTRY_MATCH"
    dst = path_for(trade_date, "official", ops_cfg)
    if dst.exists() and not res["problems"]:
        if not supersede_reason:
            res["problems"].append(f"{dst.name} already exists; pass --supersede-reason to replace it (old file kept)")
        else:
            dst.replace(dst.with_name(dst.stem + f"_superseded_{datetime.now(TPE):%Y%m%d_%H%M%S}.json"))
    if res["problems"]:
        return res
    off.update(source=source, entered_by=operator, entered_at=datetime.now(TPE).isoformat())
    write_json(dst, off)
    conf = {"date": trade_date, "entered_at": off["entered_at"], "source": source, "operator": operator,
            "input_file": str(file), "input_file_sha256": sha256_file(Path(file)),
            "verify_file": str(verify_file) if verify_file else None,
            "verify_file_sha256": sha256_file(Path(verify_file)) if verify_file else None,
            "double_entry": res.get("double_entry", "NOT_PERFORMED"),
            "official_snapshot_reference": snapshot_ref, "notes": notes,
            "official_json_sha256": sha256_file(dst), "content_hash": sha256_json(
                {k: off[k] for k in ("holdings", "cash", "nav", "accrued_dividends", "warnings")}),
            "warnings": warns, "confirmed": bool(confirm),
            "confirmed_at": datetime.now(TPE).isoformat() if confirm else None,
            "supersede_reason": supersede_reason}
    write_json(path_for(trade_date, "confirmation", ops_cfg), conf)
    res.update(status="DOUBLE_ENTRY_MATCH" if res.get("double_entry") else "IMPORTED", official=str(dst),
               confirmed=bool(confirm))
    return res


def confirmation_status(trade_date: str, ops_cfg: dict | None = None) -> dict:
    """For preflight: is the manual official settlement of trade_date confirmed and unchanged since?"""
    ops_cfg = ops_cfg or load_ops_config()
    off, conf = path_for(trade_date, "official", ops_cfg), path_for(trade_date, "confirmation", ops_cfg)
    if not off.exists():
        return {"official": False, "confirmed": False, "detail": "no official settlement file"}
    if not conf.exists():
        return {"official": True, "confirmed": False, "detail": "no confirmation record (use settlement_entry.py)"}
    c = json.loads(conf.read_text(encoding="utf-8"))
    same = c.get("official_json_sha256") == sha256_file(off)
    return {"official": True, "confirmed": bool(c.get("confirmed")) and same, "unchanged": same,
            "double_entry": c.get("double_entry"), "operator": c.get("operator"),
            "detail": ("confirmed" if c.get("confirmed") else "NOT confirmed") +
                      ("" if same else "; official file CHANGED after confirmation")}


def write_templates(out: Path | None = None) -> list[Path]:
    out = out or ROOT / "templates"
    out.mkdir(parents=True, exist_ok=True)
    c = out / "settlement_official_template.csv"
    c.write_text("# Official settlement copied from the organiser's back office. One row per holding.\n"
                 "# shares = integer number of shares (not lots). Special rows at the end; __WARNINGS__ = rule ids\n"
                 "# separated by ';' (empty if none). Enter twice (A and B files) and use --verify-file.\n"
                 "ticker,shares\n2330,17000\n2317,50000\n"
                 "__DATE__,2026-10-27\n__CASH__,123456789.00\n__NAV__,1000000000.00\n__ACCRUED__,0\n__WARNINGS__,\n",
                 encoding="utf-8")
    j = out / "settlement_official_template.json"
    write_json(j, {"date": "2026-10-27", "holdings": {"2330": 17000, "2317": 50000}, "cash": "123456789.00",
                   "nav": "1000000000.00", "accrued_dividends": "0", "warnings": []})
    return [c, j]


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", action="store_true")
    ap.add_argument("--date")
    ap.add_argument("--file")
    ap.add_argument("--verify-file", default=None, help="independent second entry (double-entry check)")
    ap.add_argument("--operator", default="")
    ap.add_argument("--source", default="")
    ap.add_argument("--snapshot-ref", default=None, help="screenshot / printout reference of the official screen")
    ap.add_argument("--notes", default="")
    ap.add_argument("--confirm", action="store_true", help="operator confirms the figures match the official screen")
    ap.add_argument("--supersede-reason", default=None)
    ap.add_argument("--status", action="store_true", help="show confirmation status for --date")
    a = ap.parse_args(argv)
    if a.template:
        for p in write_templates():
            print("template:", p)
        return 0
    if a.status:
        print(json.dumps(confirmation_status(a.date), ensure_ascii=False, indent=1))
        return 0
    r = import_settlement(a.date, Path(a.file), verify_file=Path(a.verify_file) if a.verify_file else None,
                          operator=a.operator, source=a.source, snapshot_ref=a.snapshot_ref, notes=a.notes,
                          confirm=a.confirm, supersede_reason=a.supersede_reason)
    print(f"SETTLEMENT ENTRY {a.date}: {r['status']}")
    for p in r["problems"]:
        print("  BLOCK:", p)
    for w in r["warnings"]:
        print("  warn :", w)
    if r["status"] != "BLOCK" and not r.get("confirmed"):
        print("  NOT CONFIRMED: competition runs stay blocked until re-imported with --confirm")
    return 0 if r["status"] != "BLOCK" else 2


if __name__ == "__main__":
    raise SystemExit(main())
