"""Issue #23: automatic official DataPack acquisition via the confirmed portal UI (fake driver; nothing real).
The downloaded file is validated by the SAME gate the run uses, quarantined unless it passes, installed atomically
with provenance, never modified; login / page mismatch / stale / invalid all fail closed."""
import copy
import inspect
import json
import shutil
from pathlib import Path

import pytest

from agent.ops import datapack_acquire as DA
from agent.ops import scheduled_run as S
from agent.ops.common import load_ops_config
from agent.submission import portal_driver as PD

REAL_HOOK = S._acquire_datapack                      # the conftest guard replaces it per test; restored on demand
FX = Path(__file__).resolve().parents[1] / "fixtures" / "datapack"
VALID = "official_example_3_1_valid_TEAM_042_2026-10-28.json"
STALE = "synthetic_stale_TEAM_042.json"
BAD = "synthetic_negative_cash.json"
T, TEAM = "2026-10-28", "TEAM_042"


@pytest.fixture
def cfg(tmp_path):
    c = copy.deepcopy(load_ops_config())
    c["paths"] = dict(c["paths"], official_datapack_dir=str(tmp_path / "official"))
    c["datapack"] = {"auto_download": {"enabled": True, "max_attempts": 3, "retry_wait_s": 0, "download_timeout_s": 1}}
    return c


class FakeDL:
    """Fake portal: serves fixture files through download_datapack (one per attempt)."""
    def __init__(self, files, *, login="LOGGED_IN", team=TEAM, date=T, raises=None):
        self.files, self.login, self.team, self.date, self.raises = list(files), login, team, date, raises
        self.calls, self.closed = [], 0

    def __call__(self, ops_cfg, official_test):
        return self

    def open_portal(self): self.calls.append("open")
    def check_login(self): return self.login
    def read_team_id(self): return self.team
    def read_trade_date(self): return self.date
    def safe_url(self): return "https://portal/docs"

    def download_datapack(self, dest, timeout_s=60):
        self.calls.append("download")
        if self.raises:
            raise self.raises
        name = self.files.pop(0) if len(self.files) > 1 else self.files[0]
        Path(dest).mkdir(parents=True, exist_ok=True)
        shutil.copy2(FX / name, Path(dest) / name)
        return {"suggested_filename": name, "path": str(Path(dest) / name)}

    def close(self): self.closed += 1


def _official(cfg):
    return Path(cfg["paths"]["official_datapack_dir"])


def test_valid_download_is_installed_atomically_with_provenance(cfg):
    drv = FakeDL([VALID])
    r = DA.acquire(T, TEAM, ops_cfg=cfg, driver_factory=drv, sleep=lambda s: None)
    assert r["status"] == "INSTALLED" and drv.closed == 1
    f = Path(r["file"])
    assert f.parent == _official(cfg) and f.read_bytes() == (FX / VALID).read_bytes()      # content untouched
    prov = json.loads((_official(cfg) / "provenance" / f"{f.stem}.json").read_text(encoding="utf-8"))
    assert prov["sha256"] == DA._sha(f) and prov["gate"]["status"] == "PASS" and prov["page_trade_date"] == T
    assert "下載資料包" in prov["method"] and (_official(cfg) / "provenance" / "acquisition_log.jsonl").exists()
    r2 = DA.acquire(T, TEAM, ops_cfg=cfg, driver_factory=FakeDL([VALID]), sleep=lambda s: None)
    assert r2["status"] == "ALREADY_PRESENT"                                                # idempotent, no browser


def test_identical_redownload_is_not_duplicated(cfg):
    DA.acquire(T, TEAM, ops_cfg=cfg, driver_factory=FakeDL([VALID]), sleep=lambda s: None)
    r = DA.acquire(T, TEAM, ops_cfg=cfg, driver_factory=FakeDL([VALID]), sleep=lambda s: None, force=True)
    assert r["status"] == "ALREADY_PRESENT" and len(list(_official(cfg).glob("*.json"))) == 1


@pytest.mark.parametrize("kw, status", [
    (dict(login="LOGIN_REQUIRED"), "LOGIN_REQUIRED"),
    (dict(team="TEAM_999"), "PAGE_MISMATCH"),
    (dict(date="2026-10-29"), "PAGE_MISMATCH"),
])
def test_no_download_without_login_or_on_the_wrong_page(cfg, kw, status):
    drv = FakeDL([VALID], **kw)
    r = DA.acquire(T, TEAM, ops_cfg=cfg, driver_factory=drv, sleep=lambda s: None)
    assert r["status"] == status and "download" not in drv.calls and len(r["attempts"]) == 1   # never retried
    assert not list(_official(cfg).glob("*.json"))


def test_stale_is_retried_bounded_then_installed_when_published(cfg):
    waits = []
    drv = FakeDL([STALE, VALID])
    r = DA.acquire(T, TEAM, ops_cfg=cfg, driver_factory=drv, sleep=waits.append)
    assert r["status"] == "INSTALLED" and len(r["attempts"]) == 2 and waits == [0.0]
    q = [p for p in (_official(cfg) / ".incoming").rglob("QUARANTINED.json")]
    assert len(q) == 1                                                  # the stale file stayed in quarantine


def test_stale_forever_gives_up_after_max_attempts(cfg):
    r = DA.acquire(T, TEAM, ops_cfg=cfg, driver_factory=FakeDL([STALE]), sleep=lambda s: None)
    assert r["status"] == "DATAPACK_STALE" and len(r["attempts"]) == 3 and not list(_official(cfg).glob("*.json"))


def test_invalid_download_is_quarantined_never_installed(cfg):
    r = DA.acquire(T, TEAM, ops_cfg=cfg, driver_factory=FakeDL([BAD]), sleep=lambda s: None)
    assert r["status"] == "DATAPACK_INVALID" and len(r["attempts"]) == 1
    assert not list(_official(cfg).glob("*.json"))


def test_download_failure_fails_closed(cfg):
    drv = FakeDL([VALID], raises=PD.UIUnexpected("DATAPACK_DOWNLOAD_NOT_STARTED (TimeoutError)"))
    r = DA.acquire(T, TEAM, ops_cfg=cfg, driver_factory=drv, sleep=lambda s: None)
    assert r["status"] == "DOWNLOAD_FAILED" and len(r["attempts"]) == 3 and drv.closed == 3


def test_disabled_config_never_opens_a_browser(cfg):
    cfg["datapack"]["auto_download"]["enabled"] = False
    r = DA.acquire(T, TEAM, ops_cfg=cfg, driver_factory=lambda *a: pytest.fail("browser"), sleep=lambda s: None)
    assert r["status"] == "AUTO_DOWNLOAD_DISABLED"


def test_competition_preparation_acquires_then_passes_the_gate(cfg, tmp_path, monkeypatch):
    from tests.ops.test_datapack_integration import _log
    calls, real = [], DA.acquire

    def acq(t, team, ops_cfg):
        calls.append(t)
        return real(t, team, ops_cfg=ops_cfg, driver_factory=FakeDL([VALID]), sleep=lambda s: None)
    monkeypatch.setattr(DA, "acquire", acq)
    monkeypatch.setattr(S, "_acquire_datapack", REAL_HOOK)
    lg = _log(tmp_path)
    r = S.competition_preparation("COMPETITION", T, TEAM, lg, ops_cfg=cfg)
    assert calls == [T] and r["blocked_reason"] is None and r["cd_mode"] == "competition"
    assert r["datapack_status"].startswith("PASS")
    assert "DATAPACK_ACQUIRE" in lg.path.read_text(encoding="utf-8")


def test_competition_preparation_stays_blocked_when_acquisition_fails(cfg, tmp_path, monkeypatch):
    from tests.ops.test_datapack_integration import _log
    monkeypatch.setattr(DA, "acquire", lambda t, team, ops_cfg: {"status": "LOGIN_REQUIRED", "attempts": [{}]})
    monkeypatch.setattr(S, "_acquire_datapack", REAL_HOOK)
    r = S.competition_preparation("COMPETITION", T, TEAM, _log(tmp_path), ops_cfg=cfg)
    assert r["blocked_reason"] == "DATAPACK_MISSING"                   # no fallback, no paper ledger


def test_driver_download_uses_only_the_confirmed_button_and_the_browser_download_event():
    from tests.ops.test_submission_window import _code_only
    import textwrap
    src = _code_only(textwrap.dedent(inspect.getsource(PD.PlaywrightPortalDriver.download_datapack)))
    assert '_locate ( "datapack_download" , action = true )' in src and "expect_download" in src
    for bad in ("goto(", "request", "fetch(", "cookie", "storage", "token", "/api/", ".fill(", ".type("):
        assert bad not in src, bad
    assert PD.load_adapter()["selectors"]["datapack_download"]["status"] == "CONFIRMED_REAL_E2E"
    a = _code_only(inspect.getsource(DA))
    for bad in ("requests", "urllib", "cookie", "token", "csrf", "/api/", "playwright", ".fill(", ".type("):
        assert bad not in a, bad


def test_guard_no_test_reaches_the_real_portal():
    """The conftest guard (Issue #23): the run hook is inert and the real driver refuses in every test."""
    from agent.submission import auto_upload as AU
    assert S._acquire_datapack("2026-10-28", "TEAM_042", False, None, None) is None
    with pytest.raises(RuntimeError, match="forbidden in tests"):
        AU._default_driver({}, False)
