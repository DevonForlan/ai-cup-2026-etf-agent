"""Official test period (封測): receipt rules (last upload vs last successful), conservative official->internal
mapping, credential refusal, isolated evidence folders, TEST_SUBMISSION_PACKAGE, read-only DataPack inventory."""
import json
from datetime import datetime
from pathlib import Path

import pytest

from agent.competition_day import run_competition_day
from agent.ops.common import TPE, Clock, load_ops_config
from agent.submission import official_test as OT
from agent.submission import status as ST
from agent.submission.receipt import OFFICIAL_RECEIPT_FORMAT, Receipt, effective_submission, record_receipt
from tests.ops.conftest import CLEAN_GIT
from tests.ops.test_competition_day import CLK1, T1, run

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "datapack"


@pytest.fixture(autouse=True)
def _release_ops_loggers():
    yield
    import logging
    for name, lg in list(logging.Logger.manager.loggerDict.items()):
        if name.startswith("ops.") and isinstance(lg, logging.Logger):
            for h in list(lg.handlers):
                h.close()
                lg.removeHandler(h)
            del logging.Logger.manager.loggerDict[name]


def at(s):
    return datetime.fromisoformat(s + "+08:00")


@pytest.fixture
def test_cfg(ops_cfg, tmp_path):
    return dict(ops_cfg, submission={"official_test_reports_dir": str(tmp_path / "rep_ot"),
                                     "official_test_receipts_dir": str(tmp_path / "rcpt_ot"),
                                     "official_test_datapack_dir": str(tmp_path / "dp_ot")})


def _rcpt(sha, t, status, rid=None, **kw):
    return Receipt(T1, "TEAM_TEST", sha, f"2026-10-26T{t}:00+08:00", "manual_web", "op", official_receipt_id=rid,
                   official_status=status, **kw)


# ---------------------------------------------------------------- multiple submissions
def test_rejected_after_accepted_never_overwrites_accepted(fixture_store, ops_cfg):
    s = run(fixture_store, ops_cfg, T1, CLK1, initial=True)
    sha = s["sha256"]
    assert record_receipt(_rcpt(sha, "08:05", "accepted", "R-1"), ops_cfg)["state"] == "SUBMISSION_CONFIRMED"
    r = record_receipt(_rcpt(sha, "08:20", "rejected", failure_reason="C6"), ops_cfg)      # used to crash
    assert r["state"] == "SUBMISSION_CONFIRMED" and "stays effective" in r["reason"]
    r = record_receipt(_rcpt(sha, "08:25", "pending"), ops_cfg)
    assert r["state"] == "SUBMISSION_CONFIRMED"
    st = ST.compute(T1, now=at("2026-10-26T08:40:00"), ops_cfg=ops_cfg)
    assert st["state"] == "ACCEPTED" and st["submission_id"] == "R-1"
    assert st["last_upload_status"] == "pending" and st["last_upload_is_effective"] is False and st["uploads_today"] == 3


def test_last_upload_vs_last_successful_submission():
    recs = [{"trade_date": T1, "submitted_at": "2026-10-26T08:00:00+08:00", "official_status": "accepted", "official_receipt_id": "A"},
            {"trade_date": T1, "submitted_at": "2026-10-26T08:10:00+08:00", "official_status": "accepted", "official_receipt_id": "B"},
            {"trade_date": T1, "submitted_at": "2026-10-26T08:20:00+08:00", "official_status": "rejected"},
            {"trade_date": T1, "submitted_at": "2026-10-26T09:00:00+08:00", "official_status": "accepted", "official_receipt_id": "LATE"}]
    e = effective_submission(recs, T1)
    assert e["effective"]["official_receipt_id"] == "B"          # last SUCCESSFUL before 08:55
    assert e["last_upload"]["official_status"] == "rejected"     # last upload is not the effective one
    assert e["last_upload_is_effective"] is False and e["late_ignored"] == 1 and e["uploads"] == 3


# ---------------------------------------------------------------- official -> internal mapping
@pytest.mark.parametrize("result,sid,conf,state", [
    ("accepted", "S-1", False, "ACCEPTED"),
    ("accepted", None, True, "ACCEPTED"),
    ("accepted", None, False, "UPLOADED"),           # "upload completed" wording alone is not acceptance
    ("pending", None, False, "UPLOADED"),
    ("unknown", None, False, "UPLOADED"),
    ("rejected", None, False, "REJECTED"),
    ("ui_unavailable", None, False, "SUBMISSION_UI_UNAVAILABLE"),
])
def test_official_result_mapping(result, sid, conf, state):
    assert OT.map_official_result(result, sid, conf)["state"] == state


def test_receipt_format_pending_and_ui_login_required():
    assert OFFICIAL_RECEIPT_FORMAT == "PENDING_PORTAL_VALIDATION"
    sub = load_ops_config()["submission"]
    assert sub["receipt_format"] == "PENDING_PORTAL_VALIDATION" and sub["ui_status"] == "LOGIN_REQUIRED"
    assert sub["portal_url"] is None and sub["official_portal_provider"] == "DISABLED_PENDING_OFFICIAL_PORTAL_VALIDATION"


# ---------------------------------------------------------------- test-period evidence (isolated)
def test_record_upload_is_isolated_and_refuses_credentials(test_cfg, tmp_path):
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"png")
    r = OT.record_upload(T1, "sha256:" + "a" * 64, "accepted", "上傳成功 編號 S-9", "op", submission_id="S-9",
                         evidence=[str(shot)], ops_cfg=test_cfg)
    assert r["mapped_internal_state"] == "ACCEPTED" and r["environment"] == "OFFICIAL_TEST"
    assert Path(r["evidence"][0]["file"]).parent == OT.dirs(T1, test_cfg)["receipts"]
    assert not (Path(test_cfg["paths"]["submissions_dir"]) / "20261026" / "receipts.jsonl").exists()
    for bad in ("Set-Cookie: sid=abc", "Bearer eyJhbGciOiJIUzI1NiJ9", "password=hunter2", "csrftoken=x"):
        with pytest.raises(ValueError, match="credential"):
            OT.record_upload(T1, "sha256:" + "a" * 64, "unknown", bad, "op", ops_cfg=test_cfg)


def test_package_blocked_without_official_team_id(fixture_store, test_cfg):
    run(fixture_store, test_cfg, T1, CLK1, mode="dry-run", initial=True)
    p = OT.package(T1, ops_cfg=dict(test_cfg, team={"competition_team_id": None}), now=at("2026-10-26T07:00:00"))
    assert p["status"] == "BLOCKED_TEAM_ID_NOT_CONFIGURED" and p["final"]["sha256_verified"]
    assert p["local_checks"]["schema"] == "PASS" and p["quant_fingerprint"]["frozen"]
    assert (OT.dirs(T1, test_cfg)["reports"] / "TEST_SUBMISSION_PACKAGE.md").exists()


def test_package_ready_only_with_matching_official_team(fixture_store, test_cfg):
    cfg = dict(test_cfg, team={"competition_team_id": "TEAM_042"})
    s = run_competition_day(T1, "TEAM_042", "competition", store=fixture_store, store_is_fixture=True, ops_cfg=cfg,
                            clock=Clock(CLK1), git=CLEAN_GIT, archive_readonly=False, skip_refresh=True, initial=True)
    assert s["status"] == "READY_TO_SUBMIT", s.get("reason")
    p = OT.package(T1, ops_cfg=cfg, now=at("2026-10-26T07:00:00"))
    assert p["status"] == "READY_FOR_MANUAL_TEST_UPLOAD", p["problems"]
    assert p["final"]["filename"] == f"D-Plan_TEAM_042_{T1}.json" and p["submission_status"] == "READY_FOR_UPLOAD"
    r = OT.record_upload(T1, p["final"]["sha256"], "accepted", "Upload completed", "op", ops_cfg=cfg)
    assert r["sha256_matches_package"] is True and r["mapped_internal_state"] == "UPLOADED"   # no id -> not ACCEPTED


def test_datapack_inventory_is_read_only(test_cfg):
    src = FIX / "official_example_3_1_valid_TEAM_042_2026-10-28.json"
    r = OT.datapack(str(src), "2026-10-28", "TEAM_042", ops_cfg=test_cfg)
    assert r["imported_into_competition_chain"] is False and r["sha256"].startswith("sha256:")
    assert Path(r["archived"]).parent == OT.dirs("2026-10-28", test_cfg)["datapack"]
    assert any(k.startswith("holdings") for k in r["field_inventory"]) and r["validation"] is not None
    assert not list(Path(test_cfg["paths"]["official_datapack_dir"]).glob("*.json")) \
        if Path(test_cfg["paths"]["official_datapack_dir"]).exists() else True


def test_official_test_module_has_no_network_or_login_code():
    src = Path(OT.__file__).read_text(encoding="utf-8").lower()
    for bad in ("import requests", "import urllib", "urlopen(", ".post(", "selenium", "playwright", "webbrowser"):
        assert bad not in src, bad
