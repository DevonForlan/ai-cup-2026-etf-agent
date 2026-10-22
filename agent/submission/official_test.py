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


STAGES = ("file_uploaded", "server_validated", "submitted", "accepted", "rejected")


def map_official_result(result: str, submission_id: str | None = None, official_confirmation: bool = False, *,
                        stage: str | None = None, validation_result: str | None = None,
                        history_entry: str | None = None) -> dict:
    """Observed official UI (Issue #4): upload -> 檢核結果 -> 送出繳交 -> history -> existing internal states
    (agent/submission/status.py). ACCEPTED only with official evidence: a submission id or the verbatim history
    entry. `official_confirmation` (operator says the page looked successful) alone is NOT evidence."""
    if result == "ui_unavailable":
        return {"state": "SUBMISSION_UI_UNAVAILABLE", "why": "official page has no upload function (not an agent failure)"}
    if result == "rejected" or stage == "rejected" or validation_result == "FAIL":
        return {"state": "REJECTED", "why": "official rejection / 檢核結果 FAIL"}
    if result == "accepted" and (submission_id or history_entry):
        return {"state": "ACCEPTED", "why": "official acceptance evidence (submission id / history entry)"}
    if result == "accepted" or stage in ("submitted", "accepted"):
        return {"state": "SUBMITTED", "why": "送出繳交 done; no official acceptance evidence (id / history entry) yet"
                + (" — operator confirmation alone is not evidence" if official_confirmation else "")}
    if stage == "server_validated" and validation_result == "PASS":
        return {"state": "SERVER_VALIDATED", "why": "official 檢核結果 PASS; not submitted yet"}
    return {"state": "FILE_UPLOADED", "why": f"file uploaded; 檢核結果 {validation_result or 'not recorded'}"}


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
                  stage: str | None = None, validation_result: str | None = None, history_entry: str | None = None,
                  server_validated_at: str | None = None, submitted_at: str | None = None,
                  accepted_at: str | None = None, ops_cfg: dict | None = None) -> dict:
    if result not in RESULTS:
        raise ValueError(f"result must be one of {RESULTS}")
    if stage is not None and stage not in STAGES:
        raise ValueError(f"stage must be one of {STAGES}")
    if validation_result not in (None, "PASS", "FAIL", "UNKNOWN"):
        raise ValueError("validation_result must be PASS / FAIL / UNKNOWN")
    for txt in [message or "", submission_id or "", filename or "", history_entry or ""] + list(evidence or []):
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
    m = map_official_result(result, submission_id, official_confirmation, stage=stage,
                            validation_result=validation_result, history_entry=history_entry)
    rec = {"trade_date": trade_date, "recorded_at": datetime.now(TPE).replace(microsecond=0).isoformat(),
           "uploaded_at": uploaded_at or datetime.now(TPE).replace(microsecond=0).isoformat(),
           "server_validated_at": server_validated_at, "submitted_at": submitted_at, "accepted_at": accepted_at,
           "stage": stage, "server_validation_result": validation_result, "history_entry": history_entry,
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


def target_trade_date(now: datetime | None = None) -> str:
    """The trade date whose submission window is open now or opens next: today if it is a trading day and the
    08:55 close has not passed, otherwise the next trading day (official TWSE calendar)."""
    from datetime import date as _date, timedelta
    from agent.ops.datapack import calendar_holidays
    from agent.ops.scheduled_run import is_trading_day
    from agent.ops.submission_window import official_times
    now = now or datetime.now(TPE)
    hol = calendar_holidays()
    _, close_hm = official_times()
    d = now.date()
    if is_trading_day(d, hol) and (now.hour, now.minute) < close_hm:
        return d.isoformat()
    d = d + timedelta(days=1)
    while not is_trading_day(d, hol):
        d += timedelta(days=1)
    return _date.isoformat(d)


def full_local_validation(trade_date: str, team_id: str, final_file: Path, summary: dict | None, ops_cfg: dict,
                          fin: dict | None = None) -> dict:
    """§10 local validation of the sealed-test / competition D-Plan. Every item PASS -> READY_FOR_MANUAL_TEST_UPLOAD."""
    from agent.config import load_official_rules
    from agent.engine.rules import load_rulebook
    c: dict[str, str] = {}
    raw = final_file.read_bytes()
    try:
        doc = json.loads(raw.decode("utf-8"))
        c["json_parse"] = "PASS"
    except ValueError:
        return {"checks": {"json_parse": "FAIL"}, "ok": False}
    lc = _local_checks(doc)
    c.update(schema=lc["schema"], ticker=lc["ticker"], numeric=lc["numeric"])
    c["team_id"] = "PASS" if doc.get("team_id") == team_id else f"FAIL ({doc.get('team_id')})"
    c["trade_date"] = "PASS" if doc.get("trade_date") == trade_date else f"FAIL ({doc.get('trade_date')})"
    pattern = load_official_rules().raw["dplan"]["filename_pattern"].format(team_id=team_id, trade_date=trade_date)
    c["filename"] = "PASS" if final_file.name == pattern else f"FAIL ({final_file.name} != {pattern})"
    limit = int((ops_cfg.get("submission") or {}).get("max_upload_bytes") or 2 * 1024 * 1024)
    c["file_size"] = "PASS" if len(raw) <= limit else f"FAIL ({len(raw)} > {limit} bytes)"
    lot = int(load_rulebook().rules.lot_size)
    c["whole_lot"] = "PASS" if all(int(o.get("shares", 0)) % lot == 0 for o in doc.get("orders", [])) else "FAIL"
    cs = (summary or {}).get("compliance_summary") or {}
    for key, label in (("holdings_20_30", "Holdings 20-30"), ("tsmc_le_25", "2330 <= 25%"),
                       ("other_le_10", "Other stocks <= 10%"), ("cash_lt_25", "Cash < 25%"),
                       ("active_share_ge_15", "Active Share official >= 15%")):
        v = str(cs.get(label, "MISSING"))
        c[key] = "PASS" if v.startswith("PASS") else f"FAIL ({v})"
    fz = ops_cfg["freeze"]
    h = sha256_file(ROOT / fz["strategy_config"])
    h = h if h.startswith("sha256:") else "sha256:" + h
    c["quant_fingerprint"] = "PASS" if h == fz["strategy_sha256"] else "FAIL"
    c["dplan_order_consistency"] = "PASS" if (summary or {}).get("validation") == "PASS" else f"FAIL ({(summary or {}).get('validation')})"
    sha = sha256_file(final_file)
    c["no_manual_override"] = "PASS" if (fin is None or fin.get("sha256") == sha) and \
        ((summary or {}).get("sha256") in (None, sha)) else "FAIL (file changed after generation)"
    return {"checks": c, "ok": all(v == "PASS" for v in c.values()), "sha256": sha, "bytes": len(raw)}


def isolated_ops(trade_date: str, ops_cfg: dict | None = None) -> dict:
    """ops config whose runtime paths live under data/official_test_runs/<ymd>/ (never the paper-run folders)."""
    import copy
    c = copy.deepcopy(ops_cfg or load_ops_config())
    base = ROOT / "data" / "official_test_runs" / ymd(trade_date)
    for k, v in c["paths"].items():
        c["paths"][k] = str(base / Path(v).name)
    return c


def prepare(trade_date: str | None = None, *, now: datetime | None = None, clock=None, ops_cfg: dict | None = None,
            store=None, skip_refresh: bool = False, git: dict | None = None) -> dict:
    """Generate the sealed-test D-Plan with the OFFICIAL Team ID (Quant v1 unchanged, template narrative, initial
    capital — the official test account starts from the initial capital until a test DataPack says otherwise) in
    isolated folders, then run the full §10 local validation and write TEST_SUBMISSION_PACKAGE.*"""
    from agent.competition_day import run_competition_day
    from agent.ops import submission_window as SW
    from agent.ops.common import Clock
    from agent.ops.team import resolve
    ops_cfg = ops_cfg or load_ops_config()
    now = now or (clock.now() if clock else datetime.now(TPE))
    t = trade_date or target_trade_date(now)
    out = {"trade_date": t, "prepared_at": now.replace(microsecond=0).isoformat(), "status": None, "reason": None}
    team = resolve("COMPETITION", ops_cfg)
    if team["status"] != "OK":
        out.update(status="BLOCKED", reason="TEAM_ID_NOT_CONFIGURED")
        return out
    ph = SW.phase(t, now, ops_cfg)
    if ph != "DECISION_OPEN":
        tm = SW.times_for(t, ops_cfg)
        out.update(status="BLOCKED", reason=f"{ph}: the sealed-test D-Plan for {t} can be generated only between "
                                            f"{tm['opens']:%m-%d %H:%M} and {tm['decision_cutoff']:%m-%d %H:%M}")
        return out
    iso = isolated_ops(t, ops_cfg)
    kw = {"store": store} if store is not None else {}
    s = run_competition_day(t, team["team_id"], "dry-run", ops_cfg=iso, clock=clock or Clock(), initial=True,
                            skip_refresh=skip_refresh, archive_readonly=False, write_report=False,
                            **({"git": git} if git else {}), **kw)
    if s.get("status") != "DRY_RUN_OK" or not s.get("final_file"):
        out.update(status="BLOCKED", reason=f"generation {s.get('status')}: {str(s.get('reason'))[:300]}")
        return out
    pkg = package(t, ops_cfg=iso, now=now)
    from agent.ops.package_submission import active_final
    fin = active_final(t, iso)
    f = Path(s["final_file"]) if Path(s["final_file"]).is_absolute() else ROOT / s["final_file"]
    v = full_local_validation(t, team["team_id"], f, s, iso, fin)
    pkg.update(local_validation=v["checks"], local_validation_ok=v["ok"], file_bytes=v.get("bytes"),
               isolated_root=str(ROOT / "data" / "official_test_runs" / ymd(t)), generation_status=s["status"])
    pkg["status"] = "READY_FOR_MANUAL_TEST_UPLOAD" if (v["ok"] and pkg.get("status") == "READY_FOR_MANUAL_TEST_UPLOAD") \
        else ("BLOCKED" if pkg.get("status") != "BLOCKED_TEAM_ID_NOT_CONFIGURED" else pkg["status"])
    d = dirs(t, iso)["reports"]
    write_json(d / "TEST_SUBMISSION_PACKAGE.json", pkg)
    (d / "TEST_SUBMISSION_PACKAGE.md").write_text(_package_md(pkg) + _validation_md(v), encoding="utf-8")
    out.update(status=pkg["status"], package=pkg)
    return out


def _validation_md(v: dict) -> str:
    rows = "\n".join(f"| {k} | {val} |" for k, val in v["checks"].items())
    return f"\n## Local validation（§10）\n\n| check | result |\n|---|---|\n{rows}\n"


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    a0 = sp.add_parser("prepare", help="generate + validate the sealed-test D-Plan (official Team ID, isolated)")
    a0.add_argument("--date", default=None, help="default: the trade date whose window is open now / opens next")
    a0.add_argument("--skip-refresh", action="store_true")
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
    a2.add_argument("--stage", default=None, choices=STAGES, help="furthest official UI stage reached")
    a2.add_argument("--validation-result", default=None, choices=["PASS", "FAIL", "UNKNOWN"], help="official 檢核結果")
    a2.add_argument("--history-entry", default=None, help="verbatim official history row (acceptance evidence)")
    a2.add_argument("--server-validated-at", default=None)
    a2.add_argument("--submitted-at", default=None)
    a2.add_argument("--accepted-at", default=None)
    a3 = sp.add_parser("datapack")
    a3.add_argument("--file", required=True)
    a3.add_argument("--date", required=True)
    a3.add_argument("--team-id", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "prepare":
        r = prepare(a.date, skip_refresh=a.skip_refresh)
    elif a.cmd == "package":
        r = package(a.date)
    elif a.cmd == "record-upload":
        r = record_upload(a.date, a.sha256, a.result, a.message, a.operator, submission_id=a.submission_id,
                          filename=a.filename, evidence=a.evidence, official_confirmation=a.official_confirmation,
                          uploaded_at=a.uploaded_at, stage=a.stage, validation_result=a.validation_result,
                          history_entry=a.history_entry, server_validated_at=a.server_validated_at,
                          submitted_at=a.submitted_at, accepted_at=a.accepted_at)
    else:
        r = datapack(a.file, a.date, a.team_id)
    print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
