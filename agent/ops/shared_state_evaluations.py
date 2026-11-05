"""Issue #33 — publish every completed daily evaluation (NAV / daily / cumulative return, attribution) to Shared State.

Same safe pattern as Issue #31 (`shared_state_sync`): the `shared-state` branch through the dedicated worktree
`<root>/.worktrees/shared-state`; the production checkout is never touched. Downstream observability only: no portfolio,
evaluation, FINAL or submission state is read-write here and a failure never raises.

    shared_state/daily_evaluations/latest.json                 pointer + headline metrics of the newest evaluation
    shared_state/daily_evaluations/<date>/evaluation.json      machine-readable snapshot parsed from the source report
    shared_state/daily_evaluations/<date>/summary.md           concise human summary
    shared_state/daily_evaluations/<date>/superseded/<sha8>/   earlier versions of the same date (audit)

Every value comes from the evaluation report (`reports/daily_evaluations/<date>_evaluation.md`); missing optional fields are
null. Only a COMPLETED evaluation is published (Overall READY, compliance / NAV reconciliation / attribution PASS, a
competition label). `COMPETITION_DAY_ESTIMATE` is an internal close-based estimate and is never labelled official.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from agent.ops import shared_state_sync as S

REL = "shared_state/daily_evaluations"
FIRST_COMPETITION_DATE = "2026-10-27"
ESTIMATE = "COMPETITION_DAY_ESTIMATE"
PUBLISHABLE_TYPES = (ESTIMATE,)           # an official-settlement type does not exist yet; never mislabel an estimate


def _num(s: str | None) -> float | None:
    if s is None:
        return None
    m = re.search(r"[-+]?\d[\d,]*\.?\d*", s)
    return float(m.group(0).replace(",", "")) if m else None


def _kpi(rows: dict, *names: str) -> str | None:
    for k, v in rows.items():
        if any(k.startswith(n) for n in names):
            return v
    return None


def parse_report(text: str) -> dict:
    """Parse the evaluation report. Raises ValueError when it is not a completed competition evaluation."""
    head = re.search(r"^#\s*Daily Evaluation\s*—\s*(\d{4}-\d{2}-\d{2})（([A-Z_]+)）", text, re.M)
    if not head:
        raise ValueError("not an evaluation report")
    date, etype = head.group(1), head.group(2)
    overall = re.search(r"^##\s*Overall:\s*\*\*(\w+)\*\*", text, re.M)
    comp = re.search(r"^##\s*Compliance:\s*\*\*(\w+)\*\*", text, re.M)
    kpi = {m.group(1).strip(): m.group(2).strip() for m in re.finditer(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$", text, re.M)}
    pred = {k: v for k, v in kpi.items() if k in ("Prediction file", "D-Plan file", "Prediction generated", "Starting point", "Execution")}
    rec = {
        "trade_date": date, "evaluation_type": etype,
        "is_official_settlement": False,
        "nav": _num(kpi.get("NAV")),
        "daily_return_pct": _num(kpi.get("Daily return")), "cumulative_return_pct": _num(kpi.get("Cumulative return")),
        "mdd_pct": _num(kpi.get("MDD")), "turnover_pct": _num(kpi.get("Turnover")), "fees": _num(kpi.get("Fees")),
        "tax": _num(kpi.get("Tax")), "cash_weight_pct": _num(kpi.get("Cash weight")), "holdings_count": None,
        "active_share_pct": None, "active_share_vs": None, "compliance": comp.group(1) if comp else None,
        "nav_reconciliation": kpi.get("NAV reconciliation"), "return_attribution_check": kpi.get("Return attribution check"),
        "positive_holding_ratio_pct": _num(_kpi(kpi, "Positive holding ratio")), "overall": overall.group(1) if overall else None,
        "starting_point": pred.get("Starting point"), "execution": pred.get("Execution"),
        "dplan_file": (pred.get("D-Plan file") or "").split("（")[0].strip("` ") or None,
    }
    h = _num(kpi.get("Holdings"))
    rec["holdings_count"] = int(h) if h is not None else None
    asv = _kpi(kpi, "Active Share")
    if asv:
        rec["active_share_pct"] = _num(asv)
        m = re.search(r"（([^）]+)）", asv)
        rec["active_share_vs"] = m.group(1) if m else None
    # holdings table + contributors
    hold = []
    sec = re.search(r"## Holdings result\s*\n(.*?)(?=\n## |\Z)", text, re.S)
    for ln in (sec.group(1).splitlines() if sec else []):
        c = [x.strip() for x in ln.strip().strip("|").split("|")]
        if len(c) == 5 and re.fullmatch(r"\d{4,6}", c[0]):
            hold.append({"ticker": c[0], "name": c[1], "weight_pct": _num(c[2]), "daily_return_pct": _num(c[3]),
                         "contribution_pct": _num(c[4])})
    rec["holdings"] = hold

    def contrib(title):
        m = re.search(rf"## {title}\s*\n(.*?)(?=\n## |\Z)", text, re.S)
        out = []
        for ln in (m.group(1).splitlines() if m else []):
            x = re.match(r"-\s*(\d{4,6})\s+(\S+)\s+([-+]\d+\.?\d*)%", ln.strip())
            if x:
                out.append({"ticker": x.group(1), "name": x.group(2), "contribution_pct": float(x.group(3))})
        return out
    rec["largest_positive_contributors"] = contrib("Largest positive contributors")
    rec["largest_negative_contributors"] = contrib("Largest negative contributors")
    return rec


def is_complete(rec: dict) -> tuple[bool, str]:
    if rec["trade_date"] < FIRST_COMPETITION_DATE:
        return False, "before the competition start (paper run)"
    if rec["evaluation_type"] not in PUBLISHABLE_TYPES:
        return False, f"evaluation type {rec['evaluation_type']} is not a competition evaluation"
    if rec["overall"] != "READY":
        return False, f"overall {rec['overall']}"
    for k in ("compliance", "nav_reconciliation", "return_attribution_check"):
        if rec.get(k) != "PASS":
            return False, f"{k} = {rec.get(k)}"
    if rec["nav"] is None or rec["cumulative_return_pct"] is None or rec["daily_return_pct"] is None:
        return False, "missing NAV / return"
    return True, ""


def _summary_md(rec: dict, meta: dict) -> str:
    f = lambda v, u="": "not available" if v is None else f"{v:,}{u}" if isinstance(v, int) else f"{v}{u}"  # noqa: E731
    asv = "not available" if rec["active_share_pct"] is None else f"{rec['active_share_pct']}%" + (f" (vs {rec['active_share_vs']})" if rec["active_share_vs"] else "")
    rows = [("Trade date", rec["trade_date"]), ("Evaluation type", f"**{rec['evaluation_type']}**"),
            ("NAV (TWD)", f(rec["nav"])), ("Daily return", f(rec["daily_return_pct"], " %")),
            ("Cumulative return", f(rec["cumulative_return_pct"], " %")), ("MDD", f(rec["mdd_pct"], " %")),
            ("Cash weight", f(rec["cash_weight_pct"], " %")), ("Holdings", f(rec["holdings_count"])), ("Active Share", asv),
            ("Compliance", f(rec["compliance"])), ("NAV reconciliation", f(rec["nav_reconciliation"])),
            ("Return attribution check", f(rec["return_attribution_check"])), ("Execution", f(rec["execution"]))]
    cl = lambda xs: "\n".join(f"- {x['ticker']} {x['name']} {x['contribution_pct']:+.3f} %" for x in xs) or "- not available"  # noqa: E731
    return "\n".join([
        f"# Daily evaluation — {rec['trade_date']} ({rec['evaluation_type']})", "",
        "> **COMPETITION_DAY_ESTIMATE is an internal close-based estimate. It is NOT the organiser's official settlement** "
        "(the official figure is the next DataPack). Starting point: " + (rec["starting_point"] or "not available") + ".", "",
        "| Item | Value |", "|---|---|", *[f"| {k} | {v} |" for k, v in rows], "",
        "## Largest positive contributors", cl(rec["largest_positive_contributors"]), "",
        "## Largest negative contributors", cl(rec["largest_negative_contributors"]), "",
        f"Source report `{meta['source_report']}` (sha256 `{meta['source_sha256']}`); synced at {meta['synced_at']}. "
        "AI generated; human review required.", ""])


def _write(wt: Path, rec: dict, meta: dict) -> str:
    base = wt / REL
    ga = wt / ".gitattributes"
    if not ga.is_file():
        ga.write_text("shared_state/** -text" + chr(10), encoding="utf-8", newline=chr(10))
    day = base / rec["trade_date"]
    ep = day / "evaluation.json"
    prev = None
    if ep.is_file():
        try:
            prev = json.loads(ep.read_text(encoding="utf-8"))
        except ValueError:
            prev = None
    if prev and prev.get("source_sha256") == meta["source_sha256"]:
        return "UNCHANGED"
    chain = list(prev.get("supersedes", [])) if prev else []
    if prev:
        arch = day / "superseded" / prev["source_sha256"].replace("sha256:", "")[:8]
        arch.mkdir(parents=True, exist_ok=True)
        (arch / "evaluation.json").write_text(ep.read_text(encoding="utf-8"), encoding="utf-8", newline=chr(10))
        if (day / "summary.md").is_file():
            (arch / "summary.md").write_text((day / "summary.md").read_text(encoding="utf-8"), encoding="utf-8", newline=chr(10))
        chain.append({"source_sha256": prev["source_sha256"], "synced_at": prev.get("synced_at")})
    day.mkdir(parents=True, exist_ok=True)
    doc = {**rec, **meta, "supersedes": chain,
           "idempotency_key": f"{rec['trade_date']}|{meta['source_sha256']}"}
    ep.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + chr(10), encoding="utf-8", newline=chr(10))
    (day / "summary.md").write_text(_summary_md(rec, meta), encoding="utf-8", newline=chr(10))
    lp = base / "latest.json"
    try:
        cur = json.loads(lp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cur = None
    if not cur or cur.get("trade_date", "") <= rec["trade_date"]:
        keys = ("trade_date", "evaluation_type", "is_official_settlement", "nav", "daily_return_pct", "cumulative_return_pct",
                "mdd_pct", "cash_weight_pct", "holdings_count", "active_share_pct", "compliance")
        latest = {k: doc[k] for k in keys}
        latest.update(evaluation_path=f"{REL}/{rec['trade_date']}/evaluation.json", summary_path=f"{REL}/{rec['trade_date']}/summary.md",
                      source_report=meta["source_report"], source_sha256=meta["source_sha256"], synced_at=meta["synced_at"])
        lp.write_text(json.dumps(latest, ensure_ascii=False, indent=1) + chr(10), encoding="utf-8", newline=chr(10))
    return "SUPERSEDED" if prev else "CREATED"


def _pending_path(root: Path) -> Path:
    return root / "logs" / "shared_state" / "pending_evaluations.json"


def _pending(root: Path) -> dict:
    try:
        return json.loads(_pending_path(root).read_text(encoding="utf-8")).get("pending", {})
    except (OSError, ValueError):
        return {}


def _set_pending(root: Path, d: dict) -> None:
    p = _pending_path(root)
    if not d:
        p.unlink(missing_ok=True)
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"updated_at": S._now(), "pending": d}, ensure_ascii=False, indent=1), encoding="utf-8")


def publish(report: Path, root=None, *, push: bool = True) -> dict:
    """Publish one evaluation report. Never raises."""
    root = S._root(root)
    out = {"report": str(report), "status": "SKIPPED", "detail": ""}
    date = None
    try:
        data = Path(report).read_bytes()
        rec = parse_report(data.decode("utf-8"))
        date = rec["trade_date"]
        out["trade_date"] = date
        ok, why = is_complete(rec)
        if not ok:
            out["detail"] = why
            return out
        try:
            src = Path(report).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            src = Path(report).name
        meta = {"source_report": src, "source_sha256": "sha256:" + S._sha(data), "synced_at": S._now()}
        wt = S.ensure_worktree(root)
        action = _write(wt, rec, meta)
        out["action"] = action
        if action != "UNCHANGED":
            S._git(wt, "add", "-A", REL, ".gitattributes")
            if S._git(wt, "diff", "--cached", "--quiet", check=False).returncode != 0:
                S._git(wt, "commit", "-q", "-m", f"shared-state: {date} evaluation {rec['evaluation_type']} NAV {rec['nav']:,.0f} "
                       f"cum {rec['cumulative_return_pct']}%\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>")
        pend = _pending(root)
        if push and (action != "UNCHANGED" or date in pend or "ahead" in S._git(wt, "status", "-sb", check=False).stdout.splitlines()[0]):
            last = ""
            for _ in range(S.PUSH_ATTEMPTS):
                r = S._git(wt, "push", "-u", "origin", S.BRANCH, check=False)
                if r.returncode == 0:
                    break
                last = (r.stderr or r.stdout).strip()[:300]
                S._git(wt, "pull", "--rebase", "origin", S.BRANCH, check=False)
            else:
                raise RuntimeError(f"push failed: {last}")
        out["status"] = "SYNCED" if (action != "UNCHANGED" or date in pend) else "ALREADY_SYNCED"
        pend.pop(date, None)
        _set_pending(root, pend)
    except Exception as e:  # noqa: BLE001  downstream only
        out.update(status="SYNC_PENDING", detail=str(e)[:300])
        if date:
            try:
                pend = _pending(root)
                pend[date] = {"report": str(report), "since": pend.get(date, {}).get("since", S._now()),
                              "last_error": str(e)[:300], "last_try": S._now()}
                _set_pending(root, pend)
            except OSError:
                pass
    return out


def sweep(root=None, *, push: bool = True) -> list[dict]:
    """Publish every completed competition evaluation not yet published (backfill + retry of pending ones)."""
    root = S._root(root)
    res = []
    d = root / "reports" / "daily_evaluations"
    for p in sorted(d.glob("*_evaluation.md")) if d.is_dir() else []:
        if p.name[:10] < FIRST_COMPETITION_DATE:
            continue
        r = publish(p, root, push=push)
        if r["status"] != "SKIPPED":
            res.append(r)
    return res


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Publish completed daily evaluations to the shared-state branch (Issue #33)")
    ap.add_argument("--root", default=None, help="production project root (default: this checkout)")
    ap.add_argument("--report", default=None, help="one report file; default: sweep every completed competition evaluation")
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args(argv)
    res = [publish(Path(a.report), a.root, push=not a.no_push)] if a.report else sweep(a.root, push=not a.no_push)
    for r in res:
        print(json.dumps(r, ensure_ascii=False))
    return 0 if all(r["status"] != "SYNC_PENDING" for r in res) else 1


if __name__ == "__main__":
    raise SystemExit(main())
