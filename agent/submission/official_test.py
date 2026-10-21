"""Official TEST-period (封測) helpers — evidence only. Never logs in, uploads, submits, downloads or reads cookies,
tokens, passwords or any credential; never guesses a URL or API. The organiser clears test data before the
competition, so test artefacts are kept APART from competition artefacts (never data/official_datapack/, never
data/settlement/, never submissions/<T>/receipts.jsonl or the submission state machine).

    .venv\\Scripts\\python.exe -m agent.submission.official_test package --date T
    .venv\\Scripts\\python.exe -m agent.submission.official_test record-upload --date T --sha256 sha256:... ^
        --result accepted|rejected|pending|unknown|ui_unavailable --message "<verbatim official text>" ^
        [--submission-id X] [--filename F] [--evidence screenshot.png] --operator "name"
    .venv\\Scripts\\python.exe -m agent.submission.official_test datapack --file <downloaded.json> --date T [--team-id X]

Folders (config/ops.yaml submission.official_test_*): reports/official_test/<T>/, data/official_test_receipts/<T>/,
data/official_test_datapack/<T>/.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT  # noqa: E402
from agent.ops.common import TPE, load_ops_config, ops_path, sha256_file, write_json, ymd  # noqa: E402

RESULTS = ("accepted", "rejected", "pending", "unknown", "ui_unavailable")
SECRET_PATTERNS = re.compile(r"(set-cookie|cookie\s*[:=]|bearer\s+[a-z0-9._-]{8,}|password\s*[:=]|csrf|sessionid|"
                             r"authorization\s*[:=]|access[_-]?token|refresh[_-]?token)", re.I)


def _dir(key: str, default: str, ops_cfg: dict) -> Path:
    v = (ops_cfg.get("submission") or {}).get(key) or default
    p = Path(v)
    return p if p.is_absolute() else ROOT / p


def dirs(trade_date: str, ops_cfg: dict | None = None) -> dict[str, Path]:
    ops_cfg = ops_cfg or load_ops_config()
    d = ymd(trade_date)
    return {"reports": _dir("official_test_reports_dir", "reports/official_test", ops_cfg) / d,
            "receipts": _dir("official_test_receipts_dir", "data/official_test_receipts", ops_cfg) / d,
            "datapack": _dir("official_test_datapack_dir", "data/official_test_datapack", ops_cfg) / d}


def map_official_result(result: str, submission_id: str | None, official_confirmation: bool = False) -> dict:
    """Official UI / receipt -> existing internal submission state (agent/submission/status.py). Conservative:
    'accepted' becomes ACCEPTED only with an official submission id or an explicit official confirmation; an
    'upload completed' style message without that is only UPLOADED."""
    if result == "accepted" and (submission_id or official_confirmation):
        return {"state": "ACCEPTED", "why": "official acceptance with submission id / explicit confirmation"}
    if result == "accepted":
        return {"state": "UPLOADED", "why": "accepted wording but no submission id / confirmation -> not enough evidence"}
    if result == "rejected":
        return {"state": "REJECTED", "why": "official rejection"}
    if result == "ui_unavailable":
        return {"state": "SUBMISSION_UI_UNAVAILABLE", "why": "official page has no upload function (not an agent failure)"}
    return {"state": "UPLOADED", "why": f"upload done, official status {result}"}


def _local_checks(doc: dict) -> dict:
    import jsonschema
    from agent.config import load_official_rules, load_universe
    schema = json.loads(load_official_rules().schema_path.read_text(encoding="utf-8"))
    errs = [e.message for e in jsonschema.Draft202012Validator(schema).iter_errors(doc)]
    uni = set(load_universe())
    tick = ({d.get("ticker") for d in doc.get("decisions", [])} | {d.get("ticker") for d in doc.get("no_trade_decisions", [])}
            | {o.get("ticker") for o in doc.get("orders", [])})
    bad = sorted(t for t in tick if t and t not in uni)
    w = [float(d.get("target_weight", 0)) for d in doc.get("decisions", [])]
    num = all(0 <= x <= 1 for x in w) and sum(w) <= 1.0000001 and all(int(o.get("shares", 0)) > 0 for o in doc.get("orders", []))
    return {"schema": "PASS" if not errs else "FAIL", "schema_errors": errs[:5], "ticker": "PASS" if not bad else "FAIL",
            "tickers_outside_universe": bad, "numeric": "PASS" if num else "FAIL"}


def package(trade_date: str, ops_cfg: dict | None = None, now: datetime | None = None) -> dict:
    """TEST_SUBMISSION_PACKAGE for a manual test upload. Never fakes an official submission: without a configured
    official Team ID the package is BLOCKED (TEAM_ID_NOT_CONFIGURED) and must not be uploaded."""
    from agent.ops.package_submission import active_final
    from agent.ops.team import resolve
    from agent.submission.status import compute
    ops_cfg = ops_cfg or load_ops_config()
    now = now or datetime.now(TPE)
    out_dir = dirs(trade_date, ops_cfg)["reports"]
    fin = active_final(trade_date, ops_cfg)
    team = resolve("COMPETITION", ops_cfg)
    fz = ops_cfg["freeze"]
    strat = sha256_file(ROOT / fz["strategy_config"])
    strat = strat if strat.startswith("sha256:") else "sha256:" + strat
    rec = {"trade_date": trade_date, "built_at": now.replace(microsecond=0).isoformat(), "label": "TEST_SUBMISSION_PACKAGE",
           "official_team_id": team["team_id"], "team_id_status": team["status"],
           "quant_fingerprint": {"strategy_sha256": strat, "frozen": strat == fz["strategy_sha256"]},
           "official_receipt_format": "PENDING_PORTAL_VALIDATION", "final": None, "local_checks": None,
           "validation_report": None, "submission_status": None, "status": None, "problems": []}
    if fin is None:
        rec.update(status="NOT_GENERATED", problems=["no FINAL D-Plan for this trade date"])
    else:
        day = ops_path(ops_cfg, "submissions_dir") / ymd(trade_date)
        f = day / "FINAL" / fin["file"]
        doc = json.loads(f.read_text(encoding="utf-8"))
        cand = day / "candidates" / fin["run_id"]
        meta = json.loads((cand / "run_metadata.json").read_text(encoding="utf-8")) if (cand / "run_metadata.json").exists() else {}
        vr = cand / "validation_report.json"
        val = json.loads(vr.read_text(encoding="utf-8")) if vr.exists() else {}
        rec["final"] = {"file": str(f), "filename": fin["file"], "sha256": fin["sha256"], "sha256_verified": sha256_file(f) == fin["sha256"],
                        "team_id_in_file": doc.get("team_id"), "trade_date_in_file": doc.get("trade_date"),
                        "schema_version": doc.get("schema_version"), "mode": fin.get("mode"),
                        "generated_at": meta.get("generated_at"), "run_id": fin["run_id"],
                        "orders": len(doc.get("orders", [])), "decisions": len(doc.get("decisions", [])),
                        "no_trade_decisions": len(doc.get("no_trade_decisions", []))}
        rec["validation_report"] = {"path": str(vr), "ok": val.get("ok"), "summary": val.get("summary")}
        rec["local_checks"] = _local_checks(doc)
        rec["submission_status"] = compute(trade_date, now=now, ops_cfg=ops_cfg)["state"]
        p = rec["problems"]
        if team["status"] != "OK":
            p.append("TEAM_ID_NOT_CONFIGURED: official Team ID not set in config/ops.yaml team.competition_team_id")
        elif doc.get("team_id") != team["team_id"]:
            p.append(f"D-Plan team_id {doc.get('team_id')} != official {team['team_id']} (regenerate with the official id)")
        if not rec["final"]["sha256_verified"]:
            p.append("FINAL sha256 does not verify")
        if not rec["quant_fingerprint"]["frozen"]:
            p.append("STOP: Quant v1 fingerprint changed")
        if not val.get("ok") or any(v == "FAIL" for k, v in rec["local_checks"].items() if k in ("schema", "ticker", "numeric")):
            p.append("local validation FAIL")
        rec["status"] = ("BLOCKED_TEAM_ID_NOT_CONFIGURED" if team["status"] != "OK" else
                         "BLOCKED" if p else "READY_FOR_MANUAL_TEST_UPLOAD")
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "TEST_SUBMISSION_PACKAGE.json", rec)
    (out_dir / "TEST_SUBMISSION_PACKAGE.md").write_text(_package_md(rec), encoding="utf-8")
    return rec


def _package_md(r: dict) -> str:
    f = r.get("final") or {}
    lc = r.get("local_checks") or {}
    L = [f"# TEST_SUBMISSION_PACKAGE — {r['trade_date']}", "",
         "> 官方封測用。**只有 status = READY_FOR_MANUAL_TEST_UPLOAD 才可人工上傳。** 本工具不登入、不上傳、不提交。AI 產生內容，需人工審閱。", "",
         f"- **Status**: `{r['status']}`" + (f"（{'; '.join(r['problems'])}）" if r["problems"] else ""),
         f"- Trade date: {r['trade_date']}",
         f"- Official Team ID: {r['official_team_id'] or '-'}（{r['team_id_status']}）",
         f"- FINAL D-Plan: `{f.get('file', '-')}`",
         f"- File name / team in file / date in file: {f.get('filename', '-')} / {f.get('team_id_in_file', '-')} / {f.get('trade_date_in_file', '-')}",
         f"- SHA256: `{f.get('sha256', '-')}`（verified: {f.get('sha256_verified', '-')}）",
         f"- Schema version: {f.get('schema_version', '-')}；mode: {f.get('mode', '-')}；generated_at: {f.get('generated_at', '-')}",
         f"- Validation report: {(r.get('validation_report') or {}).get('ok')}（{(r.get('validation_report') or {}).get('path', '-')}）",
         f"- Local checks: schema {lc.get('schema', '-')}, ticker {lc.get('ticker', '-')}, numeric {lc.get('numeric', '-')}",
         f"- Quant fingerprint: `{r['quant_fingerprint']['strategy_sha256'][:23]}…`（frozen: {r['quant_fingerprint']['frozen']}）",
         f"- Submission status（internal）: {r.get('submission_status') or '-'}",
         f"- Official receipt format: {r['official_receipt_format']}", "",
         "## Upload checklist（人工）", "",
         "- [ ] Status = READY_FOR_MANUAL_TEST_UPLOAD（Team ID 已設定且檔內 team_id 相符）",
         "- [ ] 從 `submissions\\<T>\\FINAL\\` 取檔；檔名 = `D-Plan_<TEAM>_<T>.json`",
         "- [ ] `certutil -hashfile <檔案> SHA256` = 上方 SHA256",
         "- [ ] 後台顯示的交易日 / Team ID 與檔案一致",
         "- [ ] 上傳後**逐字**複製官方回應、截圖存 `data\\official_test_receipts\\<T>\\`",
         "- [ ] `python -m agent.submission.official_test record-upload ...` 記錄結果（不要貼 cookie / token / 密碼）", ""]
    return "\n".join(L)


def record_upload(trade_date: str, sha256: str, result: str, message: str, operator: str, *,
                  submission_id: str | None = None, filename: str | None = None, evidence: list[str] | None = None,
                  official_confirmation: bool = False, uploaded_at: str | None = None,
                  ops_cfg: dict | None = None) -> dict:
    if result not in RESULTS:
        raise ValueError(f"result must be one of {RESULTS}")
    for txt in [message or "", submission_id or "", filename or ""] + list(evidence or []):
        if SECRET_PATTERNS.search(txt):
            raise ValueError("refused: the text looks like a cookie / token / password / session value — never store credentials")
    ops_cfg = ops_cfg or load_ops_config()
    d = dirs(trade_date, ops_cfg)
    d["receipts"].mkdir(parents=True, exist_ok=True)
    pkg_p = d["reports"] / "TEST_SUBMISSION_PACKAGE.json"
    pkg = json.loads(pkg_p.read_text(encoding="utf-8")) if pkg_p.exists() else {}
    want = (pkg.get("final") or {}).get("sha256")
    kept = []
    for e in evidence or []:
        src = Path(e)
        if src.exists() and src.is_file():
            dst = d["receipts"] / src.name
            if src.resolve() != dst.resolve():
                shutil.copy2(src, dst)
            kept.append({"file": str(dst), "sha256": sha256_file(dst)})
        else:
            kept.append({"file": e, "sha256": None, "note": "not found locally"})
    m = map_official_result(result, submission_id, official_confirmation)
    rec = {"trade_date": trade_date, "recorded_at": datetime.now(TPE).replace(microsecond=0).isoformat(),
           "uploaded_at": uploaded_at or datetime.now(TPE).replace(microsecond=0).isoformat(),
           "filename": filename, "sha256": sha256, "package_sha256": want,
           "sha256_matches_package": (want == sha256) if want else None, "official_result": result,
           "official_message": message, "submission_id": submission_id, "evidence": kept, "operator": operator,
           "mapped_internal_state": m["state"], "mapping_reason": m["why"], "environment": "OFFICIAL_TEST"}
    with open(d["receipts"] / "records.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def datapack(file: str, trade_date: str, team_id: str | None = None, ops_cfg: dict | None = None) -> dict:
    """Archive a DOWNLOADED test DataPack (sha256) and inventory/validate it READ-ONLY. Never imports it into the
    competition settlement chain."""
    from agent.ops.datapack import previous_trading_day, validate_official_datapack
    ops_cfg = ops_cfg or load_ops_config()
    src = Path(file)
    d = dirs(trade_date, ops_cfg)["datapack"]
    d.mkdir(parents=True, exist_ok=True)
    h = sha256_file(src)
    dst = d / f"{src.stem}__{h.split(':')[-1][:12]}{src.suffix}"
    if not dst.exists():
        shutil.copy2(src, dst)
    try:
        doc = json.loads(dst.read_text(encoding="utf-8"))
    except ValueError as e:
        doc = None
        parse_error = str(e)
    else:
        parse_error = None

    def keys(x, prefix=""):
        out = []
        if isinstance(x, dict):
            for k, v in x.items():
                out.append(prefix + k)
                out += keys(v, prefix + k + ".")
        elif isinstance(x, list) and x:
            out += keys(x[0], prefix + "[].")
        return out
    team = team_id or (doc or {}).get("team_id") or ""
    v = validate_official_datapack(dst, team, trade_date, previous_trading_day(trade_date)) if doc is not None else None
    rec = {"trade_date": trade_date, "archived": str(dst), "sha256": h, "parse_error": parse_error,
           "doc_type": (doc or {}).get("doc_type"), "schema_version": (doc or {}).get("schema_version"),
           "team_id": (doc or {}).get("team_id"), "as_of_date": (doc or {}).get("as_of_date"),
           "generated_at": (doc or {}).get("generated_at"), "field_inventory": sorted(set(keys(doc))) if doc else [],
           "validation": None if v is None else {k: v.get(k) for k in ("status", "reason", "freshness", "problems", "warnings")},
           "environment": "OFFICIAL_TEST", "imported_into_competition_chain": False}
    write_json(d / f"{dst.stem}__inventory.json", rec)
    return rec


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    a1 = sp.add_parser("package")
    a1.add_argument("--date", required=True)
    a2 = sp.add_parser("record-upload")
    a2.add_argument("--date", required=True)
    a2.add_argument("--sha256", required=True)
    a2.add_argument("--result", required=True, choices=RESULTS)
    a2.add_argument("--message", required=True, help="verbatim official response")
    a2.add_argument("--operator", required=True)
    a2.add_argument("--submission-id", default=None)
    a2.add_argument("--filename", default=None)
    a2.add_argument("--evidence", action="append", default=[])
    a2.add_argument("--official-confirmation", action="store_true",
                    help="the portal explicitly shows the submission as accepted/successful")
    a2.add_argument("--uploaded-at", default=None)
    a3 = sp.add_parser("datapack")
    a3.add_argument("--file", required=True)
    a3.add_argument("--date", required=True)
    a3.add_argument("--team-id", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "package":
        r = package(a.date)
    elif a.cmd == "record-upload":
        r = record_upload(a.date, a.sha256, a.result, a.message, a.operator, submission_id=a.submission_id,
                          filename=a.filename, evidence=a.evidence, official_confirmation=a.official_confirmation,
                          uploaded_at=a.uploaded_at)
    else:
        r = datapack(a.file, a.date, a.team_id)
    print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
