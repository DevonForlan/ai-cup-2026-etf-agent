"""Round 06: settlement entry (template / validation / double entry / confirmation gate), submission state
machine + receipts, organizer clarifications, decision fingerprint + idempotency + candidate compare,
FINAL replacement, crash recovery, stale locks, ETF retry / stale fallback, deadline near-miss, rehearsal."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from agent.competition_day import SimulatedCrash, run_competition_day
from agent.ops.common import Clock, sha256_file
from tests.ops.conftest import CLEAN_GIT, enter_official

T1, T2 = "2026-10-26", "2026-10-27"
CLK1, CLK2 = "2026-10-25T20:00:00+08:00", "2026-10-26T20:00:00+08:00"


def run(store, ops_cfg, date, clock, mode="competition", **kw):
    kw.setdefault("skip_refresh", True)
    return run_competition_day(date, "TEAM_TEST", mode, store=store, store_is_fixture=True, ops_cfg=ops_cfg,
                               clock=Clock(clock), git=CLEAN_GIT, archive_readonly=False, **kw)


def subdir(ops_cfg, date):
    return Path(ops_cfg["paths"]["submissions_dir"]) / date.replace("-", "")


# ============================================================================ settlement entry
def _csv(tmp, name, rows):
    p = tmp / name
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return p


GOOD = ["ticker,shares", "2330,17000", "2317,50000", "__DATE__,2026-10-27", "__CASH__,1000000",
        "__NAV__,30000000", "__ACCRUED__,0", "__WARNINGS__,"]


def test_settlement_templates_parse(tmp_path):
    from agent.ops.settlement_entry import parse_file, write_templates
    c, j = write_templates(tmp_path)
    rc, pc = parse_file(c)
    rj, pj = parse_file(j)
    assert not pc and not pj and rc["cash"] == "123456789.00" and dict(rc["rows"]) == {"2330": "17000", "2317": "50000"}
    assert {t: str(v) for t, v in rj["rows"]} == {"2330": "17000", "2317": "50000"}


@pytest.mark.parametrize("bad,needle", [
    (["2330,17000", "2330,1000"], "duplicate ticker 2330"),
    (["9999,1000"], "not in the 150-stock universe"),
    (["2330,-1000"], "negative"),
    (["2330,1000.5"], "not an integer"),
    (["2330,abc"], "not a number"),
    (["23X0,1000"], "bad ticker format"),
])
def test_settlement_entry_rejects_bad_rows(tmp_path, ops_cfg, bad, needle):
    from agent.ops.settlement_entry import import_settlement
    rows = ["ticker,shares"] + bad + GOOD[3:]
    r = import_settlement("2026-10-27", _csv(tmp_path, "a.csv", rows), operator="op", source="src", ops_cfg=ops_cfg,
                          closes={})
    assert r["status"] == "BLOCK" and any(needle in p for p in r["problems"]), r["problems"]
    assert not (Path(ops_cfg["paths"]["settlement_dir"]) / "20261027_official.json").exists()


def test_settlement_entry_cash_nav_date_checks(tmp_path, ops_cfg):
    from agent.ops.settlement_entry import import_settlement
    imp = lambda rows, **kw: import_settlement("2026-10-27", _csv(tmp_path, "x.csv", rows), operator="op",  # noqa: E731
                                               source="src", ops_cfg=ops_cfg, closes=kw.get("closes", {}))
    assert "cash negative" in " ".join(imp(GOOD[:4] + ["__CASH__,-5", "__NAV__,1"])["problems"])
    assert "NAV must be > 0" in " ".join(imp(GOOD[:4] + ["__CASH__,5", "__NAV__,0"])["problems"])
    assert "file date" in " ".join(imp(GOOD[:3] + ["__DATE__,2026-10-26"] + GOOD[4:])["problems"])
    wrong_nav = imp(GOOD, closes={"2330": 1000.0, "2317": 100.0})        # 17M + 5M + 1M = 23M != 30M
    assert any("NAV" in p and "sum(shares x close)" in p for p in wrong_nav["problems"])
    ok = imp(GOOD[:5] + ["__NAV__,23000000", "__ACCRUED__,0", "__WARNINGS__,"], closes={"2330": 1000.0, "2317": 100.0})
    assert ok["status"] == "IMPORTED" and not ok["confirmed"]
    assert "operator is required" in " ".join(import_settlement("2026-10-27", _csv(tmp_path, "y.csv", GOOD),
                                                                 source="s", ops_cfg=ops_cfg, closes={})["problems"])


def test_double_entry_match_and_mismatch(tmp_path, ops_cfg):
    from agent.ops.settlement_entry import confirmation_status, import_settlement
    a = _csv(tmp_path, "A.csv", GOOD)
    b_bad = _csv(tmp_path, "B_bad.csv", GOOD[:1] + ["2330,17000", "2317,5000"] + GOOD[3:])
    r = import_settlement("2026-10-27", a, verify_file=b_bad, operator="op", source="s", ops_cfg=ops_cfg, closes={})
    assert r["status"] == "BLOCK" and "DOUBLE_ENTRY_MISMATCH" in " ".join(r["problems"])
    b = _csv(tmp_path, "B.csv", GOOD)
    r = import_settlement("2026-10-27", a, verify_file=b, operator="op", source="s", confirm=True, ops_cfg=ops_cfg,
                          closes={}, snapshot_ref="shot.png")
    assert r["status"] == "DOUBLE_ENTRY_MATCH"
    conf = json.loads((Path(ops_cfg["paths"]["settlement_dir"]) / "20261027_confirmation.json").read_text(encoding="utf-8"))
    for k in ("entered_at", "source", "operator", "input_file_sha256", "official_snapshot_reference", "notes", "confirmed"):
        assert k in conf
    assert conf["input_file_sha256"] == sha256_file(a) and conf["confirmed"] is True
    assert confirmation_status("2026-10-27", ops_cfg)["confirmed"]
    off = Path(ops_cfg["paths"]["settlement_dir"]) / "20261027_official.json"
    off.write_text(off.read_text(encoding="utf-8").replace("17000", "18000"), encoding="utf-8")
    st = confirmation_status("2026-10-27", ops_cfg)
    assert not st["confirmed"] and "CHANGED" in st["detail"]          # edited after confirmation -> not trusted
    again = import_settlement("2026-10-27", a, verify_file=b, operator="op", source="s", ops_cfg=ops_cfg, closes={})
    assert again["status"] == "BLOCK" and "already exists" in " ".join(again["problems"])


def test_unconfirmed_official_blocks_competition_but_not_dry_run(fixture_store, ops_cfg, rb):
    from agent.ops.settle_internal import settle_day
    run(fixture_store, ops_cfg, T1, CLK1, initial=True)
    st = settle_day(T1, store=fixture_store, ops_cfg=ops_cfg, initial_cash=rb.rules.initial_cash)
    off = {"date": T1, "holdings": st.holdings, "cash": str(st.cash), "nav": str(st.nav), "accrued_dividends": "0",
           "warnings": []}
    enter_official(off, ops_cfg, Path(ops_cfg["paths"]["settlement_dir"]).parent / "e", confirm=False)
    s = run(fixture_store, ops_cfg, T2, CLK2)
    assert s["status"] == "BLOCKED" and "settlement_confirmed" in s["reason"]
    assert run(fixture_store, ops_cfg, T2, CLK2, mode="dry-run")["status"] == "DRY_RUN_OK"


# ============================================================================ submission framework
def test_submission_state_machine_and_receipts(fixture_store, ops_cfg):
    from agent.submission.base import InvalidTransition, OfficialSubmissionUnavailable, get_state, set_state
    from agent.submission.future_api import FutureOfficialAPISubmissionProvider
    from agent.submission.manual import ManualSubmissionProvider
    from agent.submission.receipt import Receipt, record_receipt
    assert get_state(T1, ops_cfg)["state"] == "NOT_READY"
    s = run(fixture_store, ops_cfg, T1, CLK1, initial=True)
    assert s["status"] == "READY_TO_SUBMIT" and s["submission_state"] == "READY_TO_SUBMIT"
    prov = ManualSubmissionProvider(ops_cfg)
    with pytest.raises(OfficialSubmissionUnavailable):
        prov.submit(prov.prepare(T1, "TEAM_TEST"))
    with pytest.raises(OfficialSubmissionUnavailable):
        FutureOfficialAPISubmissionProvider().submit({})
    bad = Receipt(T1, "TEAM_TEST", "sha256:" + "0" * 64, "2026-10-25T20:05:00+08:00", "manual_web", "op A",
                  "R1", "accepted")
    assert record_receipt(bad, ops_cfg)["state"] == "UNKNOWN"         # hash != FINAL -> investigate
    set_state(T1, "READY_TO_SUBMIT", reason="operator re-checked after UNKNOWN", cfg=ops_cfg)
    unver = Receipt(T1, "TEAM_TEST", s["sha256"], "2026-10-25T20:06:00+08:00", "manual_web", "op A")
    assert record_receipt(unver, ops_cfg)["state"] == "SUBMITTED_UNVERIFIED"   # no official confirmation yet
    ok = Receipt(T1, "TEAM_TEST", s["sha256"], "2026-10-25T20:06:00+08:00", "manual_web", "op A", "PLAT-123",
                 "accepted", "receipt_2006.png")
    assert record_receipt(ok, ops_cfg)["state"] == "SUBMISSION_CONFIRMED"
    with pytest.raises(InvalidTransition):
        set_state(T1, "READY_TO_SUBMIT", reason="must not silently go back", cfg=ops_cfg)
    with pytest.raises(ValueError):
        record_receipt(Receipt(T1, "TEAM_TEST", "not-a-hash", "x", "carrier_pigeon", "op"), ops_cfg)
    lines = (subdir(ops_cfg, T1) / "receipts.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3                                                # append-only


def test_dry_run_final_is_never_ready_to_submit(fixture_store, ops_cfg):
    from agent.submission.manual import ManualSubmissionProvider
    run(fixture_store, ops_cfg, T1, CLK1, mode="dry-run", initial=True)
    p = ManualSubmissionProvider(ops_cfg).prepare(T1, "TEAM_TEST")
    assert not p["ok"] and "not for upload" in " ".join(p["problems"]) and p["state"] == "NOT_READY"


def test_receipt_schema_written(tmp_path):
    from agent.submission.receipt import RECEIPT_SCHEMA, write_schema
    p = write_schema(tmp_path / "receipt.schema.json")
    j = json.loads(p.read_text(encoding="utf-8"))
    assert set(j["required"]) >= {"trade_date", "team_id", "dplan_sha256", "submitted_at", "submission_method",
                                  "confirmed_by"}
    assert set(RECEIPT_SCHEMA["properties"]) >= {"official_receipt_id", "official_status", "screenshot_reference", "notes"}


# ============================================================================ organizer clarifications
def test_organizer_clarifications_default_unknown_and_gate(tmp_path):
    from agent.rules import organizer_clarifications as OC
    missing = tmp_path / "none.yaml"
    assert all(e["status"] == "unknown" for e in OC.load(missing).values())
    assert OC.label("NC-1", missing) == "ASSUMPTION" and not OC.is_confirmed("NC-1", missing)
    bad = tmp_path / "bad.yaml"
    bad.write_text("NC-1:\n  status: confirmed\n", encoding="utf-8")
    with pytest.raises(OC.ClarificationError):                            # confirmed needs answer/source/date
        OC.load(bad)
    good = tmp_path / "good.yaml"
    good.write_text("NC-15:\n  status: confirmed\n  answer: first trading day is 10/26\n  source: organizer_email\n"
                    "  effective_date: 2026-10-20\n  affected: [calendar]\n", encoding="utf-8")
    assert OC.is_confirmed("NC-15", good) and OC.label("NC-1", good) == "ASSUMPTION"
    unk = tmp_path / "unk.yaml"
    unk.write_text("NC-99:\n  status: unknown\n", encoding="utf-8")
    with pytest.raises(OC.ClarificationError):
        OC.load(unk)


def test_repo_has_no_confirmed_clarification():
    from agent.rules import organizer_clarifications as OC
    assert all(e["status"] == "unknown" for e in OC.load().values())   # nothing confirmed without an official answer


# ============================================================================ fingerprint / idempotency / compare
def test_idempotent_rerun_same_fingerprint_and_compare(fixture_store, ops_cfg):
    from agent.ops.compare_candidates import compare
    a = run(fixture_store, ops_cfg, T1, CLK1, mode="dry-run", initial=True)
    b = run(fixture_store, ops_cfg, T1, "2026-10-25T20:07:00+08:00", mode="dry-run", initial=True)
    assert a["run_id"] != b["run_id"] and a["decision_fingerprint"] == b["decision_fingerprint"]
    assert b["final_action"] == "KEPT_IDENTICAL" and b["sha256"] == a["sha256"]       # FINAL untouched
    c = compare(Path(a["package"]), Path(b["package"]))
    assert c["class"] == "IDENTICAL_DECISION" and c["same_decision"]


def test_fingerprint_excludes_timestamps_and_prose():
    import copy
    from agent.ops.fingerprint import decision_fingerprint
    doc = {"trade_date": T1, "team_id": "T", "market_view": {"regime": "neutral", "stance": "neutral", "posture": {},
           "logic": "A"}, "decisions": [{"ticker": "2330", "action": "BUY", "target_weight": 0.05, "risk_check": "x"}],
           "no_trade_decisions": [], "orders": [{"ticker": "2330", "side": "BUY", "shares": 1000}],
           "agent_metadata": {"run_started_at": "t1"}}
    kw = dict(strategy_hash="s", data_snapshot_hash="d", settlement_hash="h", code_version="git:x")
    f1 = decision_fingerprint(doc, **kw)
    d2 = copy.deepcopy(doc)
    d2["market_view"]["logic"] = "completely different prose"
    d2["agent_metadata"]["run_started_at"] = "t2"
    d2["decisions"][0]["risk_check"] = "other"
    assert decision_fingerprint(d2, **kw) == f1
    d3 = copy.deepcopy(doc)
    d3["orders"][0]["shares"] = 2000
    assert decision_fingerprint(d3, **kw) != f1
    assert decision_fingerprint(doc, **dict(kw, data_snapshot_hash="other")) != f1


def test_compare_classifies_decision_and_data_difference(fixture_store, ops_cfg, tmp_path):
    import shutil
    from agent.ops.compare_candidates import compare
    a = run(fixture_store, ops_cfg, T1, CLK1, mode="dry-run", initial=True)
    pa = Path(a["package"])
    pb = tmp_path / "B"
    shutil.copytree(pa, pb)
    meta = json.loads((pb / "run_metadata.json").read_text(encoding="utf-8"))
    meta["data_snapshot_hash"] = "sha256:other"
    (pb / "run_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    assert compare(pa, pb)["class"] == "DATA_DIFFERENCE"
    dp = next(pb.glob("D-Plan_*.json"))
    doc = json.loads(dp.read_text(encoding="utf-8"))
    doc["orders"][0]["shares"] += 1000
    dp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    r = compare(pa, pb)
    assert r["class"] == "DECISION_DIFFERENCE" and r["detail"]["orders"] and "data" in r["reason"]
    doc["orders"][0]["shares"] -= 1000
    doc["market_view"]["logic"] = "rewritten"
    dp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    meta["data_snapshot_hash"] = json.loads((pa / "run_metadata.json").read_text(encoding="utf-8"))["data_snapshot_hash"]
    (pb / "run_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    assert compare(pa, pb)["class"] == "NARRATIVE_ONLY_DIFFERENCE"


def test_replace_final_cli_flow(fixture_store, ops_cfg):
    from agent.ops.final import replace_final
    from agent.ops.package_submission import history
    a = run(fixture_store, ops_cfg, T1, CLK1, initial=True)
    b = run(fixture_store, ops_cfg, T1, "2026-10-25T20:30:00+08:00", initial=True)
    assert b["final_action"] == "KEPT_IDENTICAL" and b["final_run_id"] == a["run_id"]
    r = replace_final(T1, "TEAM_TEST", b["run_id"], reason="operator chose later run", operator="op A",
                      ops_cfg=ops_cfg, clock=Clock("2026-10-25T21:00:00+08:00"))
    assert r["ok"] and r["comparison"]["class"] == "IDENTICAL_DECISION"
    late = replace_final(T1, "TEAM_TEST", a["run_id"], reason="x", operator="op A", ops_cfg=ops_cfg,
                         clock=Clock("2026-10-26T09:00:00+08:00"))
    assert not late["ok"] and "past cutoff" in late["reasons"][0]
    ev = [h["event"] for h in history(T1, ops_cfg)]
    assert ev.count("MARKED") == 1 and ev.count("REPLACED") == 1


# ============================================================================ crash recovery
@pytest.mark.parametrize("phase", ["after_refresh", "before_package", "package_mid", "before_archive", "archive_mid"])
def test_crash_recovery(fixture_store, ops_cfg, phase):
    from agent.ops.archive_run import partial_dirs, verify_archive
    from agent.ops.package_submission import active_final, verify_package

    def crash(name):
        if name == phase:
            raise SimulatedCrash(name)
    with pytest.raises(SimulatedCrash):
        run(fixture_store, ops_cfg, T1, CLK1, initial=True, crash_hook=crash)
    fin_before = active_final(T1, ops_cfg)
    s = run(fixture_store, ops_cfg, T1, "2026-10-25T20:05:00+08:00", initial=True)
    assert s["status"] == "READY_TO_SUBMIT", s.get("reason")
    fin = active_final(T1, ops_cfg)
    ffile = subdir(ops_cfg, T1) / "FINAL" / fin["file"]
    assert sha256_file(ffile) == fin["sha256"]                                  # FINAL never corrupted
    if fin_before:                                                              # crash after FINAL: kept, not overwritten
        assert fin["sha256"] == fin_before["sha256"] and s["final_action"] == "KEPT_IDENTICAL"
    cands = [p for p in (subdir(ops_cfg, T1) / "candidates").iterdir() if not p.name.startswith(".")]
    assert all(not verify_package(p) for p in cands)                           # every visible candidate intact
    assert not verify_archive(Path(s["archive"]))
    assert all(p.name.endswith(".partial") for p in partial_dirs(ops_cfg))      # leftovers only as .partial
    assert not (Path(ops_cfg["paths"]["settlement_dir"]) / "20261026_internal.json").exists()  # ledger untouched


def test_crash_during_refresh_leaves_no_outputs(fixture_store, ops_cfg):
    from tests.ops.test_ops_units import _fake
    f = _fake(latest="2026-10-23")

    def boom(ctx):
        raise SimulatedCrash("process killed during refresh")
    f["etf_holdings"] = boom
    with pytest.raises(SimulatedCrash):
        run(fixture_store, ops_cfg, T1, CLK1, initial=True, skip_refresh=False, refresh_fetchers=f)
    assert not subdir(ops_cfg, T1).exists()
    s = run(fixture_store, ops_cfg, T1, "2026-10-25T20:05:00+08:00", initial=True, skip_refresh=False,
            refresh_fetchers=_fake(latest="2026-10-23"))
    assert s["status"] == "READY_TO_SUBMIT"


# ============================================================================ locks
def test_stale_lock_recovery_only_for_dead_owner(tmp_path):
    from agent.data.locks import FileLock, LockTimeout, is_stale, recover_stale
    lock = tmp_path / "manifest.lock"
    audit = tmp_path / "lock_recovery.jsonl"
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    import socket
    lock.write_text(json.dumps({"pid": p.pid, "host": socket.gethostname(), "created_at": "x"}), encoding="utf-8")
    old = time.time() - 600
    os.utime(lock, (old, old))
    assert is_stale(lock, 120)[0]
    with FileLock(lock, timeout=5, stale_after=120, audit_log=audit):
        assert json.loads(lock.read_text(encoding="utf-8"))["pid"] == os.getpid()
    assert not lock.exists() and audit.exists() and "not running" in audit.read_text(encoding="utf-8")
    assert list(tmp_path.glob("manifest.lock.stale-*"))                   # evidence kept, not deleted
    # live owner (this process) -> never recovered, even if old
    lock.write_text(json.dumps({"pid": os.getpid(), "host": socket.gethostname()}), encoding="utf-8")
    os.utime(lock, (old, old))
    assert not recover_stale(lock, 120, audit)
    with pytest.raises(LockTimeout):
        FileLock(lock, timeout=0.3, stale_after=120, audit_log=audit).acquire()
    lock.unlink()
    # young lock of a dead owner -> not yet stale
    lock.write_text(json.dumps({"pid": p.pid, "host": socket.gethostname()}), encoding="utf-8")
    assert not is_stale(lock, 120)[0]


# ============================================================================ ETF retry / fallback
class _R:
    def __init__(self, etf, status, asof=None, rows=None):
        self.etf, self.status, self.asof, self.rows, self.reason = etf, status, asof, rows or [], None


def test_etf_retry_previous_date_and_stale_fallback():
    from agent.ops.refresh_daily import etf_fetch_with_policy
    calls = []

    def fetch(s, etf, qdate=None, save=True):
        calls.append((etf, qdate))
        n = sum(1 for c in calls if c[0] == etf)
        if etf == "A":
            return _R(etf, "ok", "2026-10-02", [{"x": 1}])
        if etf == "B":                                   # empty, then OK on retry
            return _R(etf, "no_data") if n == 1 else _R(etf, "ok", "2026-10-02", [{"x": 1}])
        if etf == "C":                                   # latest empty twice, previous date OK
            return _R(etf, "ok", "2026-10-01", [{"x": 1}]) if qdate else _R(etf, "no_data")
        if etf == "D":                                   # latest-only issuer, empty -> stored fallback
            return _R(etf, "no_history") if qdate else _R(etf, "no_data")
        return _R(etf, "error")
    assert etf_fetch_with_policy(None, "A", fetch, "2026-10-05")[1] == "OK"
    assert etf_fetch_with_policy(None, "B", fetch, "2026-10-05")[1] == "RETRY_OK"
    r, st, att = etf_fetch_with_policy(None, "C", fetch, "2026-10-05")
    assert st == "PREVIOUS_DATE" and r.asof == "2026-10-01"
    r, st, att = etf_fetch_with_policy(None, "D", fetch, "2026-10-05")
    assert r is None and st == "STALE_FALLBACK" and len(att) == 3       # latest, retry, one history probe
    r, st, att = etf_fetch_with_policy(None, "E", fetch, "2026-10-05")
    assert st == "STALE_FALLBACK" and len(att) == 5


def test_etf_refresh_marks_stale_fallback_and_never_fakes_today(fixture_store, ops_cfg):
    from agent.config import load_active_etfs
    from agent.ops.refresh_daily import _fetch_etf
    etfs = [x["etf"] for x in load_active_etfs()]
    empty = set(etfs[:3])

    def fetch(s, etf, qdate=None, save=True):
        if etf in empty:
            return _R(etf, "no_data")
        return _R(etf, "ok", "2026-10-23", [{"date": "2026-10-23", "etf": etf, "ticker": "2330", "weight": 0.1,
                                            "rank": 1, "available_at": "2026-10-23T20:00:00+08:00"}])
    ctx = {"ops_cfg": ops_cfg, "store": fixture_store, "run_date": "2026-10-25", "wall": Clock("2026-10-25T20:00:00+08:00"),
           "etf_fetch_one": fetch, "etf_session": lambda: None, "etf_max_workers": 3}
    r = _fetch_etf(ctx)
    assert r["detail"]["by_status"] == {"OK": 27, "STALE_FALLBACK": 3}
    mf = json.loads(Path(r["detail"]["snapshot_manifest"]).read_text(encoding="utf-8"))
    fb = [f for f in mf["files"] if f["status"] == "STALE_FALLBACK"]
    assert len(fb) == 3 and all(f["file"] is None and f["holdings_date"] != "2026-10-23" for f in fb)


# ============================================================================ deadline near-miss
@pytest.mark.parametrize("hhmm,phase,llm,refresh,final", [
    ("2026-10-25T19:30", "NORMAL", True, "all", True),
    ("2026-10-25T22:00", "NORMAL", True, "all", True),
    ("2026-10-26T02:00", "NORMAL", True, "all", True),
    ("2026-10-26T05:30", "NORMAL", True, "all", True),
    ("2026-10-26T07:00", "NORMAL", True, "all", True),
    ("2026-10-26T08:30", "RESTRICTED", True, "critical", True),
    ("2026-10-26T08:44", "NO_LLM", False, "critical", True),
    ("2026-10-26T08:45", "PACKAGE_ONLY", False, "none", True),
    ("2026-10-26T08:46", "PACKAGE_ONLY", False, "none", True),
    ("2026-10-26T08:51", "PACKAGE_ONLY", False, "none", True),
    ("2026-10-26T08:54", "PACKAGE_ONLY", False, "none", True),
    ("2026-10-26T08:56", "PAST_CUTOFF", False, "none", False),
])
def test_deadline_full_clock(ops_cfg, hhmm, phase, llm, refresh, final):
    from agent.ops import deadline as DL
    s = DL.status(T1, Clock(hhmm + ":00+08:00"), ops_cfg)
    assert s.phase == phase and s.allow_llm == llm
    assert {"all": (True, True), "critical": (True, False), "none": (False, False)}[refresh] == \
        (s.allow_refresh, s.allow_noncritical_refresh)
    assert (s.phase != "PAST_CUTOFF") == final


def test_0856_never_produces_final(fixture_store, ops_cfg):
    s = run(fixture_store, ops_cfg, T1, "2026-10-26T08:56:00+08:00", initial=True)
    assert s["status"] == "LATE_PAST_CUTOFF" and not (subdir(ops_cfg, T1) / "FINAL_CANDIDATE.txt").exists()


def test_clock_skew_check():
    from datetime import timedelta
    from agent.competition_day import clock_skew_check
    from agent.ops.common import load_ops_config
    cfg = load_ops_config()
    now = Clock("2026-10-26T08:00:00+08:00").now()
    assert clock_skew_check(now, now + timedelta(seconds=30), cfg, True).level == "PASS"
    assert clock_skew_check(now, now + timedelta(seconds=300), cfg, True).level == "WARN"
    assert clock_skew_check(now, now + timedelta(seconds=900), cfg, True).level == "BLOCK"
    assert clock_skew_check(now, now + timedelta(seconds=900), cfg, False).level == "WARN"
    assert clock_skew_check(now, None, cfg, True).level == "PASS"


# ============================================================================ operator outputs
def test_operator_summary_last_15_lines_and_reports(fixture_store, ops_cfg):
    from agent.competition_day import operator_summary
    s = run(fixture_store, ops_cfg, T1, CLK1, initial=True)
    tail = "\n".join(operator_summary(s).splitlines()[-15:])
    for needle in (T1, "TEAM_TEST", "READY_TO_SUBMIT", "COMPETITION", s["sha256"], "CUT-OFF", "SUBMISSION"):
        assert needle in tail
    rep = Path(s["operator_report"]).read_text(encoding="utf-8")
    for needle in ("Data health", "Official settlement", "Reconciliation", "Active Share", "Final file", "SHA256",
                   "Deadline", "Submission state"):
        assert needle in rep
    banner = (subdir(ops_cfg, T1) / "FINAL_CANDIDATE.txt").read_text(encoding="utf-8")
    assert f"#####  {T1}  #####  TEAM_TEST" in banner and "CUT-OFF" in banner and "DECISION FP" in banner


def test_short_rehearsal_continuity(fixture_store, tmp_path):
    from agent.ops.rehearsal import rehearse
    s = rehearse(T1, days=3, team_id="TEAM_R", mode="clock-sim", root=tmp_path / "rh", store=fixture_store,
                 git=CLEAN_GIT, store_is_fixture=True, quiet=True)
    assert s["passed"], s
    assert s["criteria"]["settlement_continuity_break"] == 0 and s["criteria"]["operational_pass"] == "3/3"
    import csv
    rows = list(csv.DictReader(open(tmp_path / "rh" / "rehearsal_daily.csv", encoding="utf-8-sig")))
    assert [r["submission_state"] for r in rows] == ["SUBMISSION_CONFIRMED"] * 3
    assert rows[1]["reconciliation"] == "MATCH" and rows[2]["settlement_match"] == "MATCH"


def test_continuity_detects_breaks():
    from decimal import Decimal
    from agent.ops.common import sha256_json
    from agent.ops.rehearsal import continuity_problems
    from agent.sim.models import Settlement
    s = Settlement("2026-10-26", {"2330": 1000}, Decimal(100), Decimal(1100))
    s.agent_state = {"day_index": 1, "entry_date": {"2330": "2026-10-26"}, "last_rebalance_index": 0}
    good = {"date": s.date, "holdings": {"2330": 1000}, "cash": "100", "nav": "1100", "accrued_dividends": "0",
            "agent_state_hash": sha256_json(s.agent_state), "warning_count": 0}
    assert continuity_problems(s, good, None, T2) == []
    assert "holdings break" in continuity_problems(s, dict(good, holdings={}), None, T2)
    assert "cash break" in continuity_problems(s, dict(good, cash="0"), None, T2)
    assert "agent_state break" in continuity_problems(s, dict(good, agent_state_hash="x"), None, T2)
