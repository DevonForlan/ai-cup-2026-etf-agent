"""19:30 precompetition scheduler: catch-up, cross-day skip, already-PASS skip, network retries, status mapping."""
from datetime import datetime

from agent.ops import scheduled_run as S
from agent.ops.common import TPE

HOL = {"2026-10-09", "2026-10-26"}


def at(s):
    return datetime.fromisoformat(s + "+08:00")


def test_on_time_run_targets_next_trading_day():
    p = S.plan(at("2026-10-13T19:30:05"), HOL)
    assert p["action"] == "RUN" and p["trade_date"] == "2026-10-14" and p["run_delay_minutes"] == 0
    assert p["scheduled_time"] == "2026-10-13T19:30:00+08:00"


def test_same_day_catch_up_records_delay():
    p = S.plan(at("2026-10-13T22:11:00"), HOL)
    assert p["action"] == "RUN" and p["run_delay_minutes"] == 161 and p["actual_start_time"].startswith("2026-10-13T22:11")


def test_after_midnight_is_cross_day_catch_up_for_today():
    """2026-10-20 policy (was MISSED_PREVIOUS_DAY): the window of TODAY's trade date is still open until 08:30."""
    p = S.plan(at("2026-10-14T00:20:00"), HOL)
    assert p["action"] == "RUN" and p["run_kind"] == "CROSS_DAY_CATCHUP" and p["scheduled_date"] == "2026-10-13"
    assert p["trade_date"] == "2026-10-14"


def test_no_window_when_next_day_is_not_a_trading_day():
    assert S.plan(at("2026-10-16T19:31:00"), HOL)["reason"] == "NO_SUBMISSION_WINDOW_TONIGHT"   # Fri -> Sat
    assert S.plan(at("2026-10-08T19:31:00"), HOL)["reason"] == "NO_SUBMISSION_WINDOW_TONIGHT"   # -> 10-09 holiday
    assert S.plan(at("2026-10-25T19:31:00"), HOL)["reason"] == "NO_SUBMISSION_WINDOW_TONIGHT"   # -> 10-26 closed
    p = S.plan(at("2026-10-26T19:30:00"), HOL)                                                  # first window
    assert p["action"] == "RUN" and p["trade_date"] == "2026-10-27"
    assert S.plan(at("2026-10-18T19:31:00"), HOL)["trade_date"] == "2026-10-19"                # Sun -> Mon


def test_already_passed_today_is_skipped_blocked_or_failed_may_rerun():
    hist = [{"scheduled_date": "2026-10-13", "status": "BLOCKED"}, {"scheduled_date": "2026-10-12", "status": "PASS"}]
    assert not S.already_passed("2026-10-13", hist)
    assert S.already_passed("2026-10-13", hist + [{"scheduled_date": "2026-10-13", "status": "PASS"}])


def test_network_retries_then_blocked_and_recovery(monkeypatch):
    calls = {"n": 0}

    def down(name, target):
        return False
    r = S.network_check(5, 0, None, down)
    assert not r["ok"] and r["retries"] == 5

    def recovers(name, target):
        calls["n"] += 1
        return calls["n"] > len(S.NETWORK_TARGETS) * 2          # fails on the first two rounds, then OK
    r = S.network_check(5, 0, None, recovers)
    assert r["ok"] and r["retries"] == 2

    def tpex_only(name, target):
        return name != "TWSE"                                     # one of TWSE / TPEx is enough
    assert S.network_check(0, 0, None, tpex_only)["ok"]


def test_summarize_maps_competition_day_outcomes():
    pf = {"checks": [{"name": "etf_holdings_freshness", "level": "BLOCK", "detail": "oldest 2026-10-02 (11 days)"}]}
    b = S.summarize({"status": "BLOCKED", "reason": "preflight BLOCK: etf_holdings_freshness: ..."}, pf, 2)
    assert b["status"] == "BLOCKED" and b["blocked_reason"] == "ETF_HOLDINGS_STALE"
    ok = S.summarize({"status": "DRY_RUN_OK", "decisions": 24, "validation": "PASS", "final_file": "x.json",
                      "llm": {"used": True, "calls": 3, "failed": 0},
                      "compliance_summary": {"Active Share official >= 15%": "PASS (46.65%)"}}, None, 0)
    assert ok["status"] == "PASS" and ok["grounding"] == "PASS" and ok["active_share"].startswith("PASS")
    fb = S.summarize({"status": "DRY_RUN_OK", "llm": {"used": False, "calls": 3, "failed": 3}}, None, 0)
    assert fb["status"] == "PASS" and fb["grounding"] == "TEMPLATE_FALLBACK"
    assert S.summarize(None, None, 1)["status"] == "FAILED"


def test_check_reports_missed_when_no_record_today():
    c = S.check(at("2026-10-13T21:00:00"), {"scheduled_date": "2026-10-12", "status": "PASS"})
    assert c["status"] == "MISSED" and c["recommended_action"] == "MANUAL_RERUN_RECOMMENDED"
    c = S.check(at("2026-10-13T21:00:00"), {"scheduled_date": "2026-10-13", "status": "PASS"})
    assert c["status"] == "PASS" and c["recommended_action"] == "NONE"
    c = S.check(at("2026-10-13T21:00:00"), {"scheduled_date": "2026-10-13", "status": "BLOCKED"})
    assert c["recommended_action"] == "MANUAL_RERUN_RECOMMENDED"
    assert S.check(at("2026-10-13T15:00:00"), {"scheduled_date": "2026-10-12", "status": "PASS"})["status"] == "PASS"


def test_run_skips_without_side_effects_when_already_passed(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "LOG_DIR", tmp_path)
    monkeypatch.setattr(S, "LATEST", tmp_path / "latest_status.json")
    monkeypatch.setattr(S, "HISTORY", tmp_path / "history.jsonl")
    monkeypatch.setattr(S, "holidays", lambda cfg=None: HOL)
    (tmp_path / "history.jsonl").write_text('{"scheduled_date": "2026-10-13", "status": "PASS"}\n', encoding="utf-8")
    monkeypatch.setattr(S, "network_check", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    r = S.run(now=datetime(2026, 10, 13, 22, 0, tzinfo=TPE))
    assert r["status"] == "SKIPPED" and r["blocked_reason"] == "SKIP_ALREADY_PASSED"
    assert (tmp_path / "latest_status.json").exists() and "OVERALL_STATUS" in open(r["log_file"], encoding="utf-8").read()
    r = S.run(now=datetime(2026, 10, 14, 0, 20, tzinfo=TPE))           # catch-up for a date that already PASSED
    assert r["status"] == "SKIPPED" and r["blocked_reason"] == "SKIP_ALREADY_PASSED"

def test_probe_treats_a_cdn_403_as_reachable_but_5xx_and_timeouts_as_down(monkeypatch):
    import io
    import urllib.error

    def raiser(code):
        def f(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO(b""))
        return f
    monkeypatch.setattr(S.urllib.request, "urlopen", raiser(403))
    assert S._probe("ESUN", "https://esun-ai-challenge.tw/") is True
    monkeypatch.setattr(S.urllib.request, "urlopen", raiser(503))
    assert S._probe("ESUN", "https://esun-ai-challenge.tw/") is False

    def boom(req, timeout=0):
        raise OSError("timeout")
    monkeypatch.setattr(S.urllib.request, "urlopen", boom)
    assert S._probe("ESUN", "https://esun-ai-challenge.tw/") is False

