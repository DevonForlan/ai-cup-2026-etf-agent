"""Round 07: production-candidate wiring — competition profile, sectioned Claude CLI config, version pin,
whitelisted auth, READY/DEGRADED status line, runtime budget phases, FINAL mode precedence, official
calendar, CTBC error surfacing."""
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from agent.competition_day import llm_runtime_status, load_competition_profile, operator_summary
from agent.llm.client import flatten_sections, load_llm_config
from agent.llm.providers import claude_cli as C
from agent.llm.providers.mock import MockProvider
from agent.ops.common import load_ops_config
from agent.ops.package_submission import active_final, mark_final
from tests.ops.test_competition_day import CLK1, T1, run
from tests.ops.test_ops_units import _pkg

ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- profile / config
def test_prod_profile_is_claude_primary_template_fallback_and_global_default_unchanged():
    p = load_competition_profile("prod")
    assert p["llm"] == {"primary": "claude-cli", "config": "config/llm_claude_cli.yaml", "fallback": "template",
                        "role": "narrative_research_only"}
    assert p["strategy_config"] == "config/strategy_quant_v1.yaml"
    assert load_llm_config()["provider"] == "template"                       # global default stays template
    assert load_llm_config("config/llm_claude_cli.yaml")["enabled"] is False  # only the profile / flag enables it


def test_sectioned_cli_config_flattens_and_locks_tools():
    c = load_llm_config("config/llm_claude_cli.yaml")
    assert c["provider"] == "claude_cli" and c["fallback_provider"] == "template"
    assert c["supported_versions"] == ["2.1.289", "2.1.291", "2.1.296"] and c["accepted_auth_methods"] == ["claude.ai"]
    assert c["claude_cli"]["profile"] == "NARRATIVE_LOCKED" and c["retries"] == 0
    assert c["events"]["enabled"] is False and c["llm_signal"]["enabled"] is False
    assert c["research"]["enabled"] is True and c["narrative"]["mode"] == "llm"
    for t in ("Bash", "Read", "Write", "Edit", "WebFetch", "WebSearch", "mcp__*", "Browser", "Git"):
        assert t in c["tools"]["forbidden"]
    assert "TIMEOUT" in c["fallback_on"] and "USAGE_LIMIT" in c["fallback_on"]
    raw = yaml.safe_load((ROOT / "config/llm_claude_cli.yaml").read_text(encoding="utf-8"))
    for bad in ({"tools": dict(raw["tools"], allowed=["Bash"])},
                {"tools": dict(raw["tools"], profile="RESEARCH_READONLY")},
                {"session": dict(raw["session"], persistence=True)},
                {"fallback": {"provider": "gemini"}}):
        with pytest.raises(ValueError):
            flatten_sections(dict(raw, **bad))


def test_cli_profile_flag_resolution(monkeypatch):
    import agent.competition_day as CD
    seen = {}

    def fake_run(date, team, mode, **kw):
        seen.update(kw)
        return {"status": "DRY_RUN_OK", "trade_date": date, "team_id": team, "mode": mode}
    monkeypatch.setattr(CD, "run_competition_day", fake_run)
    monkeypatch.setattr(CD, "operator_summary", lambda s: "x")
    monkeypatch.setattr(CD, "ops_path", lambda cfg, k: ROOT / "runtime" / "test_round07")
    monkeypatch.setattr(C, "resolve_claude_cli", lambda refresh=False: {"path": None, "kind": None, "version": None,
                                                                       "rejected": []})
    (ROOT / "runtime" / "test_round07" / "20261006").mkdir(parents=True, exist_ok=True)
    CD.main(["--date", "2026-10-06", "--team-id", "T", "--competition-profile", "prod"])
    assert seen["llm_config"] == "config/llm_claude_cli.yaml" and seen["llm_provider"].name == "claude_cli"
    CD.main(["--date", "2026-10-06", "--team-id", "T", "--competition-profile", "prod", "--llm-provider", "template"])
    assert seen["llm_provider"] is None and seen["llm_config"] is None     # explicit template wins
    CD.main(["--date", "2026-10-06", "--team-id", "T"])
    assert seen["llm_provider"] is None                                     # no profile -> template default


# ---------------------------------------------------------------- version pin / auth / status line
@pytest.mark.parametrize("v,exp", [("2.1.289", "VERSION_VALIDATED"), ("2.1.291", "VERSION_VALIDATED"),
                                   ("2.1.296", "VERSION_VALIDATED"), ("2.1.292", "WARNING_VERSION_DRIFT"), ("2.1.297", "WARNING_VERSION_DRIFT"),
                                   (None, "CLI_NOT_FOUND")])
def test_version_pin(v, exp):
    supported = load_llm_config("config/llm_claude_cli.yaml")["supported_versions"]
    assert C.version_check(v, supported) == exp


def test_auth_status_reads_only_whitelisted_fields(monkeypatch):
    secret = {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "subscriptionType": "team",
              "email": "someone@example.invalid", "orgId": "org-123", "orgName": "Example Org",
              "token": "sk-ant-oat01-SECRET"}
    monkeypatch.setattr(C, "resolve_claude_cli", lambda refresh=False: {"path": "claude.exe", "kind": "native",
                                                                       "version": "2.1.289", "rejected": []})
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(secret), ""))
    a = C.auth_status()
    assert set(a) == {"loggedIn", "authMethod", "subscriptionType", "apiProvider"}
    assert "SECRET" not in json.dumps(a) and "example" not in json.dumps(a).lower()


class _FakeCLI:
    name = "claude_cli"

    def __init__(self, hc, cfg=None):
        self.hc, self.cfg = hc, cfg or {"supported_versions": ["2.1.289"]}

    def healthcheck(self):
        return self.hc


def test_llm_status_line_ready_degraded_and_deadline():
    ready = _FakeCLI({"cli_found": True, "claude_code_version": "2.1.289", "version_check": "VERSION_VALIDATED", "loggedIn": True,
                      "authMethod": "claude.ai", "llm_status": "READY", "status": "READY", "fallback": "template"})
    st = llm_runtime_status(ready)
    assert st["line"] == "LLM: PRIMARY=claude-cli STATUS=READY FALLBACK=template"
    down = _FakeCLI({"cli_found": True, "loggedIn": False, "llm_status": "DEGRADED", "status": "NOT_AUTHENTICATED"})
    assert llm_runtime_status(down)["line"].startswith("LLM: PRIMARY=claude-cli STATUS=DEGRADED FALLBACK=template")
    missing = _FakeCLI({"cli_found": False, "llm_status": "DEGRADED", "status": "CLI_NOT_FOUND"})
    assert "CLI_NOT_FOUND" in llm_runtime_status(missing)["line"]

    class _D:
        allow_llm, phase = False, "NO_LLM"
    assert llm_runtime_status(ready, _D())["status"] == "DEGRADED"
    assert llm_runtime_status(None)["line"] == "LLM: PRIMARY=template STATUS=TEMPLATE FALLBACK=template"


def test_provider_healthcheck_degraded_on_wrong_auth_method(monkeypatch):
    monkeypatch.setattr(C, "resolve_claude_cli", lambda refresh=False: {"path": "claude.exe", "kind": "native",
                                                                       "version": "2.1.300", "rejected": []})
    p = C.ClaudeCodeCLIProvider(None, load_llm_config("config/llm_claude_cli.yaml"))
    p._auth = {"loggedIn": True, "authMethod": "apiKey"}
    hc = p.healthcheck()
    assert hc["llm_status"] == "DEGRADED" and hc["version_check"] == "WARNING_VERSION_DRIFT"
    p._auth = {"loggedIn": True, "authMethod": "claude.ai"}
    assert p.healthcheck()["llm_status"] == "READY"


def test_unavailable_cli_never_fails_competition_day(fixture_store, ops_cfg, monkeypatch):
    monkeypatch.setattr(C, "resolve_claude_cli", lambda refresh=False: {"path": None, "kind": None, "version": None,
                                                                       "rejected": []})
    prov = C.ClaudeCodeCLIProvider(None, dict(load_llm_config("config/llm_claude_cli.yaml"), enabled=True))
    s = run(fixture_store, ops_cfg, T1, CLK1, mode="dry-run", initial=True, llm_config="config/llm_claude_cli.yaml",
            llm_provider=prov)
    assert s["status"] == "DRY_RUN_OK" and s["validation"] == "PASS" and s["llm"]["used"] is False
    assert s["llm_runtime"]["status"] == "DEGRADED"
    assert "LLM: PRIMARY=claude-cli STATUS=DEGRADED FALLBACK=template" in operator_summary(s)


# ---------------------------------------------------------------- runtime budget
@pytest.fixture
def research_mock_cfg(tmp_path):
    p = tmp_path / "llm_mock.yaml"
    base = load_llm_config("config/llm_claude_cli.yaml")
    base.update(provider="mock", model="mock-rules-v1", enabled=True, log_calls=False)
    p.write_text(yaml.safe_dump(base, allow_unicode=True), encoding="utf-8")
    return str(p)


def test_restricted_phase_allows_only_the_market_narrative(fixture_store, ops_cfg, research_mock_cfg):
    prov = MockProvider("mock-rules-v1", "normal")
    s = run(fixture_store, ops_cfg, T1, "2026-10-26T08:35:00+08:00", mode="dry-run", initial=True,
            llm_config=research_mock_cfg, llm_provider=prov)
    assert s["deadline"]["phase"] == "RESTRICTED" and s["status"] == "DRY_RUN_OK"
    assert prov.calls == 1 and s["llm"]["calls"] == 1 and s["llm"]["research_inferences"] == 0
    assert any("runtime budget RESTRICTED" in n for n in s["notes"])


def test_normal_phase_runs_narrative_and_thesis(fixture_store, ops_cfg, research_mock_cfg):
    prov = MockProvider("mock-rules-v1", "normal")
    s = run(fixture_store, ops_cfg, T1, CLK1, mode="dry-run", initial=True, llm_config=research_mock_cfg,
            llm_provider=prov)
    assert s["deadline"]["phase"] == "NORMAL" and prov.calls >= 2 and s["llm"]["used"]
    assert "llm_availability" not in s["preflight"]["warns"]        # checks the real provider, not the file flag


# ---------------------------------------------------------------- FINAL mode precedence
@pytest.fixture(scope="module")
def day1(fixture_store, rb, tmp_path_factory):
    from tests.ops import test_ops_units as U
    return U.day1.__wrapped__(fixture_store, rb, tmp_path_factory)


def test_competition_final_supersedes_dry_run_final(day1, ops_cfg):
    d = mark_final(_pkg(day1, ops_cfg, "dry"), team_id="TEAM_TEST", trade_date=T1, mode="dry-run", ops_cfg=ops_cfg)
    c = mark_final(_pkg(day1, ops_cfg, "comp"), team_id="TEAM_TEST", trade_date=T1, mode="competition",
                   ops_cfg=ops_cfg)
    assert d["ok"] and c["ok"] and c["event"] == "SUPERSEDED_NON_COMPETITION" and c["old_mode"] == "dry-run"
    assert active_final(T1, ops_cfg)["run_id"] == "comp"
    again = mark_final(_pkg(day1, ops_cfg, "dry2"), team_id="TEAM_TEST", trade_date=T1, mode="dry-run",
                       ops_cfg=ops_cfg, replace=True, reason="x", operator="operator A")
    assert not again["ok"] and again["kept"]                                 # dry-run never replaces competition
    comp2 = mark_final(_pkg(day1, ops_cfg, "comp2"), team_id="TEAM_TEST", trade_date=T1, mode="competition",
                       ops_cfg=ops_cfg)
    assert not comp2["ok"] and comp2["kept"]                                 # competition FINAL stays frozen
    assert active_final(T1, ops_cfg)["run_id"] == "comp"


# ---------------------------------------------------------------- official calendar
def test_official_twse_calendar_2026():
    cal = yaml.safe_load((ROOT / "config/trading_calendar_2026.yaml").read_text(encoding="utf-8"))
    assert cal["source"]["authority"].startswith("TWSE") and cal["source"]["url"].startswith("https://www.twse.com.tw/")
    assert "2026-10-26" in cal["competition_period_market_closures"]
    assert len(cal["competition_period_trading_days"]) == cal["competition_period_trading_days_count"] == 24
    assert cal["competition_period_trading_days"][0] == "2026-10-27"
    hol = {str(x) for x in load_ops_config()["market_holidays"]}
    assert "2026-10-26" in hol and hol == {str(x["date"]) for x in cal["weekday_market_closures"]}


def test_ctbc_persistent_error_is_surfaced(monkeypatch):
    from agent.data.fetchers import etf_holdings as E
    calls = []

    def fake_post(session, url, body, hdr=None):
        calls.append(url)
        if "AuthToken" in url:
            return json.dumps({"Data": {"token": "t"}}).encode()
        return json.dumps({"ResultCode": 9, "Message": "token invalid"}).encode()
    monkeypatch.setattr(E, "_post_json", fake_post)
    with pytest.raises(RuntimeError, match="ResultCode=9"):
        E.fetch_ctbc(None, "00995A", "E0036", "2026-10-05")
    assert len(calls) == 6


def test_readiness_reports_llm_runtime_without_changing_level(monkeypatch, tmp_path):
    from agent.ops import readiness as R
    monkeypatch.setattr(R, "write_json", lambda path, obj: None)
    r = R.assess({"ok": True, "failed": 0, "summary": "x"})
    assert r["llm_runtime"] == "CLAUDE_CLI_PRODUCTION_CANDIDATE" and r["llm_fallback"] == "template"
    assert r["level"] != "COMPETITION_READY"                      # NC-1 / NC-15 still open
