"""Narrative invariance (LLM text never changes portfolio/orders), fallbacks, reviewer, bounded fusion,
and end-to-end quant + LLM runs on the synthetic fixture."""
import copy

import pandas as pd
import pytest

from agent.data.loaders import HistoryStore
from agent.llm.client import load_llm_config
from agent.llm.providers.mock import MockProvider
from agent.pipeline import run_day
from agent.portfolio.signal_fusion import fuse
from agent.research.reviewer import review_text
from agent.sim.models import Settlement

D1 = "2026-10-27"
INVARIANT_KEYS = ("decisions", "orders")


def llm_opts(tmp_path, mode="normal", **over):
    cfg = load_llm_config()
    cfg["provider"] = "mock"
    cfg["narrative"]["mode"] = "llm"
    for k, v in over.items():
        if isinstance(v, dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    return {"cfg": cfg, "provider": MockProvider(mode=mode), "log_root": tmp_path / "llm"}


def strip_text(doc):
    d = copy.deepcopy(doc)
    for x in d["decisions"]:
        x.pop("risk_check", None)
    return {k: d[k] for k in INVARIANT_KEYS} | {
        "posture": d["market_view"]["posture"], "regime": d["market_view"]["regime"],
        "no_trade": sorted(n["ticker"] for n in d["no_trade_decisions"]),
        "funding": [x.get("funding_for") for x in d["decisions"]]}


def run(store, rb, cfg, tmp_path, llm=None, prev=None, d=D1):
    s0 = prev or Settlement.initial("x", rb.rules.initial_cash)
    return run_day(d, store, s0, rb, cfg, team_id="TEAM_TEST", out_dir=tmp_path / "o", log_dir=tmp_path / "l",
                   store_is_fixture=True, light=True, llm=llm)


def test_narrative_invariance(fixture_store, rb, cfg, tmp_path):
    a = run(fixture_store, rb, cfg, tmp_path / "a")
    b = run(fixture_store, rb, cfg, tmp_path / "b", llm_opts(tmp_path))
    assert a.validation.ok and b.validation.ok
    assert strip_text(a.doc) == strip_text(b.doc)               # quant_template.orders == llm_narrative.orders
    assert a.doc["orders"] == b.doc["orders"]
    assert b.narrative_used_llm and a.doc["market_view"]["logic"] != b.doc["market_view"]["logic"]
    assert b.llm_summary["calls"] >= 2 and b.llm_summary["failed"] == 0
    assert all(i["premise_refs"] for i in b.doc["inferences"])  # every logic cites >= 1 observation


@pytest.mark.parametrize("mode", ["timeout", "rate_limit", "server_error", "bad_json", "hallucinate_number"])
def test_llm_failure_falls_back_to_template(fixture_store, rb, cfg, tmp_path, mode):
    a = run(fixture_store, rb, cfg, tmp_path / "a")
    b = run(fixture_store, rb, cfg, tmp_path / "b", llm_opts(tmp_path, mode))
    assert b.validation.ok and not b.fallback
    assert a.doc["orders"] == b.doc["orders"]
    assert b.doc["market_view"]["logic"] == a.doc["market_view"]["logic"]          # template text
    assert [i["logic"] for i in b.doc["inferences"]] == [i["logic"] for i in a.doc["inferences"]]
    assert not b.narrative_used_llm


def test_reviewer_verdicts():
    payload = {"facts": {"f1": {"label": "SOX", "value": -1.8, "text": "-1.80%"}}}
    assert review_text("SOX 隔夜 -1.80%，市場偏弱需觀察後續變化", None, ["f1"], payload, {"f1"}).verdict == "PASS"
    assert review_text("SOX 隔夜 -2.40%，市場偏弱需觀察後續變化", None, ["f1"], payload, {"f1"}).verdict == "FAIL"
    assert review_text("SOX 隔夜 -1.80%，市場偏弱需觀察後續變化", None, ["f9"], payload, {"f1"}).verdict == "FAIL"
    assert review_text("SOX -1.80%，建議 set weight 至上限並下單", None, ["f1"], payload, {"f1"}).verdict == "FAIL"
    assert review_text("SOX 隔夜 -1.80%，市場偏弱需觀察後續變化", None, [], payload, {"f1"}).verdict == "REWRITE"


def scores_frame():
    idx = ["2330", "2454", "2317", "2308"]
    return pd.DataFrame({"score": [0.90, 0.80, 0.70, None], "eligible": [True, True, True, False],
                         "rank": [1, 2, 3, None]}, index=idx)


def test_fusion_bounded_and_audited():
    sc = scores_frame()
    es = {"2317": {"score": 1.0, "events": ["E1"]}, "2454": {"score": -1.0, "events": ["E2"]},
          "2308": {"score": 1.0, "events": ["E3"]}, "9999": {"score": 1.0, "events": ["E4"]}}
    out, audit = fuse(sc, es, 5)
    assert out.at["2317", "score"] == pytest.approx(0.75) and out.at["2317", "adjustment"] == pytest.approx(0.05)
    assert out.at["2454", "score"] == pytest.approx(0.75)
    assert pd.isna(out.at["2308", "score"]) and out.at["2308", "adjustment"] == 0      # ineligible: no adjustment
    assert "9999" not in out.index and "9999" not in audit                           # cannot create candidates
    assert set(out.columns) >= {"quant_score", "event_score", "adjustment", "score"}
    assert audit["2317"] == {"quant_score": 0.70, "event_score": 1.0, "adjustment": pytest.approx(0.05),
                             "final_score": pytest.approx(0.75), "events": ["E1"]}
    out0, _ = fuse(sc, es, 0)
    assert out0["score"].dropna().tolist() == sc["score"].dropna().tolist()          # adj=0 -> identical


def _store_with_events(fixture_store, tmp_path, rows):
    st = HistoryStore(tmp_path / "evstore")
    for t in ("daily_prices", "institutional", "monthly_revenue", "etf_holdings"):
        st.upsert(t, fixture_store.load(t))
    st.upsert("material_info", rows)
    return st


def test_e2e_events_and_signal(fixture_store, rb, cfg, tmp_path):
    rows = []
    for i, t in enumerate(["2330", "2454", "1101", "2603"]):
        txt = "本公司9月營收創新高，較去年同期成長" if i % 2 == 0 else "本公司下修第四季財測"
        rows.append({"event_key": f"k{i}", "ticker": t, "published_at": "2026-10-26T17:30:00+08:00", "subject": txt,
                     "body": "", "source": "mops_t05st02", "source_url": f"https://mops.example/{i}",
                     "authority": "mops", "available_at": "2026-10-26T17:30:00+08:00"})
    rows.append({"event_key": "future", "ticker": "2317", "published_at": "2026-10-27T10:00:00+08:00",
                 "subject": "本公司營收創新高", "body": "", "source": "x", "source_url": "https://mops.example/f",
                 "authority": "mops", "available_at": "2026-10-27T10:00:00+08:00"})
    st = _store_with_events(fixture_store, tmp_path, rows)
    base = run(st, rb, cfg, tmp_path / "q")
    l2 = run(st, rb, cfg, tmp_path / "l2", llm_opts(tmp_path, events={"enabled": True},
                                                       llm_signal={"enabled": False}))
    l4 = run(st, rb, cfg, tmp_path / "l4", llm_opts(tmp_path, events={"enabled": True},
                                                       llm_signal={"enabled": True, "max_percentile_adjustment": 5}))
    assert base.validation.ok and l2.validation.ok and l4.validation.ok
    assert {e.ticker for e in l2.events} == {"2330", "2454", "1101", "2603"}       # future doc invisible (PIT)
    assert base.doc["orders"] == l2.doc["orders"]                                   # extraction only: no change
    adj = l4.scores["adjustment"]
    assert adj.abs().max() <= 0.05 + 1e-12 and (adj != 0).sum() >= 1
    assert set(l4.scores.index) == set(base.scores.index)
    w = {d["ticker"]: d["target_weight"] for d in l4.doc["decisions"]}
    assert all(x <= 0.235 + 1e-9 for x in w.values()) and 20 <= len(w) <= 30
    ev_obs = [o for o in l4.doc["observations"] if o.get("topic") == "company_event"]
    srcs = {s["source_id"]: s for s in l4.doc["sources"]}
    for o in ev_obs:                                                                # EventFact -> Source(mops)
        assert all(srcs[r]["authority"] == "mops" for r in o["source_ref"])
