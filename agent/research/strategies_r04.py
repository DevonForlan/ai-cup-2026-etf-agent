"""Round 04 strategy set: Quant v1 vs Quant+LLM (narrative / events / bounded signal) vs Crash Guard.

All LLM variants here use the MOCK provider unless a real provider is configured: the mock is a
deterministic keyword classifier, NOT a language model. Results with it validate plumbing, safety
and the *mechanism* of bounded adjustment; they are NOT evidence of LLM alpha.
"""
from __future__ import annotations

import copy

import yaml

from agent.config import ROOT

V1 = yaml.safe_load((ROOT / "config" / "strategy_quant_v1.yaml").read_text(encoding="utf-8"))


def _llm(provider="mock", narrative="template", events=False, signal=False, pct=5, blind=False):
    return {"provider": provider, "blind_mode": blind, "narrative": {"mode": narrative},
            "events": {"enabled": events}, "llm_signal": {"enabled": signal, "max_percentile_adjustment": pct}}


def _s(sid, group, desc, llm=None, guard=False, regime=False, turnover=None):
    ov = {}
    if llm is not None:
        ov["llm"] = llm
    if guard:
        ov["crash_guard"] = {"enabled": True}
    if regime:
        ov["regime.use_v0"] = True
    if turnover:
        t = copy.deepcopy(V1["turnover"])
        t.update(turnover)
        ov["turnover"] = t
    return {"strategy_id": sid, "group": group, "desc": desc, "overrides": ov}


H10 = {"rebalance_every": 10, "min_holding_days": 5, "rebalance_threshold": 0.02}


def registry_r04() -> list[dict]:
    return [
        _s("Q0_v1", "quant", "Quant Core v1 (no LLM)"),
        _s("L1_narr", "llm", "v1 + LLM narrative only", _llm(narrative="llm")),
        _s("L2_events0", "llm", "v1 + event extraction, adjustment 0", _llm(narrative="llm", events=True)),
        _s("L3_ev2", "llm", "v1 + events ±2 pct", _llm(narrative="llm", events=True, signal=True, pct=2)),
        _s("L4_ev5", "llm", "v1 + events ±5 pct", _llm(narrative="llm", events=True, signal=True, pct=5)),
        _s("L5_ev10", "llm", "v1 + events ±10 pct (stress)", _llm(narrative="llm", events=True, signal=True, pct=10)),
        _s("L4_ev5_blind", "llm_blind", "v1 + events ±5, BLIND prompts",
           _llm(narrative="llm", events=True, signal=True, pct=5, blind=True)),
        _s("L4h_h10_ev5", "llm", "10-day rebalance + events ±5 (gives events a chance to act)",
           _llm(narrative="llm", events=True, signal=True, pct=5), turnover=H10),
        _s("Q0h_h10", "quant", "10-day rebalance, no LLM (control for L4h)", turnover=H10),
        _s("Q1_guard", "guard", "v1 + Crash Guard", guard=True),
        _s("Qr_regime", "guard", "v1 + Regime v0 (soft cash)", regime=True),
        _s("Q4_guard_ev5", "guard_llm", "v1 + Crash Guard + events ±5",
           _llm(narrative="llm", events=True, signal=True, pct=5), guard=True),
    ]


def resolve_r04(s: dict) -> dict:
    cfg = copy.deepcopy(V1)
    for k, v in s["overrides"].items():
        node = cfg
        parts = k.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = copy.deepcopy(v)
    cfg["strategy_name"] = s["strategy_id"]
    return cfg
